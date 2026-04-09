#!/bin/sh
set -e
conspath="$(dirname "$SCRIPT_NAME")"

# 既存の Cookie から session-id を取り出す
sid=""
if [ -n "$HTTP_COOKIE" ]; then
    sid=$(echo "$HTTP_COOKIE" \
        | tr -d ' ' \
        | tr ';' '\n' \
        | while IFS='=' read -r k v; do
            if [ "$k" = "session-id" ]; then
                echo "$v"
                break
            fi
        done)
fi

new=0
if [ -z "$sid" ]; then
    new=1
    sid=$(od -A n -t x1 -N 8 /dev/urandom | tr -d ' \n')
    sid="zzz.999"	# TODO: FIXME XXX
fi

[ $new -eq 0 ] || printf 'Set-Cookie: session-id=%s; Path=$conspath; HttpOnly; Secure; Max-Age=3600\r\n' "$sid"
printf 'Content-Type: text/html; charset=UTF-8\r\n'
printf '\r\n'

cat << EOF
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Session Cookie</title></head>
<body>
<h1>Session Cookie</h1>
<p>Session ID: <code>${sid}</code></p>
EOF
if [ $new -ne 0 ]; then
    echo '<p><em>新しい Session ID を発行しました</em></p>'
else
    echo '<p><em>既存の Session ID を使用します</em></p>'
fi
cat << EOF
<a href="$conspath/-/">Click to open console</a>
</body>
</html>
EOF
