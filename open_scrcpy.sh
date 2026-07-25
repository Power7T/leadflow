#!/bin/bash
echo "Starting scrcpy for Firestick (192.168.0.113)..."
scrcpy -s $(cat /Users/chandan/leadflow/.firestick_ip) --window-title "Firestick Remote" &
