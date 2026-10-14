#!/bin/sh
set -e
export LC_ALL=C

top=${1:-"docroot"}

find $top -type f ! -name '*.gz' -print | sort -u | while read f; do
    etag=$(openssl dgst -sha256 < "$f" | sed 's/^.*[^0-9A-Fa-f]//')
    len=$(wc -c < "$f")
    gzlen=0
    [ ! -f "$f.gz" ] || gzlen=$(wc -c < "$f.gz")
    case "$f" in
    *.css)   type='text/css; charset=utf-8'		;;
    *.html)  type='text/html; charset=utf-8'		;;
    *.js)    type='text/javascript; charset=utf-8'	;;
    *.woff2) type='font/woff2'				;;
    *)       type='ERROR'
             echo "ERROR: unknown suffix: $f" 1>&2	;;
    esac
    printf '%s\t%s\t%s\t%s\t%s\n' "$etag" "$len" "$gzlen" "$type" "${f#$top/}"
done | python3 -c 'import json; import sys
ret = 0
result = {}
records = [line.rstrip("\n").split("\t") for line in sys.stdin]

for etag, len, gzlen, type, path in records:
    len = int(len)
    gzlen = int(gzlen)

    if type == "ERROR":
        ret = 1
        continue

    result[path] = {
        "etag": f"\"{etag}\"",
        "content-length": len,
        "content-type": f"{type}",
    }
    if gzlen:
        result[path]["gzip"] = {
            "etag": f"\"gzip-{etag}\"",
            "content-length": gzlen,
        }

print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
exit(ret)'
