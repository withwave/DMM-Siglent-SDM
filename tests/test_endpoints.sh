#!/bin/bash
# Smoke test for the web app's HTTP API.
# Launches uvicorn against the real DMM, hits every endpoint, asserts
# the shape, and tears down. Run from the project root:
#
#   ./tests/test_endpoints.sh
#
# Exits non-zero on the first failed assertion.
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PORT="${PORT:-8765}"   # different from default 8000 so we don't fight a
                       # running instance.
URL="http://127.0.0.1:${PORT}"
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

# Activate venv if present, otherwise rely on PATH.
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$1"; printf "\n--- backend log ---\n"; cat "$LOG"; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing dep: $1"; }

need curl
need python3

# Sanity-check the DMM is reachable before we burn time on uvicorn. If
# the SCPI socket is refusing connections (common after an ungraceful
# disconnect — the device needs a power cycle), bail with a clear
# message instead of letting assertions fail on empty IDN later.
DMM_HOST=$(python3 -c "
import configparser; c = configparser.ConfigParser()
c.read('multimeter.ini'); print(c['hw_settings']['HOST'])
")
DMM_PORT=$(python3 -c "
import configparser; c = configparser.ConfigParser()
c.read('multimeter.ini'); print(c['hw_settings']['PORT'])
")
echo "[test] checking DMM at ${DMM_HOST}:${DMM_PORT}"
if ! python3 -c "
import socket
s = socket.create_connection(('${DMM_HOST}', ${DMM_PORT}), timeout=3)
s.settimeout(2); s.sendall(b'*IDN?\n'); idn = s.recv(256).decode().strip()
s.close()
print(' ', idn)
assert 'Siglent' in idn
" 2>&1; then
  echo "[test] DMM not responding on ${DMM_HOST}:${DMM_PORT}"
  echo "[test] (cycle the DMM power and try again - see README)"
  exit 2
fi

echo "[test] starting uvicorn on :${PORT}"
python3 -m uvicorn web_app:app --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
UVI=$!
cleanup() { kill -TERM "$UVI" 2>/dev/null || true; wait "$UVI" 2>/dev/null || true; }
trap 'cleanup; rm -f "$LOG"' EXIT

# Wait for the port to accept connections (up to 15 s).
for _ in $(seq 1 150); do
  if curl -sf -m 1 "$URL/api/info" >/dev/null 2>&1; then break; fi
  sleep 0.1
done

# Wait for the polling task to populate last_reading (200 OK on
# /api/reading). The endpoint returns 503 until the first tick.
for _ in $(seq 1 60); do
  if curl -sf -m 1 "$URL/api/reading" >/dev/null 2>&1; then break; fi
  sleep 0.1
done

echo "[test] running assertions"

# /api/info: must include IDN and current_mode
body=$(curl -sf "$URL/api/info")
echo "$body" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
assert 'Siglent' in d['idn'], f'IDN missing Siglent: {d[\"idn\"]!r}'
assert d['current_mode'] in d['modes'], 'current_mode not in modes'
print('  IDN:', d['idn'])
print('  mode:', d['current_mode'], 'range:', d['current_range'])
" && ok "/api/info OK"

# /api/reading: JSON with numeric value
curl -sf "$URL/api/reading" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
assert isinstance(d.get('value'), (int, float)), f'value not numeric: {d}'
assert d['mode'] == 'DCI', f'expected DCI default, got {d[\"mode\"]}'
print('  value:', d['value'], d['prefix'])
" && ok "/api/reading OK"

# /api/reading.txt: human-readable line
txt=$(curl -sf "$URL/api/reading.txt")
case "$txt" in
  *DCI*) ok "/api/reading.txt: ${txt}" ;;
  *)     fail "/api/reading.txt unexpected: ${txt}" ;;
esac

# tools/ma: should exit 0 and print the same shape
out=$("./tools/ma" 2>&1)
echo "$out" | grep -qE "DCI"  && ok "tools/ma: $out" || fail "tools/ma bad output: $out"

# Mode switch round-trip: DCI -> VDC -> DCI
curl -sfX POST "$URL/api/mode/VDC" | grep -q '"mode":"VDC"' && ok "POST /api/mode/VDC" || fail "VDC switch failed"
# Poll until the new mode shows up in /api/reading (set_mode clears
# last_reading; we wait up to 3 s for the next tick to fill it back in).
for _ in $(seq 1 30); do
  if curl -sf "$URL/api/reading" 2>/dev/null | grep -q '"mode":"VDC"'; then break; fi
  sleep 0.1
done
curl -sf "$URL/api/reading" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
assert d['mode'] == 'VDC', f'mode did not stick: {d[\"mode\"]}'
print('  switched mode:', d['mode'])
" && ok "reading reflects VDC" || fail "VDC not reflected"
curl -sfX POST "$URL/api/mode/DCI" >/dev/null && ok "switched back to DCI"

# reset-minmax
curl -sfX POST "$URL/api/reset-minmax" | grep -q '"ok":true' && ok "POST /api/reset-minmax" || fail "reset-minmax failed"

# Static assets that the PWA needs
for p in /static/style.css /static/app.js /manifest.json /sw.js /static/icon.svg; do
  curl -sf -o /dev/null -w "%{http_code}" "$URL$p" | grep -q "^200$" && ok "GET $p -> 200" || fail "GET $p not 200"
done

echo ""
echo "[test] all assertions passed"
