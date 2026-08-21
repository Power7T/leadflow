#!/data/data/com.termux/files/usr/bin/bash
# Prevent Android from sleeping / freezing background actions
termux-wake-lock

# Give the network and system time to initialize on boot
sleep 30

ADB_BIN="/data/data/com.termux/files/usr/bin/adb"
PYTHON_BIN="/data/data/com.termux/files/home/leadflow/venv/bin/python"
LOG_FILE="/data/data/com.termux/files/home/leadflow/boot_recovery.log"

echo "=== LeadFlow Boot Recovery: $(date) ===" >> "$LOG_FILE"

# Step 1: Discover random wireless debugging port and connect/enable port 5555
CONNECTED=false
for i in {1..15}; do
    echo "Attempt $i: Discovering Wireless Debugging Port..." >> "$LOG_FILE"
    
    # Run helper script to find the active wireless debugging port
    DISCOVERED_TARGET=$($PYTHON_BIN /data/data/com.termux/files/home/leadflow/find_adb_port.py 2>/dev/null)
    
    if [ -n "$DISCOVERED_TARGET" ]; then
        echo "Found Wireless Debugging target at: $DISCOVERED_TARGET" >> "$LOG_FILE"
        
        # Connect to the discovered port
        $ADB_BIN connect "$DISCOVERED_TARGET" >> "$LOG_FILE" 2>&1
        sleep 2
        
        # Switch to permanent port 5555
        echo "Switching ADB to tcpip 5555..." >> "$LOG_FILE"
        $ADB_BIN tcpip 5555 >> "$LOG_FILE" 2>&1
        sleep 3
        
        # Connect to local port 5555
        $ADB_BIN connect localhost:5555 >> "$LOG_FILE" 2>&1
        sleep 2
    fi
    
    # Check if connected on localhost:5555
    DEV_STATUS=$($ADB_BIN devices | grep "localhost:5555" | awk '{print $2}')
    if [ "$DEV_STATUS" = "device" ]; then
        echo "Successfully connected to local ADB on port 5555!" >> "$LOG_FILE"
        CONNECTED=true
        break
    fi
    
    sleep 5
done

if [ "$CONNECTED" = "true" ]; then
    # Enable Funtouch OS setting to allow simulating inputs over ADB (Solution B / Secure input fix)
    $ADB_BIN -s localhost:5555 shell settings put secure vivo_adb_simulate_input 1 2>/dev/null || true
    # Enforce default IME to ADB Keyboard
    $ADB_BIN -s localhost:5555 shell ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null || true
    $ADB_BIN -s localhost:5555 shell ime set com.android.adbkeyboard/.AdbIME 2>/dev/null || true
    # Enable screen stayon
    $ADB_BIN -s localhost:5555 shell svc power stayon true 2>/dev/null || true
    $ADB_BIN -s localhost:5555 shell settings put global stay_on_while_plugged_in 3 2>/dev/null || true
else
    echo "Warning: Could not connect to local ADB. Dynamic Discovery failed. Trying fallback..." >> "$LOG_FILE"
    # Fallback to direct localhost:5555 connection if already enabled
    $ADB_BIN connect localhost:5555 >> "$LOG_FILE" 2>&1
fi

# Kill any existing server.py process to prevent duplicate instances
pkill -f server.py 2>/dev/null || true
sleep 2

# Start primary LeadFlow FastAPI server and scheduler
cd /data/data/com.termux/files/home/leadflow
export LEADFLOW_DEVICE_ROLE=primary
$PYTHON_BIN server.py >> server_run.log 2>&1 &
echo "Leadflow server started on primary node." >> "$LOG_FILE"
