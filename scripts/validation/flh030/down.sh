#!/bin/sh
# Stops the FLH-030 listeners started by up.sh (fixed ports only).
for port in 18930 18931 18932 5330; do
  pids=$(lsof -ti tcp:$port -sTCP:LISTEN 2>/dev/null || true)
  [ -n "$pids" ] && kill $pids
done
echo stopped
