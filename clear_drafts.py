import os
import subprocess
import base64
from pathlib import Path

# Load IP dynamically
ip_file = Path(os.path.expanduser("~/.vivo_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.1.7:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

script = """
import sqlite3
conn = sqlite3.connect("/data/data/com.termux/files/home/leadflow/leadflow.db")
conn.execute("UPDATE outreach SET draft = NULL WHERE channel = 'instagram' AND status = 'draft'")
conn.commit()
"""
b64 = base64.b64encode(script.encode()).decode()
subprocess.run(['adb', '-s', device_ip, 'shell', f"run-as com.termux /data/data/com.termux/files/usr/bin/python -c 'import base64; exec(base64.b64decode(\"{b64}\").decode())'"])

