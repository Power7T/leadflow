#!/data/data/com.termux/files/usr/bin/bash
# Persistent watchdog loop — runs forever, checks server.py every 5 minutes
LOGFILE="/data/data/com.termux/files/home/leadflow/watchdog.log"
SERVERLOG="/data/data/com.termux/files/home/leadflow/server_run.log"
LEADFLOW="/data/data/com.termux/files/home/leadflow"
PYTHON="/data/data/com.termux/files/usr/bin/python3"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin"
export HOME="/data/data/com.termux/files/home"

check_port() {
    (echo >/dev/tcp/127.0.0.1/8765) 2>/dev/null
}

while true; do
    if ! check_port; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] server.py not responding — restarting" >> "$LOGFILE"
        pkill -f "python3.*server.py" 2>/dev/null
        sleep 3
        cd "$LEADFLOW"
        nohup "$PYTHON" -u server.py >> "$SERVERLOG" 2>&1 &
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launched server.py (PID $!)" >> "$LOGFILE"
        sleep 15
    else
        sleep 300
    fi
done
