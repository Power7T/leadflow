#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/system/bin
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr

# Prevent sleep
termux-wake-lock

# Wait for network and tmux to initialize
sleep 20

# Kill existing leadflow sessions if any
tmux kill-session -t leadflow_primary 2>/dev/null
tmux kill-session -t leadflow_failover 2>/dev/null

# Start the primary server.py in a dedicated tmux session
tmux new-session -d -s leadflow_primary "cd /data/data/com.termux/files/home/leadflow && python3 -u server.py >> server_run.log 2>&1"
