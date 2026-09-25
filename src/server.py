from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator
from typing import Any

import starlette.applications
import starlette.routing

from . import globalvars as g
from . import session as sm
from . import static


async def _lifespan(_: Any) -> AsyncIterator[None]:
    uvicorn_server = g.uvicorn_server
    assert uvicorn_server is not None

    shutdown_event = asyncio.Event()

    async def _shutdown_handler() -> None:
        """Wait for shutdown, close connections, then stop uvicorn."""
        await shutdown_event.wait()
        await sm.close_all_connections()
        uvicorn_server.should_exit = True

    loop = asyncio.get_running_loop()
    loop.create_task(_shutdown_handler())

    def _on_signal() -> None:
        # Restore default handlers so a second signal force-kills.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.remove_signal_handler(sig)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, _on_signal)

    yield

    await sm.cleanup_all_sessions()


app = starlette.applications.Starlette(
    routes=[
        starlette.routing.WebSocketRoute("/ws", sm.ws_endpoint),
        starlette.routing.Route("/", static.endpoint),
        starlette.routing.Route("/static/{path:path}", static.endpoint),
    ],
    lifespan=contextlib.asynccontextmanager(_lifespan),
)
