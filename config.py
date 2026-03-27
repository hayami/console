from __future__ import annotations

import collections
import contextlib
import json5
import os
from typing import Any


_config: dict[str, Any] = {}
with contextlib.suppress(FileNotFoundError):
    with open("config.json") as _f:
        try:
            _config = json5.load(_f)
        except ValueError as e:
            raise SystemExit(f"config.json: parse error: {e}")

if not isinstance(_config, dict):
    raise SystemExit("config.json: root must be an object")

_shell_config: dict[str, Any] = _config.get("shell", {})
if not isinstance(_shell_config, dict):
    raise SystemExit("config.json: shell must be an object")

_umask_raw = _shell_config.get("umask", "022")
try:
    if not isinstance(_umask_raw, str):
        raise ValueError
    UMASK: int = int(_umask_raw, 8)
except ValueError:
    raise SystemExit(
        'config.json: shell.umask must be an octal string (e.g. "022")'
    )

CWD: str = _shell_config.get("cwd") or "."
if not isinstance(CWD, str):
    raise SystemExit("config.json: shell.cwd must be a string")

SHELL: str = _shell_config.get("path") or ""
if not isinstance(SHELL, str):
    raise SystemExit("config.json: shell.path must be a string")
if not SHELL:
    raise SystemExit("config.json: shell.path is required")

ARGS: list[str] = _shell_config.get("args", [])
if not isinstance(ARGS, list) or not all(isinstance(a, str) for a in ARGS):
    raise SystemExit("config.json: shell.args must be a list of strings")
if not ARGS:
    raise SystemExit("config.json: shell.args requires at least one element")

_env_raw: dict[str, Any] = _shell_config.get("env", {})
if not isinstance(_env_raw, dict) or not all(
    isinstance(k, str) and isinstance(v, str) for k, v in _env_raw.items()
):
    raise SystemExit("config.json: shell.env must be a mapping of strings")
_env_dict = collections.defaultdict(str, os.environ)
ENV: dict[str, str] = {
    k: v.format_map(_env_dict) for k, v in _env_raw.items()
}
