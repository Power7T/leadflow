import os
import subprocess
import base64
from pathlib import Path

# Load Firestick IP dynamically
ip_file = Path(os.path.expanduser("~/.firestick_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.0.113:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

script = """
import os
os.chdir('/data/data/com.termux/files/home/leadflow')
os.system('/data/data/com.termux/files/usr/bin/python sync_engine.py')
"""
b64 = base64.b64encode(script.encode()).decode()
subprocess.run(['adb', '-s', device_ip, 'shell', f"run-as com.termux /data/data/com.termux/files/usr/bin/python -c 'import base64; exec(base64.b64decode(\"{b64}\").decode())'"])

