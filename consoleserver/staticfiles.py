from __future__ import annotations

import json
from collections.abc import Iterator
from functools import cache
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath
from typing import Any, cast

from starlette.requests import Request
from starlette.responses import Response
from starlette.responses import StreamingResponse

from . import config


_CHUNK_SIZE = 4096
_Manifest = dict[str, dict[str, Any]]


@cache
def _load_manifest() -> _Manifest:
    with config.MANIFEST.open("r", encoding="utf-8") as fp:
        return cast(_Manifest, json.load(fp))


def _get_manifest_headers(path: str) -> dict[str, str] | None:
    entry = _load_manifest().get(path)
    if entry is None:
        return None

    etag = entry.get("etag")
    assert isinstance(etag, str)

    content_length = entry.get("content-length")
    assert isinstance(content_length, int)

    content_type = entry.get("content-type")
    assert isinstance(content_type, str)

    return {
        # 'Cache-Control: no-cache' lets the browser store the response,
        # but requires revalidation before reuse. With ETag, this enables
        # If-None-Match and 304 Not Modified when the content is unchanged.
        "etag": etag,
        "cache-control": "no-cache",
        "content-length": str(content_length),
        "content-type": content_type,
    }


def _check_not_modified(request: Request, headers: dict[str, str]) -> bool:
    if request.method not in ("GET", "HEAD"):
        return False

    etag = headers.get("etag")
    if etag is None:
        return False

    values = request.headers.get("if-none-match")
    if values is None:
        return False

    match_list = [i.strip() for i in values.split(",")]
    if etag in match_list:
        return True

    return False


def _read_chunks(file: Traversable) -> Iterator[bytes]:
    with file.open("rb") as fp:
        while True:
            chunk = fp.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def _get_response(request: Request, path: str) -> Response | None:
    if "\\" in path:
        return None

    p = PurePosixPath(path)
    parts = p.parts
    if p.is_absolute() or ".." in parts:
        return None

    target = config.STATICFILES.joinpath(*parts)
    if not target.is_file():
        return None

    headers = _get_manifest_headers(path)
    if headers is None:
        return None

    not_modified = _check_not_modified(request, headers)
    if not_modified:
        not_modified_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() != "content-length"
        }
        return Response(status_code=304, headers=not_modified_headers)
    else:
        return StreamingResponse(_read_chunks(target), headers=headers)


def endpoint(request: Request) -> Response:
    path = request.path_params.get("path")
    path = "_index.html" if path is None else f"static/{path}"
    response = _get_response(request, path)
    if response is not None:
        return response
    else:
        return Response("Not Found", status_code=404, media_type="text/plain")
