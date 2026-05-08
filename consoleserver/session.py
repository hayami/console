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

from consoleserver import config
from consoleserver import execshell
from consoleserver import globalvars as g


_logger = logging.getLogger("uvicorn")


# ---------------------------------------------------------------------------
# PTY session management
# ---------------------------------------------------------------------------
@dataclass
class PtySession:
    pid: int
    master_fd: int
    tty_name: str
    reaped: bool = False
    keyin_event: asyncio.Event | None = None
    keyin_task: asyncio.Task[None] | None = None


sessions: dict[str, PtySession] = {}
timeout_task: asyncio.Task[None] | None = None


def open_pty_session(cols: int, rows: int) -> tuple[int, int, str]:
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


async def handle_shell_exit(sid: str) -> None:
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
        await g.sio.emit("close-connection", reason, to=sid)
    await cleanup_session(sid)


async def cleanup_session(sid: str) -> None:
    """Remove *sid* and kill its child process.  Idempotent."""
    global timeout_task
    session = sessions.pop(sid, None)
    if session is None:
        return
    if session.keyin_event is not None:
        session.keyin_event = None
    if session.keyin_task is not None:
        session.keyin_task.cancel()
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

    if config.NO_SESSION_TIMEOUT > 0 and not sessions:
        if timeout_task is None or timeout_task.done():
            timeout_task = loop.create_task(no_session_timeout_handler())

    _logger.info(f"Session closed on {session.tty_name}")


async def keyin_timeout_handler(sid: str) -> None:
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
                await g.sio.emit(
                    "close-connection",
                    f"key input timeout ({config.KEYIN_TIMEOUT}s)",
                    to=sid,
                )
            _logger.info(
                f"Key input timeout ({config.KEYIN_TIMEOUT}s)"
                f" on {session.tty_name}"
            )
            # Prevent cleanup_session from cancelling this task.
            session.keyin_task = None
            await cleanup_session(sid)
            return


async def no_session_timeout_handler() -> None:
    """Shut down the server on no-session timeout."""

    try:
        await asyncio.sleep(config.NO_SESSION_TIMEOUT)
    except asyncio.CancelledError:
        return
    if sessions:
        return
    msg = f"No sessions for {config.NO_SESSION_TIMEOUT}s, shutting down"
    _logger.info(msg)
    assert g.uvicorn_server is not None
    g.uvicorn_server.should_exit = True
