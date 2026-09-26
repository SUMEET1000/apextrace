#!/usr/bin/env bash
# Cold-path probe for the static site. Run it after the web service has been
# idle for 20 minutes or more, so the API call pays the real wake-up.
#
#   scripts/probe_static.sh <site-url> <api-base>
#
# <api-base> is the site URL itself while /api is passed through by the static
# site's rewrite, or https://apextrace.onrender.com if the fallback (direct
# calls with CORS) is in use; then the Origin check below also runs.
#
# Output goes to a real file, never /dev/null: Git Bash's curl intermittently
# fails writing there with "(23) client returned ERROR on write", which looks
# like a server failure and is not one (20 Sept 2026).
set -u
SITE=${1:?site url}; API=${2:?api base}
OUT=$(mktemp -d); FAIL=0
# A Windows path under Git Bash, so curl can write there even with MSYS_NO_PATHCONV=1 set.
command -v cygpath >/dev/null && OUT=$(cygpath -m "$OUT")

hit() {   # name, url, max seconds, [extra curl args...]
  local name=$1 url=$2 max=$3; shift 3
  local line
  line=$(curl -sS -f -o "$OUT/$name" -D "$OUT/$name.h" -w '%{http_code} %{time_total}' --max-time 120 "$@" "$url") \
    || { echo "FAIL $name: $url -> ${line:-no response}"; FAIL=1; return; }
  local secs=${line#* }
  if awk "BEGIN{exit !($secs > $max)}"; then echo "FAIL $name: $line s, limit $max s"; FAIL=1
  else echo "PASS $name: $line s"; fi
}

hit shell "$SITE/" 2
hit deep_route "$SITE/race-arc?year=2024&round=1&session=R" 2
grep -q 'id="root"' "$OUT/deep_route" 2>/dev/null || { echo "FAIL deep_route: not the app shell"; FAIL=1; }
hit manifest "$API/api/manifest" 90
# The rewrite has to carry the query string; nothing in Render's docs says it does.
hit home "$API/api/home?slug=2024/12_Q" 30
grep -q '"slug":"2024/12_Q"' "$OUT/home" 2>/dev/null || { echo "FAIL home: answer is not for 2024/12_Q"; FAIL=1; }

if [ "$API" != "$SITE" ]; then
  hit cors "$API/api/manifest" 30 -H "Origin: $SITE"
  grep -qi "^access-control-allow-origin: $SITE" "$OUT/cors.h" 2>/dev/null \
    || { echo "FAIL cors: no Access-Control-Allow-Origin for $SITE"; FAIL=1; }
fi

rm -rf "$OUT"
[ "$FAIL" = 0 ] && echo "probe passed" || echo "probe failed"
exit "$FAIL"
