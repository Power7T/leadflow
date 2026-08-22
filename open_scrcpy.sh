#!/bin/bash
echo "Starting scrcpy for Firestick (192.168.8.246)..."
scrcpy -s $(cat /Users/chandan/leadflow/.firestick_ip) --window-title "Firestick Remote" &
