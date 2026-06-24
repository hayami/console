from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import struct
import termios
from collections.abc import AsyncIterator
from typing import Any

import socketio
import starlette.applications
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware


from . import config
from . import globalvars as g
from . import session as sm
from . import staticfiles


_logger = logging.getLogger("uvicorn")


def _parse_size(data: dict[str, Any]) -> tuple[int, int]:
    """Extract (cols, rows) from *data*, clamped to [1, 4096]."""
    try:
        cols = max(1, min(4096, int(data.get("cols", 80))))
        rows = max(1, min(4096, int(data.get("rows", 24))))
    except (ValueError, TypeError):
        cols, rows = 80, 24
    return cols, rows


def _on_pty_readable(
    sid: str, master_fd: int, loop: asyncio.AbstractEventLoop
) -> None:
    try:
        data = os.read(master_fd, 4096)
        if not data:
            # EOF: FreeBSD returns b"", Linux usually raises EIO.
            raise OSError("EOF on PTY master")
        loop.create_task(
            g.sio.emit(
                "output", data.decode("utf-8", errors="replace"), to=sid
            )
        )
    except OSError:
        loop.remove_reader(master_fd)
        loop.create_task(sm.handle_shell_exit(sid))


# ---------------------------------------------------------------------------

@g.sio.event  # type: ignore[untyped-decorator]
async def connect(
    sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None
) -> bool:
    cols, rows = _parse_size(auth or {})

    try:
        pid, master_fd, tty_name = sm.open_pty_session(cols, rows)
    except (RuntimeError, OSError) as e:
        with contextlib.suppress(Exception):
            await g.sio.emit("close-connection", str(e), to=sid)
        # Accept the connection so the client can receive
        # the close-connection event with the error reason.
        return True

    loop = asyncio.get_running_loop()
    sm.sessions[sid] = sm.PtySession(
        pid=pid,
        master_fd=master_fd,
        tty_name=tty_name,
    )
    if config.NO_SESSION_TIMEOUT > 0:
        if not (sm.timeout_task is None
                or sm.timeout_task.done()):
            sm.timeout_task.cancel()
        sm.timeout_task = None
    loop.add_reader(master_fd, _on_pty_readable, sid, master_fd, loop)
    if config.KEYIN_TIMEOUT > 0:
        sm.sessions[sid].keyin_event = asyncio.Event()
        sm.sessions[sid].keyin_task = loop.create_task(
            sm.keyin_timeout_handler(sid),
        )

    _logger.info(f"New session on {tty_name}")
    return True


@g.sio.event  # type: ignore[untyped-decorator]
async def disconnect(sid: str) -> bool:
    await sm.cleanup_session(sid)
    return True


@g.sio.event  # type: ignore[untyped-decorator]
async def input(sid: str, data: str) -> bool:
    session = sm.sessions.get(sid)
    if session is None:
        return False
    if session.keyin_event is not None:
        session.keyin_event.set()
    loop = asyncio.get_running_loop()
    buf = data.encode()
    while buf:
        try:
            n = os.write(session.master_fd, buf)
            buf = buf[n:]
        except BlockingIOError:
            waiter: asyncio.Future[None] = loop.create_future()
            loop.add_writer(session.master_fd, waiter.set_result, None)
            try:
                await waiter
            finally:
                loop.remove_writer(session.master_fd)
            # Session may have been cleaned up while awaiting.
            if sm.sessions.get(sid) is not session:
                break
        except OSError:
            break
    return True


@g.sio.event  # type: ignore[untyped-decorator]
async def resize(sid: str, data: dict[str, int]) -> bool:
    session = sm.sessions.get(sid)
    if session is None:
        return False
    cols, rows = _parse_size(data)
    fcntl.ioctl(
        session.master_fd, termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, cols, 0, 0),
    )
    return True


# ---------------------------------------------------------------------------
# ASGI app
# ---------------------------------------------------------------------------
async def _lifespan(_: Any) -> AsyncIterator[None]:
    if g.uvicorn_server is None:
        raise SystemExit(
            "Do not run this app directly with the uvicorn command.\n"
            "Use: python3 -m consoleserver"
        )

    shutdown_event = asyncio.Event()

    async def _shutdown_notifier() -> None:
        """Wait for the shutdown event, notify clients, then stop uvicorn."""
        await shutdown_event.wait()
        for sid in list(sm.sessions):
            with contextlib.suppress(Exception):
                await g.sio.emit(
                    "close-connection", "server shutdown", to=sid
                )
        await asyncio.sleep(1.0)
        assert g.uvicorn_server is not None
        g.uvicorn_server.should_exit = True

    def _on_signal() -> None:
        # Restore default handlers so a second signal force-kills.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.remove_signal_handler(sig)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    loop.create_task(_shutdown_notifier())

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, _on_signal)

    if config.NO_SESSION_TIMEOUT > 0:
        sm.timeout_task = loop.create_task(
            sm.no_session_timeout_handler()
        )

    yield

    for sid in list(sm.sessions):
        await sm.cleanup_session(sid)
    with contextlib.suppress(Exception):
        await g.sio.shutdown()


_starlette = starlette.applications.Starlette(
    routes=[
        starlette.routing.Route("/", staticfiles.endpoint),
        starlette.routing.Route("/static/{path:path}", staticfiles.endpoint),
    ],
    middleware=[
        Middleware(GZipMiddleware, minimum_size=1024, compresslevel=6),
    ],
    lifespan=contextlib.asynccontextmanager(_lifespan),
)
app: socketio.ASGIApp = socketio.ASGIApp(
    g.sio, _starlette, socketio_path="sio"
)
