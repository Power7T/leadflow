#!/bin/bash
cd /Users/chandan/leadflow

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "" > /tmp/leadflow-tunnel-url.txt
echo "" > /tmp/leadflow-demo-tunnel-url.txt

python3.12 server.py > /tmp/leadflow_server.log 2>&1 &
SERVER_PID=$!
python3.12 demo_server.py > /tmp/leadflow_demo.log 2>&1 &
DEMO_PID=$!

function start_tunnel() {
  local port=$1
  local file=$2
  while true; do
    cloudflared tunnel --url http://127.0.0.1:$port 2>&1 | while read line; do
      if echo "$line" | grep -q "trycloudflare.com"; then
        URL=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com')
        if [ -n "$URL" ]; then
          echo "$URL" > $file
        fi
      fi
    done
    sleep 60
  done
}

start_tunnel 8765 /tmp/leadflow-tunnel-url.txt &
TUNNEL_PID1=$!

start_tunnel 8766 /tmp/leadflow-demo-tunnel-url.txt &
TUNNEL_PID2=$!

trap 'kill $SERVER_PID $DEMO_PID $TUNNEL_PID1 $TUNNEL_PID2 $(jobs -p) 2>/dev/null; exit' TERM INT EXIT

wait
