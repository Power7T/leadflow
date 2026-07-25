#!/bin/bash
cd "$(dirname "$0")"

# PID LOCK: Prevent multiple daemon instances
PIDFILE=/tmp/leadflow_daemon.pid
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "[run_daemon] Daemon already running (PID $(cat "$PIDFILE")). Exiting."
  exit 1
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "" > /tmp/leadflow-tunnel-url.txt
echo "" > /tmp/leadflow-demo-tunnel-url.txt

python3.12 -u server.py > /tmp/leadflow_server.log 2>&1 &
SERVER_PID=$!
python3.12 -u demo_server.py > /tmp/leadflow_demo.log 2>&1 &
DEMO_PID=$!
python3.12 -u telegram_bot.py > /tmp/leadflow_telegram.log 2>&1 &
TELEGRAM_PID=$!

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

trap 'kill $SERVER_PID $DEMO_PID $TELEGRAM_PID $TUNNEL_PID1 $TUNNEL_PID2 $(jobs -p) 2>/dev/null; exit' TERM INT EXIT

# Monitor child processes. If either server.py, demo_server.py, or telegram_bot.py exits, terminate the daemon.
while kill -0 $SERVER_PID 2>/dev/null && kill -0 $DEMO_PID 2>/dev/null && kill -0 $TELEGRAM_PID 2>/dev/null; do
  sleep 2
done

