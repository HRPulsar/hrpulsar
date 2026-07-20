"""Production uvicorn launcher.

Runs the FastAPI app with WebSocket protocol-level keepalive disabled
(``ws_ping_interval=None``). The CLI flag ``--ws-ping-interval`` is typed
as float and cannot express ``None``, so a Python entry-point is required
to turn the websockets library's keepalive task off entirely. Application
heartbeat lives in ``app.modules.notification.router``.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ.get("UVICORN_WORKERS", "2")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )


if __name__ == "__main__":
    main()
