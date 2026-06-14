#!/bin/bash
cd "$(dirname "$0")"

# Trap exit to kill all child processes
trap 'kill $(jobs -p) 2>/dev/null; pkill -P $$ 2>/dev/null; exit' INT TERM EXIT

# Clear previous tunnel URLs
echo "" > /tmp/leadflow-tunnel-url.txt
echo "" > /tmp/leadflow-demo-tunnel-url.txt

echo "Starting LeadFlow..."
python3.12 server.py &
SERVER_PID=$!

echo "Starting Demo server..."
python3.12 demo_server.py &
DEMO_PID=$!

# Wait for main app
until curl -s http://127.0.0.1:8765 > /dev/null 2>&1; do sleep 0.3; done

open "http://127.0.0.1:8765"
echo "LeadFlow running at http://127.0.0.1:8765"
echo "Demo server running at http://127.0.0.1:8766"
echo "Starting Cloudflare tunnels..."

# Tunnel 1 — main LeadFlow app
cloudflared tunnel --url http://127.0.0.1:8765 2>&1 | while read line; do
  if echo "$line" | grep -q "trycloudflare.com"; then
    URL=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com')
    if [ -n "$URL" ]; then
      echo "$URL" > /tmp/leadflow-tunnel-url.txt
      echo "  MAIN APP:   $URL"
    fi
  fi
done &

# Tunnel 2 — demo sites only (clean URL for prospects, port 8766)
cloudflared tunnel --url http://127.0.0.1:8766 2>&1 | while read line; do
  if echo "$line" | grep -q "trycloudflare.com"; then
    URL=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com')
    if [ -n "$URL" ]; then
      echo "$URL" > /tmp/leadflow-demo-tunnel-url.txt
      echo "  DEMO SITES: $URL"
    fi
  fi
done &

wait $SERVER_PID
