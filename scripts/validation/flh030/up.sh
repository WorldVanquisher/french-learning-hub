#!/bin/sh
# FLH-030 isolated environment. Usage: up.sh WORK_DIR WEB_COPY_DIR
#   WORK_DIR      new temporary directory holding the built server binary
#                 (WORK_DIR/server); databases and logs are written here.
#   WEB_COPY_DIR  temporary copy of web/ with `npm ci` and `npm run build` done.
# Starts: local stub provider :18930, DEV backend :18931 behind Vite :5330
# (StrictMode), PROD backend :18932 serving WEB_COPY_DIR/dist via -web-dir.
# The servers run with WORK_DIR as working directory, so no repository .env is
# read. No paid provider, secret or daily database is used.
set -eu
WORK=$(cd "$1" && pwd)
WEB=$(cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$WORK"
rm -f dev.db dev.db-* prod.db prod.db-*
python3 -B "$HERE/stub.py" 18930 > stub.log 2>&1 &
common="AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=openai OPENAI_API_KEY=sk-fake-local OPENAI_BASE_URL=http://127.0.0.1:18930 OPENAI_MODEL=stub-model"
env $common PORT=18931 DB_PATH="$WORK/dev.db" HTTP_TRUSTED_ORIGINS=http://localhost:5330 "$WORK/server" > dev-server.log 2>&1 &
env $common PORT=18932 DB_PATH="$WORK/prod.db" "$WORK/server" -web-dir "$WEB/dist" > prod-server.log 2>&1 &
(cd "$WEB" && FRENCH_HUB_URL=http://127.0.0.1:18931 npx vite --port 5330 --strictPort > "$WORK/vite.log" 2>&1 &)
sleep 3
echo started
