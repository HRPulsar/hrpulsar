"""WebSocket connection manager with Redis pub/sub fan-out.

Web processes hold local sockets in `_local`; Celery workers and other
web replicas reach them by `PUBLISH`-ing to a per-user / per-tenant
channel. A background `_run_listener` task in each web process
`PSUBSCRIBE`-s and forwards inbound messages to its local sockets.

Publish path is best-effort: failures are logged, never raised, so a
flaky Redis cannot break a business commit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger(__name__)


def user_channel(tenant_id: str, user_id: str) -> str:
    return f"ws:tenant:{tenant_id}:user:{user_id}"


def tenant_channel(tenant_id: str) -> str:
    return f"ws:tenant:{tenant_id}:broadcast"


_USER_CHANNEL_PATTERN = "ws:tenant:*:user:*"
_TENANT_CHANNEL_PATTERN = "ws:tenant:*:broadcast"


class ConnectionManager:
    def __init__(self) -> None:
        self._user_sockets: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._tenant_sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._redis: aioredis.Redis | None = None
        self._listener_task: asyncio.Task[None] | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def set_redis_client(self, client: aioredis.Redis | None) -> None:
        """Tests inject a fake/preconfigured Redis client here."""
        self._redis = client

    async def connect(self, tenant_id: str, user_id: str, ws: WebSocket) -> None:
        # No lock needed: Python asyncio is cooperative — set/dict mutations
        # between awaits run atomically inside a single event loop.
        self._user_sockets[(tenant_id, user_id)].add(ws)
        self._tenant_sockets[tenant_id].add(ws)

    async def disconnect(self, tenant_id: str, user_id: str, ws: WebSocket) -> None:
        sockets = self._user_sockets.get((tenant_id, user_id))
        if sockets is not None:
            sockets.discard(ws)
            if not sockets:
                self._user_sockets.pop((tenant_id, user_id), None)
        tenant_sockets = self._tenant_sockets.get(tenant_id)
        if tenant_sockets is not None:
            tenant_sockets.discard(ws)
            if not tenant_sockets:
                self._tenant_sockets.pop(tenant_id, None)

    async def publish_to_user(
        self, tenant_id: str, user_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            client = await self._get_client()
            await client.publish(user_channel(tenant_id, user_id), json.dumps(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ws publish_to_user failed: %s", exc)

    async def publish_to_tenant(self, tenant_id: str, payload: dict[str, Any]) -> None:
        try:
            client = await self._get_client()
            await client.publish(tenant_channel(tenant_id), json.dumps(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ws publish_to_tenant failed: %s", exc)

    async def _send_local(self, sockets: set[WebSocket], message: str) -> None:
        for ws in list(sockets):
            try:
                await ws.send_text(message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws send failed: %s", exc)

    async def dispatch(self, channel: str, message: str) -> None:
        """Forward a Redis-delivered message to local sockets matching channel."""
        parts = channel.split(":")
        # ws:tenant:{t}:user:{u}
        if len(parts) == 5 and parts[0] == "ws" and parts[3] == "user":
            sockets = self._user_sockets.get((parts[2], parts[4]))
            if sockets:
                await self._send_local(sockets, message)
            return
        # ws:tenant:{t}:broadcast
        if len(parts) == 4 and parts[0] == "ws" and parts[3] == "broadcast":
            sockets = self._tenant_sockets.get(parts[2])
            if sockets:
                await self._send_local(sockets, message)

    async def _run_listener(self) -> None:
        try:
            client = await self._get_client()
            pubsub = client.pubsub()
            await pubsub.psubscribe(_USER_CHANNEL_PATTERN, _TENANT_CHANNEL_PATTERN)
            logger.info("ws redis listener started")
            async for msg in pubsub.listen():
                msg_type = msg.get("type")
                if msg_type not in ("pmessage", "message"):
                    continue
                channel = msg.get("channel")
                data = msg.get("data")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                if isinstance(data, bytes):
                    data = data.decode()
                if not channel or not isinstance(data, str):
                    continue
                try:
                    await self.dispatch(channel, data)
                except Exception:
                    logger.exception("ws dispatch failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            # On shutdown ``stop_listener`` cancels this task. The cancel
            # propagates into ``pubsub.listen()`` mid-``readline``; inside
            # redis-py the cancel is swallowed by ``asyncio.timeouts`` and
            # re-raised as ``redis.TimeoutError``, which would otherwise
            # spam ERROR logs on every deploy. ``Task.cancelling()`` lets
            # us distinguish "we asked for this" from a real Redis crash.
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                logger.debug("ws redis listener stopped during shutdown")
            else:
                logger.exception("ws redis listener crashed")

    async def start_listener(self) -> None:
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._run_listener())

    async def stop_listener(self) -> None:
        task = self._listener_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._listener_task = None
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()  # type: ignore[attr-defined]
            self._redis = None


manager = ConnectionManager()
