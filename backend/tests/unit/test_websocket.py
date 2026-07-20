"""CR12 WebSocket tests.

Two layers:

1. ConnectionManager unit tests (no network, no FastAPI)
   - local connect/disconnect bookkeeping
   - dispatch routing for user / tenant channels
   - publish_to_user uses the injected Redis client

2. Endpoint + integration tests via Starlette TestClient
   - JWT auth via query param (valid / invalid / wrong-type token)
   - ping → pong heartbeat
   - send_notification fans out to manager.publish_to_user
   - execute_session emits compgen.session.updated on running/ready
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# ---------------------------------------------------------------------------
# 1. ConnectionManager unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_and_disconnect_track_local_sockets():
    from app.core.websocket import ConnectionManager

    mgr = ConnectionManager()
    ws = MagicMock()
    await mgr.connect("t1", "u1", ws)
    assert ("t1", "u1") in mgr._user_sockets
    assert ws in mgr._user_sockets[("t1", "u1")]
    assert ws in mgr._tenant_sockets["t1"]

    await mgr.disconnect("t1", "u1", ws)
    assert ("t1", "u1") not in mgr._user_sockets
    assert "t1" not in mgr._tenant_sockets


@pytest.mark.asyncio
async def test_dispatch_user_channel_sends_to_local_socket():
    from app.core.websocket import ConnectionManager

    mgr = ConnectionManager()
    ws = MagicMock()
    ws.send_text = AsyncMock()
    await mgr.connect("tenantA", "userA", ws)

    await mgr.dispatch("ws:tenant:tenantA:user:userA", '{"type":"ping"}')
    ws.send_text.assert_awaited_once_with('{"type":"ping"}')


@pytest.mark.asyncio
async def test_dispatch_tenant_channel_sends_to_all_tenant_sockets():
    from app.core.websocket import ConnectionManager

    mgr = ConnectionManager()
    ws_a, ws_b = MagicMock(), MagicMock()
    ws_a.send_text = AsyncMock()
    ws_b.send_text = AsyncMock()
    await mgr.connect("tenantA", "userA", ws_a)
    await mgr.connect("tenantA", "userB", ws_b)

    await mgr.dispatch("ws:tenant:tenantA:broadcast", '{"x":1}')
    ws_a.send_text.assert_awaited_once_with('{"x":1}')
    ws_b.send_text.assert_awaited_once_with('{"x":1}')


@pytest.mark.asyncio
async def test_dispatch_unknown_channel_is_noop():
    from app.core.websocket import ConnectionManager

    mgr = ConnectionManager()
    ws = MagicMock()
    ws.send_text = AsyncMock()
    await mgr.connect("t", "u", ws)
    await mgr.dispatch("not-a-channel", "msg")
    ws.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_to_user_publishes_via_redis_client():
    from app.core.websocket import ConnectionManager, user_channel

    mgr = ConnectionManager()
    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock()
    mgr.set_redis_client(fake_redis)

    payload = {"type": "notification.new", "payload": {"id": "abc"}}
    await mgr.publish_to_user("t1", "u1", payload)

    fake_redis.publish.assert_awaited_once_with(
        user_channel("t1", "u1"), json.dumps(payload)
    )


@pytest.mark.asyncio
async def test_publish_swallows_redis_errors():
    from app.core.websocket import ConnectionManager

    mgr = ConnectionManager()
    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock(side_effect=RuntimeError("boom"))
    mgr.set_redis_client(fake_redis)

    # Must not raise — best-effort.
    await mgr.publish_to_user("t1", "u1", {"type": "x"})


# ---------------------------------------------------------------------------
# 2. Endpoint tests via Starlette TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def ws_client(user, access_token):
    """TestClient with get_db pointed at a fresh engine.

    The TestClient drives the app on its own anyio portal/loop, distinct
    from the outer pytest-asyncio loop. Reusing the test `db` session
    across that boundary triggers asyncpg's "different loop" guard, so
    we spin up a dedicated engine inside the override.
    """
    from app.config import settings as app_settings
    from app.database import get_db
    from app.main import app
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    test_db_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"

    # Create the engine lazily inside the portal loop on first use.
    state: dict[str, object] = {"engine": None, "factory": None}

    async def _override_get_db():
        if state["factory"] is None:
            engine = create_async_engine(test_db_url, echo=False)
            state["engine"] = engine
            state["factory"] = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
        factory = state["factory"]
        async with factory() as session:  # type: ignore[misc]
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # WS endpoint opens its own short-lived session via `async_session()` (not
    # via Depends). Repoint that factory at the test DB for the test run.
    from app.modules.notification import router as notif_router

    original_factory = notif_router.async_session

    def _factory_proxy():
        if state["factory"] is None:
            engine = create_async_engine(test_db_url, echo=False)
            state["engine"] = engine
            state["factory"] = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
        return state["factory"]()  # type: ignore[misc]

    notif_router.async_session = _factory_proxy  # type: ignore[assignment]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, access_token
    finally:
        notif_router.async_session = original_factory  # type: ignore[assignment]
        app.dependency_overrides.clear()
    # The engine outlives the TestClient portal — dispose is a best-effort
    # noop here; the test process tearing down releases its connections.


def test_ws_rejects_invalid_token(ws_client):
    client, _ = ws_client
    # Starlette's TestClient raises WebSocketDisconnect when the server
    # closes the connection before accept (1008 policy violation here).
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws?token=not-a-real-jwt"),
    ):
        pass


def test_ws_rejects_refresh_token(ws_client, user, tenant):
    from app.core.security import create_refresh_token

    client, _ = ws_client
    refresh = create_refresh_token(str(user.id), str(tenant.id))
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/api/ws?token={refresh}"),
    ):
        pass


def test_ws_accepts_valid_jwt_and_pong(ws_client):
    client, token = ws_client
    with client.websocket_connect(f"/api/ws?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        msg = ws.receive_text()
        assert json.loads(msg) == {"type": "pong"}


def test_ws_disconnect_cleans_up_manager(ws_client, user):
    from app.core.websocket import manager

    client, token = ws_client
    user_id = str(user.id)
    tenant_id = str(user.tenant_id)
    with client.websocket_connect(f"/api/ws?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        ws.receive_text()
        # Connection is registered while the socket is open.
        assert (tenant_id, user_id) in manager._user_sockets

    # On exit, TestClient closes the socket; the endpoint's finally-block
    # runs disconnect() which removes the empty bucket.
    assert (tenant_id, user_id) not in manager._user_sockets


# ---------------------------------------------------------------------------
# 3. Integration with notification_service.send_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification_publishes_to_user(db, user, tenant):
    from app.modules.notification import service as notification_service
    from app.modules.notification.models import NotificationTemplate

    db.add(
        NotificationTemplate(
            code="cr12_test_template",
            subject_template="Hello {{ recipient_name }}",
            body_template="Body for {{ recipient_name }}",
        )
    )
    await db.commit()

    with patch(
        "app.core.websocket.manager.publish_to_user",
        new=AsyncMock(),
    ) as pub:
        await notification_service.send_notification(
            db,
            tenant.id,
            "cr12_test_template",
            user.id,
            user.email,
            {"recipient_name": user.first_name or user.email},
            event_type="general",
        )

    assert pub.await_count == 1
    args, _ = pub.call_args
    assert args[0] == str(tenant.id)
    assert args[1] == str(user.id)
    payload = args[2]
    assert payload["type"] == "notification.new"
    assert payload["payload"]["template_code"] == "cr12_test_template"


# ---------------------------------------------------------------------------
# 4. Integration with execute_session — broadcast for running / ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_session_broadcasts_running_and_ready(db, user, tenant):
    """Drive a `competence_indicators` session through pending → ready and
    verify the manager received `running` and `ready` events.

    LLM is mocked: `_generate_with_retries` returns a minimal valid model.
    """
    from app.modules.ai_competence_generation import tasks
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )
    from app.modules.ai_competence_generation.schemas import (
        GeneratedIndicator,
        GeneratedIndicatorsSchema,
    )
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        SkillLevel,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    group = CompetenceGroup(tenant_id=tenant.id, title="G")
    db.add(group)
    await db.commit()
    await db.refresh(group)

    comp = Competence(tenant_id=tenant.id, title="C", group_id=group.id)
    db.add(comp)
    db.add(SkillLevel(tenant_id=tenant.id, title="basic", sort_index=1))
    await db.commit()
    await db.refresh(comp)

    sess = CompetenceGenerationSession(
        tenant_id=tenant.id,
        user_id=user.id,
        scope="competence_indicators",
        target_id=comp.id,
        params={"with_indicators": True},
        base_snapshot={"competence": {"indicators": []}},
        status="pending",
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    fake_result = GeneratedIndicatorsSchema(
        indicators=[GeneratedIndicator(title="ind1", skill_level="basic")]
    )

    bind = db.bind  # AsyncEngine bound to the test DB

    factory = async_sessionmaker(bind, expire_on_commit=False)

    with (
        patch.object(
            tasks,
            "_generate_with_retries",
            new=AsyncMock(return_value=(fake_result, None)),
        ),
        patch(
            "app.core.websocket.manager.publish_to_user",
            new=AsyncMock(),
        ) as pub,
    ):
        result = await tasks.execute_session(factory, sess.id)

    assert result["status"] == "ready"

    # HRP-71 phase 4 mixes `compgen.progress` events into the same publisher;
    # only `compgen.session.updated` carries `status`, so filter before reading.
    statuses = [
        call.args[2]["payload"]["status"]
        for call in pub.call_args_list
        if call.args[2].get("type") == "compgen.session.updated"
    ]
    assert "running" in statuses
    assert "ready" in statuses
    types = {call.args[2]["type"] for call in pub.call_args_list}
    assert "compgen.session.updated" in types


@pytest.mark.asyncio
async def test_execute_session_broadcasts_error(db, user, tenant):
    """A bogus target_id triggers `_terminate` which should still broadcast."""
    from app.modules.ai_competence_generation import tasks
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sess = CompetenceGenerationSession(
        tenant_id=tenant.id,
        user_id=user.id,
        scope="group",  # but target_id is None below → insufficient_data
        target_id=None,
        params={},
        base_snapshot={},
        status="pending",
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    with patch(
        "app.core.websocket.manager.publish_to_user",
        new=AsyncMock(),
    ) as pub:
        result = await tasks.execute_session(factory, sess.id)

    assert result["status"] == "error"
    assert result["error_code"] == "insufficient_data"

    statuses = [
        call.args[2]["payload"]["status"]
        for call in pub.call_args_list
        if call.args[2].get("type") == "compgen.session.updated"
    ]
    assert "running" in statuses
    assert "error" in statuses
