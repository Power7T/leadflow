import os
import time
import requests
import subprocess
from dotenv import load_dotenv

load_dotenv()

PUBLIC_URL = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
TOKEN = os.getenv("SECRET_TOKEN")

def check_mac_heartbeat():
    try:
        r = requests.get(f"{PUBLIC_URL}/api/leadership", params={"token": TOKEN}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            last_ts = data.get("heartbeats", {}).get("mac", 0)
            if last_ts > 0:
                age_minutes = (time.time() * 1000 - last_ts) / 1000 / 60
                return age_minutes
    except Exception as e:
        print(f"Error checking heartbeat: {e}")
    return 99999.0 # Assume Mac is offline if check fails

def is_scheduler_running():
    try:
        out = subprocess.check_output("pgrep -f 'python3 scheduler.py'", shell=True).decode()
        return len(out.strip()) > 0
    except Exception:
        return False

def main():
    age = check_mac_heartbeat()
    print(f"Mac last heartbeat age: {age:.1f} minutes")
    
    # If Mac has not sent a heartbeat for more than 15 minutes
    if age > 15.0:
        if not is_scheduler_running():
            print("🚨 Mac is OFFLINE! Starting backup scheduler on Firestick...")
            subprocess.Popen(
                "nohup python3 -u scheduler.py > scheduler_backup.log 2>&1 &",
                shell=True,
                cwd="/data/data/com.termux/files/home/leadflow"
            )
            # Send ntfy notification
            try:
                topic = os.getenv("NTFY_TOPIC")
                requests.post(
                    f"https://ntfy.sh/{topic}",
                    data="⚠️ Mac server went offline! Running backup sending engine on Firestick 24/7.",
                    headers={"Title": "LeadFlow - Failover Activated", "Priority": "high", "Tags": "warning,fire"},
                    timeout=5
                )
            except: pass
        else:
            print("Backup scheduler is already running on Firestick.")
    else:
        # Mac is online! If the backup scheduler is running, kill it to avoid double-sending!
        if is_scheduler_running():
            print("✅ Mac is ONLINE again! Stopping backup scheduler on Firestick...")
            subprocess.run("pkill -f 'python3 scheduler.py'", shell=True)
            # Send ntfy notification
            try:
                topic = os.getenv("NTFY_TOPIC")
                requests.post(
                    f"https://ntfy.sh/{topic}",
                    data="✅ Mac server restored! Backup sending engine on Firestick deactivated.",
                    headers={"Title": "LeadFlow - Failover Deactivated", "Priority": "default", "Tags": "white_check_mark"},
                    timeout=5
                )
            except: pass

if __name__ == "__main__":
    main()
