#!/bin/sh
set -eu

mkdir -p /app/state /tmp

cleanup() {
  if [ -n "${LIQ_PID:-}" ]; then
    kill "$LIQ_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

liquidsoap /app/radio.liq &
LIQ_PID=$!

# Give Liquidsoap time to create its local control socket.
i=0
while [ ! -S "${LIQUIDSOAP_SOCKET:-/tmp/louder-liquidsoap.sock}" ] && [ "$i" -lt 30 ]; do
  if ! kill -0 "$LIQ_PID" 2>/dev/null; then
    echo "Liquidsoap exited during startup" >&2
    wait "$LIQ_PID"
    exit 1
  fi
  i=$((i+1))
  sleep 1
done

exec uvicorn app:app --host 0.0.0.0 --port "${CONTROL_API_PORT:-8787}"
