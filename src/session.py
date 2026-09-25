from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import struct
import termios
import warnings
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from starlette.websockets import WebSocket, WebSocketDisconnect

from . import execshell


_logger = logging.getLogger("uvicorn")

# Close codes are defined in the IANA WebSocket Close Code Registry.
WEBSOCKET_CLOSE_NORMAL = 1000
WEBSOCKET_CLOSE_GOING_AWAY = 1001
WEBSOCKET_CLOSE_INTERNAL_ERROR = 1011


@dataclass
class PtySession:
    pid: int
    master_fd: int
    tty_name: str
    reaped: bool = False


sessions: dict[str, PtySession] = {}
connections: dict[str, WebSocket] = {}


def _truncate(reason: str | Exception) -> str:
    reason = str(reason)
    max_bytes = 123  # RFC 6455 close-reason limit in UTF-8 bytes.
    return reason.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _parse_size(data: dict[str, Any]) -> tuple[int, int]:
    """Extract (cols, rows) from *data*, clamped to [1, 4096]."""
    try:
        cols = max(1, min(4096, int(data.get("cols", 80))))
        rows = max(1, min(4096, int(data.get("rows", 24))))
    except (ValueError, TypeError):
        cols, rows = 80, 24
    return cols, rows


async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    sid = uuid4().hex
    connections[sid] = websocket
    cols, rows = _parse_size({
        "cols": websocket.query_params.get("cols", 80),
        "rows": websocket.query_params.get("rows", 24),
    })

    try:
        pid, master_fd, tty_name = _open_pty_session(cols, rows)
    except (RuntimeError, OSError) as e:
        with contextlib.suppress(OSError, RuntimeError):
            await websocket.close(
                code=WEBSOCKET_CLOSE_INTERNAL_ERROR,
                reason=_truncate(e),
            )
        connections.pop(sid, None)
        return

    loop = asyncio.get_running_loop()
    sessions[sid] = PtySession(
        pid=pid,
        master_fd=master_fd,
        tty_name=tty_name,
    )
    loop.add_reader(master_fd, _on_pty_readable, sid, master_fd, loop)

    _logger.info(f"New session on {tty_name}")
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            event = message.get("type")
            if event == "input":
                await _handle_input(sid, message.get("data", ""))
            elif event == "resize":
                _handle_resize(sid, message)
    except WebSocketDisconnect:
        pass
    finally:
        await _cleanup_session(sid)
        connections.pop(sid, None)


def _open_pty_session(cols: int, rows: int) -> tuple[int, int, str]:
    """Open a PTY, fork, exec the shell, and return
    *(pid, master_fd, tty_name)*.

    The master fd is set to non-blocking before returning.
    Uses a pipe with O_CLOEXEC to detect exec failure: if execve
    succeeds the pipe is closed automatically; if it fails the child
    writes a byte before exiting.
    Raises :class:`RuntimeError` or :class:`OSError` on failure.
    """
    master_fd, slave_fd = os.openpty()
    try:
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        fcntl.ioctl(
            master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )
        execfail_r, execfail_w = os.pipe2(os.O_CLOEXEC)
    except OSError:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    try:
        # Suppress Python 3.12's DeprecationWarning about fork() in
        # multi-threaded processes; the immediate execve() is safe.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=".*fork.*",
                category=DeprecationWarning,
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
        os.close(master_fd)
        execshell.execshell(slave_fd, execfail_w)  # never returns

    tty_name = os.ttyname(slave_fd)
    os.close(slave_fd)
    os.close(execfail_w)
    exec_failed = os.read(execfail_r, 1) != b""
    os.close(execfail_r)

    if exec_failed:
        os.close(master_fd)
        with contextlib.suppress(OSError, ChildProcessError):
            os.waitpid(pid, 0)
        raise RuntimeError("failed to exec shell")

    return pid, master_fd, tty_name


def _on_pty_readable(
    sid: str, master_fd: int, loop: asyncio.AbstractEventLoop
) -> None:
    try:
        data = os.read(master_fd, 4096)
        if not data:
            # EOF: FreeBSD returns b"", Linux usually raises EIO.
            raise OSError("EOF on PTY master")
        websocket = connections.get(sid)
        if websocket is not None:

            async def send_output() -> None:
                with contextlib.suppress(OSError, RuntimeError):
                    await websocket.send_json({
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace"),
                    })

            loop.create_task(send_output())
    except OSError:
        loop.remove_reader(master_fd)
        loop.create_task(_handle_shell_exit(sid))


async def _handle_input(sid: str, data: Any) -> None:
    session = sessions.get(sid)
    if session is None or not isinstance(data, str):
        return
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
            if sessions.get(sid) is not session:
                break
        except OSError:
            break


def _handle_resize(sid: str, data: dict[str, Any]) -> None:
    session = sessions.get(sid)
    if session is None:
        return
    cols, rows = _parse_size(data)
    fcntl.ioctl(
        session.master_fd, termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, cols, 0, 0),
    )


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
    websocket = connections.get(sid)
    if websocket is not None:
        with contextlib.suppress(OSError, RuntimeError):
            await websocket.close(
                code=WEBSOCKET_CLOSE_NORMAL,
                reason=_truncate(reason),
            )
    await _cleanup_session(sid)


async def _cleanup_session(sid: str) -> None:
    """Remove *sid* and kill its child process.  Idempotent."""
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

    _logger.info(f"Session closed on {session.tty_name}")


async def cleanup_all_sessions() -> None:
    for sid in list(sessions):
        await _cleanup_session(sid)


async def close_all_connections() -> None:
    for websocket in list(connections.values()):
        with contextlib.suppress(Exception):
            await websocket.close(
                code=WEBSOCKET_CLOSE_GOING_AWAY,
                reason="server shutdown",
            )
