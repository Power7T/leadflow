#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/system/bin
export HOME=/data/data/com.termux/files/home
cd /data/data/com.termux/files/home/leadflow

# Acquire Termux wake lock to prevent CPU sleep
termux-wake-lock 2>/dev/null || true

# Start watchdog in background (it will also restart server if needed)
nohup bash start_watchdog.sh >> watchdog.log 2>&1 &

# Start server in foreground
exec python3 -u server.py >> server_run.log 2>&1
