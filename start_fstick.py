import os
import subprocess
from pathlib import Path

# Load IP dynamically
ip_file = Path(os.path.expanduser("~/.vivo_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.1.7:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

subprocess.run(f"adb -s {device_ip} shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"cd /data/data/com.termux/files/home/leadflow && /data/data/com.termux/files/usr/bin/python generate_ig_drafts.py > /data/data/com.termux/files/home/leadflow/generate_ig_drafts.log 2>&1 &\"'", shell=True)

