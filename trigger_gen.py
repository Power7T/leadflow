import os
import sqlite3
import subprocess
import base64
from pathlib import Path

# Load Firestick IP dynamically
ip_file = Path(os.path.expanduser("~/.firestick_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.0.113:5555"

# Connect dynamically before running commands
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

# Wipe the drafts on Firestick DB first
wipe_script = """
import sqlite3
conn = sqlite3.connect("/data/data/com.termux/files/home/leadflow/leadflow.db")
conn.execute("DELETE FROM outreach WHERE channel = 'instagram' AND status = 'draft'")
conn.commit()
print("Wiped drafts!")
"""
b64_wipe = base64.b64encode(wipe_script.encode()).decode()
subprocess.run(['adb', '-s', device_ip, 'shell', f"run-as com.termux /data/data/com.termux/files/usr/bin/python -c 'import base64; exec(base64.b64decode(\"{b64_wipe}\").decode())'"])

# Trigger generation on Firestick
gen_script = """
import os
os.chdir('/data/data/com.termux/files/home/leadflow')
os.system('/data/data/com.termux/files/usr/bin/python generate_ig_drafts.py')
"""
b64_gen = base64.b64encode(gen_script.encode()).decode()
subprocess.run(['adb', '-s', device_ip, 'shell', f"run-as com.termux /data/data/com.termux/files/usr/bin/python -c 'import base64; exec(base64.b64decode(\"{b64_gen}\").decode())'"])

