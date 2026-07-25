import os
import subprocess
import base64
from pathlib import Path

# Load Firestick IP dynamically
ip_file = Path(os.path.expanduser("~/.firestick_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.0.113:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

python_script = """
import sqlite3
conn = sqlite3.connect("/data/data/com.termux/files/home/leadflow/leadflow.db")
print(conn.execute("SELECT COUNT(*) FROM outreach WHERE channel='instagram' AND status='draft'").fetchall())
"""
b64 = base64.b64encode(python_script.encode()).decode()
subprocess.run(['adb', '-s', device_ip, 'shell', f"run-as com.termux /data/data/com.termux/files/usr/bin/python -c 'import base64; open(\"/data/data/com.termux/files/home/leadflow/chk.py\", \"w\").write(base64.b64decode(\"{b64}\").decode())'"])
subprocess.run(['adb', '-s', device_ip, 'shell', 'run-as', 'com.termux', '/data/data/com.termux/files/usr/bin/python', '/data/data/com.termux/files/home/leadflow/chk.py'])

