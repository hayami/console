from __future__ import annotations

import socketio
import uvicorn

from consoleserver import config


sio: socketio.AsyncServer = socketio.AsyncServer(
    async_mode="asgi", cors_allowed_origins=config.CORS_ALLOWED_ORIGINS,
    ping_timeout=3.0, ping_interval=5.0,
)
uvicorn_server: uvicorn.Server | None = None
