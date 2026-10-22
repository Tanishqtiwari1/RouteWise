#!/bin/bash
# Double-click to start RouteWise, then open http://localhost:5180 in the browser.
cd "$(dirname "$0")"
lsof -tiTCP:8010 -sTCP:LISTEN >/dev/null || (cd backend && .venv/bin/uvicorn app.main:app --port 8010 > /tmp/routewise-api.log 2>&1 &)
lsof -tiTCP:5180 -sTCP:LISTEN >/dev/null || (cd frontend && npx vite --port 5180 --strictPort > /tmp/routewise-web.log 2>&1 &)
for i in $(seq 1 40); do curl -sf http://localhost:5180 >/dev/null && curl -sf http://localhost:8010/api/v1/health >/dev/null && break; sleep 0.5; done
open http://localhost:5180
echo "RouteWise is running at http://localhost:5180 — keep this window open. Press Ctrl+C or close it to stop."
trap 'kill $(lsof -tiTCP:8010 -sTCP:LISTEN) $(lsof -tiTCP:5180 -sTCP:LISTEN) 2>/dev/null' EXIT
while true; do sleep 3600; done
