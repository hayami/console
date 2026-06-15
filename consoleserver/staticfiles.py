from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import PurePosixPath

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.responses import Response
from starlette.responses import StreamingResponse

from . import config


_CHUNK_SIZE = 4096


def _read_chunks(fres) -> Iterator[bytes]:
    with fres.open("rb") as fp:
        while True:
            chunk = fp.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def _getres(path: str) -> Response | None:
    if "\\" in path:
        return None

    p = PurePosixPath(path)
    parts = p.parts
    if p.is_absolute() or ".." in parts:
        return None

    if not config.IS_ARCHIVE:
        fpath = config.STATICFILES_PATH.joinpath(*parts)
        if not fpath.is_file():
            return None

        return FileResponse(fpath)
    else:
        fres = config.STATICFILES_RES.joinpath(*parts)
        if not fres.is_file():
            return None

        media_type, _ = mimetypes.guess_type(parts[-1])
        return StreamingResponse(
            _read_chunks(fres),
            media_type=media_type or "application/octet-stream",
        )


def endpoint(request: Request) -> Response:
    path = request.path_params.get("path")
    res = _getres("_index.html" if path is None else f"static/{path}")
    if res is None:
        return Response("Not Found", status_code=404, media_type="text/plain")
    else:
        return res
