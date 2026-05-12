from __future__ import annotations

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.responses import Response

from . import config


def endpoint(request: Request) -> Response:
    reqpath = request.path_params.get("path")
    if reqpath is None:
        reqpath = "_index.html"
    else:
        reqpath = f"static/{reqpath}"

    return FileResponse(f"{config.STATICFILES_DIR}/{reqpath}")
