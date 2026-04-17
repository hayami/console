from __future__ import annotations

import collections
import contextlib
import json5
import os
import socket
from typing import Any


CONFIG_FILE = "config.json5"


def _expand_env(obj: Any) -> Any:
    """Expand {VAR} references in all string values using os.environ."""
    if isinstance(obj, str):
        return obj.format_map(_env_dict)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


_config: dict[str, Any] = {}
with contextlib.suppress(FileNotFoundError):
    with open(f"{CONFIG_FILE}") as _f:
        try:
            _config = json5.load(_f)
        except ValueError as e:
            raise SystemExit(f"{CONFIG_FILE}: parse error: {e}")

if not isinstance(_config, dict):
    raise SystemExit(f"{CONFIG_FILE}: root must be an object")

_env_dict = collections.defaultdict(str, os.environ)
_config = _expand_env(_config)

_server_config: dict[str, Any] = _config.get("server", {})
if not isinstance(_server_config, dict):
    raise SystemExit(f"{CONFIG_FILE}: server must be an object")

HOST: str = _server_config.get("host") or "127.0.0.1"
if not isinstance(HOST, str):
    raise SystemExit(f"{CONFIG_FILE}: server.host must be a string")

_port_raw: str = _server_config.get("port") or "9000"
if not isinstance(_port_raw, str):
    raise SystemExit(f"{CONFIG_FILE}: server.port must be a string")
try:
    PORT: int = int(_port_raw)
except ValueError:
    try:
        PORT = socket.getservbyname(_port_raw)
    except OSError:
        raise SystemExit(
            f"{CONFIG_FILE}: server.port: unknown port {_port_raw!r}"
        )

SOCKET: str = _server_config.get("socket") or ""
if not isinstance(SOCKET, str):
    raise SystemExit(f"{CONFIG_FILE}: server.socket must be a string")

_cors_raw = _server_config.get("cors_allowed_origins", "*")
if isinstance(_cors_raw, str):
    CORS_ALLOWED_ORIGINS: str | list[str] = _cors_raw
elif isinstance(_cors_raw, list) and all(isinstance(o, str) for o in _cors_raw):
    CORS_ALLOWED_ORIGINS = _cors_raw
else:
    raise SystemExit(
        f"{CONFIG_FILE}: server.cors_allowed_origins must be a string"
        " or a list of strings"
    )

_keyin_timeout_raw = _server_config.get("keyin_timeout", 0)
try:
    if isinstance(_keyin_timeout_raw, bool):
        raise ValueError
    elif isinstance(_keyin_timeout_raw, int):
        KEYIN_TIMEOUT: int = _keyin_timeout_raw
    elif isinstance(_keyin_timeout_raw, str):
        KEYIN_TIMEOUT: int = int(_keyin_timeout_raw.strip())
    else:
        raise ValueError
    if KEYIN_TIMEOUT < 0:
        raise ValueError
except (TypeError, ValueError):
    raise SystemExit(
        f"{CONFIG_FILE}: server.keyin_timeout must be a non-negative integer"
    )

_shell_config: dict[str, Any] = _config.get("shell", {})
if not isinstance(_shell_config, dict):
    raise SystemExit(f"{CONFIG_FILE}: shell must be an object")

_umask_raw = _shell_config.get("umask", "022")
try:
    if not isinstance(_umask_raw, str):
        raise ValueError
    UMASK: int = int(_umask_raw, 8)
except ValueError:
    raise SystemExit(
        'config.json5: shell.umask must be an octal string (e.g. "022")'
    )

CWD: str = _shell_config.get("cwd") or "."
if not isinstance(CWD, str):
    raise SystemExit(f"{CONFIG_FILE}: shell.cwd must be a string")

SHELL: str = _shell_config.get("path") or ""
if not isinstance(SHELL, str):
    raise SystemExit(f"{CONFIG_FILE}: shell.path must be a string")
if not SHELL:
    raise SystemExit(f"{CONFIG_FILE}: shell.path is required")

ARGS: list[str] = _shell_config.get("args", [])
if not isinstance(ARGS, list) or not all(isinstance(a, str) for a in ARGS):
    raise SystemExit(f"{CONFIG_FILE}: shell.args must be a list of strings")
if not ARGS:
    raise SystemExit(f"{CONFIG_FILE}: shell.args requires at least one element")

ENV: dict[str, str] = _shell_config.get("env", {})
if not isinstance(ENV, dict) or not all(
    isinstance(k, str) and isinstance(v, str) for k, v in ENV.items()
):
    raise SystemExit(f"{CONFIG_FILE}: shell.env must be a mapping of strings")
