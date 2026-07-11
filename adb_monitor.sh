#!/bin/bash
# Self-healing Wireless ADB Daemon for Leadflow
# Runs on Mac to ensure Firestick and Vivo phone stay connected via ADB

# Detect and use the original/raw adb binary to bypass Vivo/routing wrappers
if [ -x "/opt/homebrew/bin/adb.orig" ]; then
    ADB_BIN="/opt/homebrew/bin/adb.orig"
elif [ -x "/usr/local/bin/adb.orig" ]; then
    ADB_BIN="/usr/local/bin/adb.orig"
else
    ADB_BIN="adb"
fi

LOG_FILE="/Users/chandan/leadflow/adb_monitor.log"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log "Starting ADB monitor daemon with ADB_BIN=$ADB_BIN"

# Target devices
# Each entry is "IP:DISPLAY_NAME"
DEVICES=("192.168.1.3:Firestick" "192.168.1.4:VivoPhone")

# Track consecutive failures per device index
consecutive_fails=(0 0)
# Track cooldown ticks remaining per device index (1 tick = 2 minutes)
cooldown_ticks=(0 0)

check_device() {
    local idx=$1
    local entry=${DEVICES[$idx]}
    local ip=${entry%%:*}
    local name=${entry#*:}
    local addr="${ip}:5555"

    # 1. If in cooldown, decrement and skip
    if [ ${cooldown_ticks[$idx]} -gt 0 ]; then
        cooldown_ticks[$idx]=$((cooldown_ticks[$idx] - 1))
        if [ ${cooldown_ticks[$idx]} -eq 0 ]; then
            log "$name ($ip) cooldown expired, will retry next cycle."
        fi
        return 0
    fi

    # 2. Check if device is currently connected and healthy
    # An active healthy device shows as "<ip>:5555\tdevice" (or spaces) in 'adb devices'
    if $ADB_BIN devices | grep -E "^${ip}:5555[[:space:]]+device$" > /dev/null 2>&1; then
        if [ ${consecutive_fails[$idx]} -ne 0 ]; then
            log "$name ($ip) is healthy. Resetting failure counter."
        fi
        consecutive_fails[$idx]=0
        return 0
    fi

    # Device is missing or not in 'device' state
    log "$name ($ip) is offline/missing. (Current fails: ${consecutive_fails[$idx]})"

    # 3. Ping the device to check if it's reachable on local network
    # -c 1: send 1 packet. -t 3: timeout of 3 seconds (macOS ping timeout is -t)
    if ping -c 1 -t 3 "$ip" >/dev/null 2>&1; then
        log "$name ($ip) is pingable. Attempting recovery..."

        # Disconnect and retry connect
        $ADB_BIN disconnect "$addr" >/dev/null 2>&1
        sleep 1
        local connect_output
        connect_output=$($ADB_BIN connect "$addr" 2>&1)
        log "ADB connect output for $name ($ip): $connect_output"
        sleep 2

        # Check if connect brought it back to healthy state
        if $ADB_BIN devices | grep -E "^${ip}:5555[[:space:]]+device$" > /dev/null 2>&1; then
            log "Successfully reconnected to $name ($ip). Applying power overrides..."
            # Apply stay-on overrides
            $ADB_BIN -s "$addr" shell svc power stayon true >/dev/null 2>&1 || true
            $ADB_BIN -s "$addr" shell settings put global stay_on_while_plugged_in 3 >/dev/null 2>&1 || true
            consecutive_fails[$idx]=0
            return 0
        else
            log "Reconnect action was executed, but $name ($ip) is still not healthy."
        fi
    else
        log "$name ($ip) is not reachable on the network via ping."
    fi

    # 4. Handle failure counting and cooldown entry
    consecutive_fails[$idx]=$((consecutive_fails[$idx] + 1))
    if [ ${consecutive_fails[$idx]} -ge 3 ]; then
        log "$name ($ip) has failed 3 consecutive checks. Entering 30-minute cooldown (15 cycles)."
        cooldown_ticks[$idx]=15
        consecutive_fails[$idx]=0  # Reset counter for post-cooldown retry
    fi
}

while true; do
    for i in "${!DEVICES[@]}"; do
        check_device "$i"
    done
    sleep 120
done
