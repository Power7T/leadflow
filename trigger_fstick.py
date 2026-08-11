import os
import subprocess
from pathlib import Path

# Load Firestick IP dynamically
ip_file = Path(os.path.expanduser("~/.firestick_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.8.246:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

subprocess.run(f"adb -s {device_ip} shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"cd /data/data/com.termux/files/home/leadflow && git pull && python generate_ig_drafts.py > /tmp/ig_drafts.log 2>&1 &\"'", shell=True)

