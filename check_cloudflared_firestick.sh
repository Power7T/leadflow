#!/usr/bin/env bash
# Watchdog for Firestick cloudflared tunnel liveness
# Checks if cloudflared is running on Firestick; restarts if missing.

FS_IP=$(cat /Users/chandan/leadflow/.firestick_ip 2>/dev/null || echo "192.168.8.246:5555")

# Quick ADB check
ADB_STATUS=$(/opt/homebrew/bin/adb.orig -s "$FS_IP" shell "run-as com.termux sh -c 'ps -ef | grep cloudflared | grep -v grep'" 2>/dev/null)

if [ -z "$ADB_STATUS" ]; then
    echo "[$(date)] cloudflared not running on Firestick ($FS_IP). Restarting..."
    /opt/homebrew/bin/adb.orig -s "$FS_IP" shell "run-as com.termux sh -c 'nohup /data/data/com.termux/files/usr/bin/cloudflared tunnel run > /dev/null 2>&1 &'" 2>/dev/null
    echo "[$(date)] Cloudflared restart triggered."
else
    echo "[$(date)] cloudflared is active on Firestick."
fi
