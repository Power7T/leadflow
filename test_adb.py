import subprocess
import base64
import os
from pathlib import Path

# Load Vivo phone IP dynamically
ip_file = Path(os.path.expanduser("~/.vivo_ip"))
device_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.8.157:5555"

text = "test ' & < > () | * ? ! $ test"
# Strip newlines
text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
b64 = base64.b64encode(text.encode('utf-8')).decode('utf-8')
cmd = f"adb -s {device_ip} shell \"input text \\\"$(echo {b64} | base64 -d | sed 's/ /%s/g')\\\"\""
print(f"Executing: {cmd}")
subprocess.run(cmd, shell=True)

