#!/bin/sh
set -e

comma=''
printf '{'
find docroot -type f ! -name '*.gz' -printf '%P\n' | sort -u \
| while read file; do
    filepath=docroot/$file
    etag=$(openssl dgst -sha256 < $filepath | sed 's/^.*[^0-9A-Fa-f]//')
    len=$(wc -c < $filepath)
    if [ -f ${filepath}.gz ]; then
        gzlen=$(wc -c < ${filepath}.gz)
    else
        gzlen=0
    fi
    case "$filepath" in
    *.css)   type='text/css; charset=utf-8'		;;
    *.html)  type='text/html; charset=utf-8'		;;
    *.js)    type='text/javascript; charset=utf-8'	;;
    *.ttf)   continue					;;
    *.woff2) type='font/woff2'				;;
    *)       echo "ERROR: unknown suffix for $filepath" 1>&2
             exit 1
             ;;
    esac
    printf '%s\n' "$comma"
    printf '  "%s": {\n' "$file"
    printf '    "etag": "\\"%s\\"",\n' "$etag"
    printf '    "content-length": %d,\n' "$len"
    printf '    "content-type": "%s"' "$type"
    if [ "$gzlen" -gt 0 ]; then
        printf ',\n'
        printf '    "gzip": {\n'
        printf '      "etag": "\\"gzip-%s\\"",\n' "$etag"
        printf '      "content-length": %d\n' "$gzlen"
        printf '    }'
    fi
    printf '\n  }'
    comma=','
done
printf '\n}\n'

exit 0
