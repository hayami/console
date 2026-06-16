from __future__ import annotations

import contextlib
import os

from . import config


def execshell(slave_fd: int, execfail_w: int) -> None:
    """Child process: set up controlling terminal and exec the shell.

    Never returns on success (execve replaces the process).
    On failure, writes to *execfail_w* and calls ``os._exit(127)``.
    """
    try:
        os.login_tty(slave_fd)

        # Close all inherited fds (other sessions' master_fds,
        # listening sockets, etc.) except execfail_w.
        max_fd = os.sysconf("SC_OPEN_MAX")
        os.closerange(3, execfail_w)
        os.closerange(execfail_w + 1, max_fd)

        os.umask(config.UMASK)
        os.chdir(config.CWD)
        os.execve(config.SHELL, config.ARGS, config.ENV)
    except OSError:
        with contextlib.suppress(OSError):
            os.write(execfail_w, b"@")
    with contextlib.suppress(OSError):
        os.close(execfail_w)
    os._exit(127)
