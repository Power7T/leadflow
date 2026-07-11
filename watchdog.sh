#!/data/data/com.termux/files/usr/bin/bash
# Watchdog: restart server.py if port 8765 is not responding
LOGFILE="/data/data/com.termux/files/home/leadflow/watchdog.log"
SERVERLOG="/data/data/com.termux/files/home/leadflow/server_run.log"
LEADFLOW="/data/data/com.termux/files/home/leadflow"
PYTHON="/data/data/com.termux/files/usr/bin/python3"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin"
export HOME="/data/data/com.termux/files/home"

check_port() {
    # Try connecting to port 8765; exit 0 if open, nonzero if closed
    (echo >/dev/tcp/127.0.0.1/8765) 2>/dev/null
}

if check_port; then
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] server.py not responding on :8765 — restarting" >> "$LOGFILE"

# Kill any stale python3 server.py process
pkill -f "python3.*server.py" 2>/dev/null
sleep 2

# Start server in background
cd "$LEADFLOW"
nohup "$PYTHON" -u server.py >> "$SERVERLOG" 2>&1 &
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launched server.py (PID $!)" >> "$LOGFILE"
