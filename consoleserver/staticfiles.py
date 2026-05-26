from __future__ import annotations

from importlib import resources
import mimetypes
import pathlib

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.responses import Response

from . import config


def _getres(path: str) -> Response | None:
    if "\\" in path:
        return None

    p = pathlib.PurePosixPath(path)
    parts = p.parts
    if p.is_absolute() or ".." in parts:
        return None

    if not config.IS_ARCHIVE:
        fpath = config.STATICFILES_DIR.joinpath(*parts)
        if not fpath.is_file():
            return None

        return FileResponse(fpath)
    else:
        fres = resources.files(__package__).joinpath("staticfiles", *parts)
        if not fres.is_file():
            return None

        media_type, _ = mimetypes.guess_type(parts[-1])
        return Response(
            fres.read_bytes(),
            media_type=media_type or "application/octet-stream",
        )


def endpoint(request: Request) -> Response:
    path = request.path_params.get("path")
    res = _getres("_index.html" if path is None else f"static/{path}")
    if res is None:
        return Response("Not Found", status_code=404, media_type="text/plain")
    else:
        return res
