from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import signal
import struct
import termios
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import socketio
import starlette.applications
import starlette.responses
import starlette.routing
import starlette.staticfiles
import uvicorn

import config


# ---------------------------------------------------------------------------
# PTY session management
# ---------------------------------------------------------------------------
@dataclass
class PtySession:
    pid: int
    master_fd: int
    reaped: bool = False
    keyin_event: asyncio.Event | None = None


sessions: dict[str, PtySession] = {}

_timeout_task: asyncio.Task[None] | None = None


def _parse_size(data: dict[str, Any]) -> tuple[int, int]:
    """Extract (cols, rows) from *data*, clamped to [1, 4096]."""
    try:
        cols = max(1, min(4096, int(data.get("cols", 80))))
        rows = max(1, min(4096, int(data.get("rows", 24))))
    except (ValueError, TypeError):
        cols, rows = 80, 24
    return cols, rows


def _exec_shell(slave_fd: int, execfail_w: int) -> None:
    """Child process: set up controlling terminal and exec the shell.

    Never returns on success (execve replaces the process).
    On failure, writes to *execfail_w* and calls ``os._exit(127)``.
    """
    try:
        os.setsid()
        tty_name = os.ttyname(slave_fd)
        os.close(slave_fd)
        slave_fd = os.open(tty_name, os.O_RDWR)
        # Reopen sets ctty on FreeBSD; TIOCSCTTY is needed on Linux.
        with contextlib.suppress(OSError):
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        for fd in range(3):
            os.dup2(slave_fd, fd)
        if slave_fd > 2:
            os.close(slave_fd)
        os.umask(config.UMASK)
        os.chdir(config.CWD)
        os.execve(config.SHELL, config.ARGS, config.ENV)
    except OSError:
        with contextlib.suppress(OSError):
            os.write(execfail_w, b"@")
    os._exit(127)


def _open_pty_session(cols: int, rows: int) -> tuple[int, int]:
    """Open a PTY, fork, exec the shell, and return *(pid, master_fd)*.

    The master fd is set to non-blocking before returning.
    Uses a pipe with O_CLOEXEC to detect exec failure: if execve
    succeeds the pipe is closed automatically; if it fails the child
    writes a byte before exiting.
    Raises :class:`RuntimeError` or :class:`OSError` on failure.
    """
    master_fd, slave_fd = os.openpty()
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    fcntl.ioctl(
        master_fd, termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, cols, 0, 0),
    )

    execfail_r, execfail_w = os.pipe2(os.O_CLOEXEC)
    try:
        # Suppress Python 3.12's DeprecationWarning about fork() in
        # multi-threaded processes; the immediate execve() is safe.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*fork.*", category=DeprecationWarning
            )
            pid = os.fork()
    except OSError:
        os.close(execfail_r)
        os.close(execfail_w)
        os.close(master_fd)
        os.close(slave_fd)
        raise RuntimeError("fork failed")

    if pid == 0:
        os.close(execfail_r)
        _exec_shell(slave_fd, execfail_w)  # never returns

    os.close(execfail_w)
    os.close(slave_fd)
    exec_failed = os.read(execfail_r, 1) != b""
    os.close(execfail_r)

    if exec_failed:
        os.close(master_fd)
        with contextlib.suppress(OSError, ChildProcessError):
            os.waitpid(pid, 0)
        raise RuntimeError("failed to exec shell")

    return pid, master_fd


async def _handle_shell_exit(sid: str) -> None:
    """Notify client and clean up session."""
    session = sessions.get(sid)
    if session is None:
        return
    reason = "shell exited (status unavailable)"
    loop = asyncio.get_running_loop()
    try:
        _, status = await asyncio.wait_for(
            loop.run_in_executor(None, os.waitpid, session.pid, 0),
            timeout=1.0,
        )
        session.reaped = True
        if os.WIFEXITED(status):
            reason = f"shell exited ({os.WEXITSTATUS(status)})"
        elif os.WIFSIGNALED(status):
            reason = f"shell killed by signal {os.WTERMSIG(status)}"
    except (ChildProcessError, OSError):
        session.reaped = True
    except TimeoutError:
        pass
    with contextlib.suppress(Exception):
        await sio.emit("close-connection", reason, to=sid)
    await _cleanup_session(sid)


def _on_pty_readable(
    sid: str, master_fd: int, loop: asyncio.AbstractEventLoop
) -> None:
    try:
        data = os.read(master_fd, 4096)
        if not data:
            # EOF: FreeBSD returns b"", Linux usually raises EIO.
            raise OSError("EOF on PTY master")
        loop.create_task(
            sio.emit("output", data.decode("utf-8", errors="replace"), to=sid)
        )
    except OSError:
        loop.remove_reader(master_fd)
        loop.create_task(_handle_shell_exit(sid))


async def _cleanup_session(sid: str) -> None:
    """Remove *sid* and kill its child process.  Idempotent."""
    global _timeout_task
    session = sessions.pop(sid, None)
    if session is None:
        return
    loop = asyncio.get_running_loop()
    loop.remove_reader(session.master_fd)
    with contextlib.suppress(OSError):
        os.close(session.master_fd)
    if not session.reaped:
        try:
            os.kill(session.pid, signal.SIGTERM)
            await asyncio.wait_for(
                loop.run_in_executor(None, os.waitpid, session.pid, 0),
                timeout=1.0,
            )
        except (ProcessLookupError, ChildProcessError, OSError):
            pass
        except TimeoutError:
            with contextlib.suppress(OSError):
                os.kill(session.pid, signal.SIGKILL)
            with contextlib.suppress(OSError, ChildProcessError, TimeoutError):
                await asyncio.wait_for(
                    loop.run_in_executor(None, os.waitpid, session.pid, 0),
                    timeout=1.0,
                )

    if config.NO_SESSION_TIMEOUT > 0 and not _sessions:
        if _timeout_task is None or _timeout_task.done():
            _timeout_task = loop.create_task(_no_session_timeout_handler())

    _logger.info(f"Session closed on {session.tty_name}")


