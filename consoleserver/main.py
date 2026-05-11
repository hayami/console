from __future__ import annotations

import contextlib
import copy
import sys
from typing import Any

import uvicorn

from . import config
from . import server
from . import globalvars as g


def main() -> None:
    if sys.version_info < (3, 12):
        raise SystemExit("ERROR: Python 3.12 or later is required")

    uvicorn_kwargs: dict[str, Any] = {}
    if config.SOCKET:
        uvicorn_kwargs["uds"] = config.SOCKET
    else:
        uvicorn_kwargs["host"] = config.HOST
        uvicorn_kwargs["port"] = config.PORT
    uvicorn_kwargs["timeout_graceful_shutdown"] = 10.0

    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    for i in ("default", "access"):
        f = log_config["formatters"][i]
        f["datefmt"] = "%Y-%m-%dT%H:%M:%S%z"
        f["fmt"] = "%(asctime)s " + f['fmt']
    log_config["loggers"]["uvicorn.access"]["level"] = "WARNING"
    uvicorn_kwargs["log_config"] = log_config

    uvicorn_config = uvicorn.Config(server.app, **uvicorn_kwargs)
    g.uvicorn_server = uvicorn.Server(uvicorn_config)
    with contextlib.suppress(KeyboardInterrupt):
        g.uvicorn_server.run()
