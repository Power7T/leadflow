import os
import shutil
import subprocess
from pathlib import Path

# Auto-resolve device IPs from hardware MAC addresses first
try:
    import sys
    sys.path.append("/Users/chandan/leadflow")
    import resolve_devices
    resolve_devices.resolve()
except Exception as e:
    print(f"Could not auto-resolve device IPs: {e}")

# Load Vivo Phone IP
ip_file = Path(os.path.expanduser("~/.vivo_ip"))
phone_ip = ip_file.read_text().strip() if ip_file.exists() else "192.168.8.157:5555"

# Sync .vivo_ip to project directory so it gets pushed to Firestick
if ip_file.exists():
    try:
        shutil.copy(str(ip_file), "/Users/chandan/leadflow/.vivo_ip")
    except Exception as e:
        print(f"Could not copy ~/.vivo_ip to project: {e}")

# Target device to push code to (the Firestick running Termux)
fs_ip_file = Path(os.path.expanduser("~/.firestick_ip"))
device_ip = fs_ip_file.read_text().strip() if fs_ip_file.exists() else "192.168.8.246:5555"

files_to_push = [
    "ai_writer.py",
    "scheduler.py",
    "shadow_client.py",         # Shadow client pre-qualification (NEW)
    "generate_ig_drafts.py",
    "instagram_sender.py",
    "database.py",
    "sender.py",
    "ig_reply_responder.py",
    "server.py",
    "templates/index.html",
    "demo_templates/gym.html",

    "demo_generator.py",
    "vivo_ig_ui_sender.py",
    "demo_templates/config.json",
    "sync_engine.py",
    "unfollow_ghosts.py",
    "start_leadflow_failover.sh",
    "restore_vivo_adb.sh",
    "resolve_devices.py",
    ".vivo_ip"
]

print(f"Connecting to Firestick at {device_ip}...")
subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)

for f in files_to_push:
    local_path = f"/Users/chandan/leadflow/{f}"
    if not os.path.exists(local_path):
        print(f"Skipping missing file: {f}")
        continue
    print(f"Pushing {f}...")
    # Directly stream file content into the Termux private directory via shell stdin redirection
    dir_part = os.path.dirname(f)
    mkdir_cmd = f"mkdir -p /data/data/com.termux/files/home/leadflow/{dir_part} && " if dir_part else ""
    cmd = f"adb -s {device_ip} shell \"run-as com.termux sh -c '{mkdir_cmd}cat > /data/data/com.termux/files/home/leadflow/{f}'\" < {local_path}"
    subprocess.run(cmd, shell=True)



