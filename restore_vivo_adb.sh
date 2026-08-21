#!/data/data/com.termux/files/usr/bin/sh
# Firestick-based Auto-Recovery Daemon for Vivo Phone Wireless ADB
# Runs in background on the Firestick to enable TCP mode on Vivo phone on boot

export PATH=/data/data/com.termux/files/usr/bin:$PATH
export HOME=/data/data/com.termux/files/home
export TMPDIR=/data/data/com.termux/files/home

ADB_BIN="/data/data/com.termux/files/usr/bin/adb"

echo "[restore_vivo_adb] Starting USB monitor on Firestick..."

while true; do
    # Find any USB connected device (excludes IP addresses containing colons)
    USB_DEV=$($ADB_BIN devices | grep -v "List" | grep -v ":" | grep -w "device" | awk '{print $1}' | head -n 1)
    
    if [ -n "$USB_DEV" ]; then
        echo "[restore_vivo_adb] Found USB device: $USB_DEV. Enabling TCP port 5555..."
        $ADB_BIN -s "$USB_DEV" tcpip 5555 >/dev/null 2>&1
        # Cooldown to prevent spamming
        sleep 60
    fi
    sleep 10
done
