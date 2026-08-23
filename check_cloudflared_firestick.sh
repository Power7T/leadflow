#!/usr/bin/env bash
set -euo pipefail

# Watchdog for Firestick cloudflared tunnel liveness
# Checks if cloudflared is running on Firestick; restarts if missing.

FS_IP=$(cat /Users/chandan/leadflow/.firestick_ip 2>/dev/null || echo "192.168.8.246:5555")

# Quick ADB check
ADB_STATUS=$(/opt/homebrew/bin/adb.orig -s "$FS_IP" shell "run-as com.termux sh -c 'ps -ef | grep cloudflared | grep -v grep'" 2>/dev/null || true)

if [ -z "$ADB_STATUS" ]; then
    echo "[$(date)] cloudflared not running on Firestick ($FS_IP). Triggering restart..."
    /opt/homebrew/bin/adb.orig -s "$FS_IP" shell "run-as com.termux sh -c 'nohup cloudflared tunnel run leadflow > /dev/null 2>&1 &'" || true
else
    echo "[$(date)] cloudflared healthy on Firestick ($FS_IP)."
fi
