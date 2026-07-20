"""In-process event bus for inter-module communication.

Modules publish events, other modules subscribe to handle them.
For SaaS scale, can be replaced with Redis Pub/Sub or Celery tasks.
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable]] = {}


def subscribe(event: str, handler: Callable) -> None:
    _handlers.setdefault(event, []).append(handler)


async def publish(event: str, data: dict[str, Any]) -> None:
    for handler in _handlers.get(event, []):
        try:
            await handler(data)
        except Exception:
            logger.exception("Event handler error for %s", event)
