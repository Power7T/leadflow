import subprocess
import threading
import os
import re
from pathlib import Path

# Hardware MAC Addresses (fixed per device)
FIRESTICK_MAC = "ec:2b:eb:b0:01:a3"
VIVO_MAC = "5c:1c:b9:86:af:9d"

def normalize_mac(mac):
    parts = mac.lower().replace('-', ':').split(':')
    return ':'.join(p.zfill(2) for p in parts)

def ping_ip(ip):
    subprocess.run(f"ping -c 1 -t 1 {ip}", shell=True, capture_output=True)

def scan_network():
    # Detect local subnet from gateway
    subnet = "192.168.1"
    try:
        route_out = subprocess.check_output("route -n get default", shell=True).decode()
        m = re.search(r"gateway:\s+(\d+\.\d+\.\d+)\.\d+", route_out)
        if m:
            subnet = m.group(1)
    except Exception:
        pass
        
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=30) as executor:
        for i in range(1, 255):
            executor.submit(ping_ip, f"{subnet}.{i}")

def resolve():
    # 1. Parse current ARP cache first
    arp_out = subprocess.check_output("arp -an", shell=True).decode()
    
    fs_ip = None
    vivo_ip = None
    
    for line in arp_out.split('\n'):
        m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)", line)
        if m:
            ip = m.group(1)
            mac = normalize_mac(m.group(2))
            if mac == normalize_mac(FIRESTICK_MAC):
                fs_ip = ip
            elif mac == normalize_mac(VIVO_MAC):
                vivo_ip = ip
                
    # 2. If not in cache, run a concurrent scan to populate ARP cache
    if not fs_ip or not vivo_ip:
        scan_network()
        arp_out = subprocess.check_output("arp -an", shell=True).decode()
        for line in arp_out.split('\n'):
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)", line)
            if m:
                ip = m.group(1)
                mac = normalize_mac(m.group(2))
                if mac == normalize_mac(FIRESTICK_MAC):
                    fs_ip = ip
                elif mac == normalize_mac(VIVO_MAC):
                    vivo_ip = ip
                    
    # 3. Persist resolved IPs
    home = os.path.expanduser("~")
    if fs_ip:
        Path(f"{home}/.firestick_ip").write_text(f"{fs_ip}:5555")
        print(f"Resolved Firestick IP: {fs_ip}:5555")
    if vivo_ip:
        Path(f"{home}/.vivo_ip").write_text(f"{vivo_ip}:5555")
        # Copy to project folder for local file sync
        Path("/Users/chandan/leadflow/.vivo_ip").write_text(f"{vivo_ip}:5555")
        print(f"Resolved Vivo Phone IP: {vivo_ip}:5555")

if __name__ == "__main__":
    resolve()