async def _keyin_timeout_handler(sid: str) -> None:
    """Disconnect the session after keyin_timeout seconds without key input."""
    session = sessions.get(sid)
    if session is None:
        return
    assert session.keyin_event is not None
    while True:
        session.keyin_event.clear()
        try:
            await asyncio.wait_for(
                session.keyin_event.wait(), timeout=config.KEYIN_TIMEOUT,
            )
        except TimeoutError:
            with contextlib.suppress(Exception):
                await sio.emit(
                    "close-connection",
                    f"key input timeout ({config.KEYIN_TIMEOUT}s)",
                    to=sid,
                )
            await _cleanup_session(sid)
            return


async def _no_session_timeout_handler() -> None:
    """Shut down the server on no-session timeout."""
    try:
        await asyncio.sleep(config.NO_SESSION_TIMEOUT)
    except asyncio.CancelledError:
        return
    if sessions:
        return
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True


# ---------------------------------------------------------------------------
# Socket.IO server
# ---------------------------------------------------------------------------
sio: socketio.AsyncServer = socketio.AsyncServer(
    async_mode="asgi", cors_allowed_origins=config.CORS_ALLOWED_ORIGINS,
    ping_timeout=3.0, ping_interval=5.0,
)


@sio.event  # type: ignore[untyped-decorator]
async def connect(
    sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None
) -> None:
    global _timeout_task
    cols, rows = _parse_size(auth or {})

    try:
        pid, master_fd = _open_pty_session(cols, rows)
    except (RuntimeError, OSError) as e:
        with contextlib.suppress(Exception):
            await sio.emit("close-connection", str(e), to=sid)
        return

    loop = asyncio.get_running_loop()
    sessions[sid] = PtySession(pid=pid, master_fd=master_fd)
    if config.NO_SESSION_TIMEOUT > 0:
        if not (_timeout_task is None or _timeout_task.done()):
            _timeout_task.cancel()
        _timeout_task = None
    loop.add_reader(master_fd, _on_pty_readable, sid, master_fd, loop)
    if config.KEYIN_TIMEOUT > 0:
        sessions[sid].keyin_event = asyncio.Event()
        loop.create_task(_keyin_timeout_handler(sid))


@sio.event  # type: ignore[untyped-decorator]
async def disconnect(sid: str) -> None:
    await _cleanup_session(sid)


@sio.event  # type: ignore[untyped-decorator]
async def input(sid: str, data: str) -> None:
    session = sessions.get(sid)
    if session is None:
        return
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
        except OSError:
            break


@sio.event  # type: ignore[untyped-decorator]
async def resize(sid: str, data: dict[str, int]) -> None:
    session = sessions.get(sid)
    if session is None:
        return
    cols, rows = _parse_size(data)
    fcntl.ioctl(
        session.master_fd, termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, cols, 0, 0),
    )


# ---------------------------------------------------------------------------
# ASGI app
# ---------------------------------------------------------------------------
async def _lifespan(_: Any) -> AsyncIterator[None]:
    global _timeout_task
    shutdown_event = asyncio.Event()

    async def _shutdown_notifier() -> None:
        """Wait for the shutdown event, notify clients, then stop uvicorn."""
        await shutdown_event.wait()
        for sid in list(sessions):
            with contextlib.suppress(Exception):
                await sio.emit("close-connection", "server shutdown", to=sid)
        await asyncio.sleep(1.0)
        if _uvicorn_server is not None:
            # Uvicorn closes listening sockets and transports, then
            # runs lifespan shutdown (post-yield) for final cleanup.
            _uvicorn_server.should_exit = True

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
        _timeout_task = loop.create_task(_no_session_timeout_handler())

    yield

    for sid in list(sessions):
        await _cleanup_session(sid)
    with contextlib.suppress(Exception):
        await sio.shutdown()


_starlette = starlette.applications.Starlette(
    routes=[
        starlette.routing.Route(
            "/",
            lambda _: starlette.responses.FileResponse("static/_index.html"),
        ),
        starlette.routing.Mount(
            "/static", starlette.staticfiles.StaticFiles(directory="static")
        ),
    ],
    lifespan=contextlib.asynccontextmanager(_lifespan),
)
app: socketio.ASGIApp = socketio.ASGIApp(sio, _starlette, socketio_path="sio")

_uvicorn_server: uvicorn.Server | None = None

if __name__ == "__main__":
    _uvicorn_kwargs: dict[str, Any] = {}
    if config.SOCKET:
        _uvicorn_kwargs["uds"] = config.SOCKET
    else:
        _uvicorn_kwargs["host"] = config.HOST
        _uvicorn_kwargs["port"] = config.PORT
    _uvicorn_kwargs["timeout_graceful_shutdown"] = 10.0
    _uvicorn_config = uvicorn.Config(app, **_uvicorn_kwargs)
    _uvicorn_server = uvicorn.Server(_uvicorn_config)
    with contextlib.suppress(KeyboardInterrupt):
        _uvicorn_server.run()
