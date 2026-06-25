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


_Manifest = dict[str, dict[str, Any]]
_CHUNK_SIZE = 4096
_GZIP_SKIP_SIZE_LIMIT = 1024


@cache
def _load_manifest() -> _Manifest:
    with config.MANIFEST.open("r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    assert type(manifest) is dict

    for k, v in manifest.items():
        assert type(k) is str
        assert type(v) is dict
        assert type(v.get("etag")) is str
        assert type(v.get("content-length")) is int
        assert type(v.get("content-type")) is str
        gzip = v.get("gzip")
        if gzip:
            assert type(gzip) is dict
            assert type(gzip.get("etag")) is str
            assert type(gzip.get("content-length")) is int

    return cast(_Manifest, manifest)


def _parse_accept_encoding(parse_str: str | None) -> dict[str, float]:
    encodings: dict[str, float] = {}

    if parse_str is None:
        return encodings

    for i in parse_str.split(","):
        parts = [j.strip() for j in i.split(";")]
        if not parts or not parts[0]:
            continue

        encode = parts[0].lower()
        params = parts[1:]
        quality = 1.0

        for param in params:
            name, sep, value = param.partition("=")
            if not (name and sep and value):
                continue
            if name.strip().lower() != "q":
                continue
            try:
                quality = float(value.strip())
            except ValueError:
                quality = 0.0
            else:
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0

        encodings[encode] = quality

    return encodings


def _is_gzip_acceptable(request: Request) -> bool:
    encodings = _parse_accept_encoding(request.headers.get("accept-encoding"))

    q = encodings.get("gzip")
    if q is not None:
        return q > 0

    q = encodings.get("*")
    if q is not None:
        return q > 0

    return False


def _decide_gzip(
    request: Request,
    path: str
) -> tuple[bool, bool, Traversable] | None:
    if "\\" in path:
        return None

    p = PurePosixPath(path)
    path_parts = p.parts
    if p.is_absolute() or ".." in path_parts:
        return None
    gzip_parts = (*path_parts[:-1], path_parts[-1] + ".gz")
    path_target = config.STATICFILES.joinpath(*path_parts)
    gzip_target = config.STATICFILES.joinpath(*gzip_parts)

    entry = _load_manifest().get(path)
    if entry is None:
        return None

    gzip = entry.get("gzip")
    is_gzippable = (
        isinstance(gzip, dict)
        and entry["content-length"] > _GZIP_SKIP_SIZE_LIMIT
        and gzip_target.is_file()
    )
    if is_gzippable and _is_gzip_acceptable(request):
        return (True, is_gzippable, gzip_target)
    else:
        if not path_target.is_file():
            return None
        return (False, is_gzippable, path_target)


def _get_headers(
    use_gzip: bool,
    is_gzippable: bool,
    entry: dict[str, Any]
) -> dict[str, str]:
    headers = {
        # 'Cache-Control: no-cache' lets the browser store the response,
        # but requires revalidation before reuse. With ETag, this enables
        # If-None-Match and 304 Not Modified when the content is unchanged.
        "cache-control": "no-cache",
        "content-type": entry["content-type"],
    }

    if is_gzippable:
        headers["vary"] = "Accept-Encoding"

    if use_gzip:
        gzip = entry.get("gzip")
        assert isinstance(gzip, dict)
        headers["etag"] = gzip["etag"]
        headers["content-length"] = str(gzip["content-length"])
        headers["content-encoding"] = "gzip"
    else:
        headers["etag"] = entry["etag"]
        headers["content-length"] = str(entry["content-length"])

    return headers


def _check_not_modified(request: Request, etag: str) -> bool:

    # TODO XXX weak comparison を実装すること

    if request.method not in ("GET", "HEAD"):
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
    ret = _decide_gzip(request, path)
    if ret:
        use_gzip, is_gzippable, target = ret
    else:
        return None

    entry = _load_manifest().get(path)
    if entry is None:
        return None

    headers = _get_headers(use_gzip, is_gzippable, entry)

    not_modified = _check_not_modified(request, headers["etag"])
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
