import asyncio
from ppadb.client import Client as AdbClient
import xml.etree.ElementTree as ET
import time
import os
import random

# Get vivo IP
vivo_ip = None
if os.path.exists('/Users/chandan/leadflow/.vivo_ip'):
    with open('/Users/chandan/leadflow/.vivo_ip', 'r') as f:
        vivo_ip = f.read().strip()

if not vivo_ip:
    vivo_ip = "192.168.8.157:5555"
print(f"Connecting to Vivo at {vivo_ip}...")

client = AdbClient(host="127.0.0.1", port=5037)
device = client.device(vivo_ip)
if not device:
    print("❌ Failed to connect to device.")
    exit(1)
print("✅ Connected to Vivo phone.")

def check_for_try_again_later():
    print("📸 Dumping screen UI hierarchy...")
    # Dump UI hierarchy to XML
    xml_raw = device.shell("uiautomator dump /dev/tty").strip()
    
    # Check for specific popup texts
    if "Try again later" in xml_raw or "We restrict certain activity" in xml_raw:
        print("🚨 ACTION BLOCK DETECTED! 'Try again later' popup is on screen.")
        return True
    
    print("✅ Screen clear. No action block detected.")
    return False

def check_current_app():
    # Helper to check if IG is actually open
    app = device.shell("dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'").strip()
    print(f"📱 Current focused app info:\n{app}")

def test_screen():
    check_current_app()
    check_for_try_again_later()

if __name__ == "__main__":
    test_screen()
