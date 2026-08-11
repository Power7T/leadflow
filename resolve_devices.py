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

def get_subnet():
    # Try Android "ip -4 route default"
    try:
        out = subprocess.check_output("ip -4 route show default", shell=True, stderr=subprocess.DEVNULL).decode()
        m = re.search(r"default via (\d+\.\d+\.\d+)\.\d+", out)
        if m:
            return m.group(1)
    except Exception:
        pass

    # Try Mac "route -n get default"
    try:
        out = subprocess.check_output("route -n get default", shell=True, stderr=subprocess.DEVNULL).decode()
        m = re.search(r"gateway:\s+(\d+\.\d+\.\d+)\.\d+", out)
        if m:
            return m.group(1)
    except Exception:
        pass

    # Try ip addr
    try:
        out = subprocess.check_output("ip -4 addr show", shell=True, stderr=subprocess.DEVNULL).decode()
        m = re.search(r"inet (\d+\.\d+\.\d+)\.\d+/\d+", out)
        if m:
            return m.group(1)
    except Exception:
        pass

    try:
        out = subprocess.check_output("ifconfig", shell=True, stderr=subprocess.DEVNULL).decode()
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                import re
                m = re.search(r"inet (\d+\.\d+\.\d+)\.\d+", line)
                if m:
                    return m.group(1)
    except Exception:
        pass

    # Last resort: detect own IP via socket and extract subnet
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        own_ip = s.getsockname()[0]
        s.close()
        parts = own_ip.split(".")
        if len(parts) == 4 and not own_ip.startswith("127."):
            return ".".join(parts[:3])
    except Exception:
        pass

    return "192.168.8"

def scan_network():
    subnet = get_subnet()
    print(f"Scanning network subnet: {subnet}.*")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=30) as executor:
        for i in range(1, 255):
            executor.submit(ping_ip, f"{subnet}.{i}")

def get_arp_table():
    # Try arp -an first
    try:
        arp_out = subprocess.check_output("arp -an", shell=True, stderr=subprocess.DEVNULL).decode()
        if arp_out.strip():
            return arp_out
    except Exception:
        pass

    # Fallback for Android/Termux if arp is restricted
    try:
        ip_neigh = subprocess.check_output("ip neigh show", shell=True, stderr=subprocess.DEVNULL).decode()
        if ip_neigh.strip():
            # Format: 192.168.0.113 dev wlan0 lladdr ec:2b:eb:b0:01:a3 REACHABLE
            out = []
            for line in ip_neigh.split('\n'):
                m = re.search(r"(\d+\.\d+\.\d+\.\d+).*lladdr\s+([0-9a-fA-F:]+)", line)
                if m:
                    out.append(f"? ({m.group(1)}) at {m.group(2)}")
            return "\n".join(out)
    except Exception:
        pass

    return ""

def resolve():
    # 1. Parse current ARP cache first
    arp_out = get_arp_table()
    
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
        arp_out = get_arp_table()
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
        Path(os.path.dirname(os.path.abspath(__file__)) + "/.vivo_ip").write_text(f"{vivo_ip}:5555")
        print(f"Resolved Vivo Phone IP: {vivo_ip}:5555")

if __name__ == "__main__":
    resolve()


def _adb_ok(device_ip, timeout=5):
    try:
        res = subprocess.run(["adb", "-s", device_ip, "shell", "echo", "1"],
                             capture_output=True, text=True, timeout=timeout)
        return "1" in res.stdout
    except Exception:
        return False


def _enable_tcpip_via_usb(target_lower):
    """Try to find a USB-connected Android device and enable tcpip 5555."""
    # Known USB serial for Vivo (stored when first seen)
    _usb_serial_file = Path(os.path.expanduser("~")) / f".{target_lower}_usb_serial"
    try:
        out = subprocess.check_output(["adb", "devices"], text=True, timeout=10)
        usb_devices = []
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) == 2 and parts[1] == "device":
                serial = parts[0]
                # USB serials don't contain colons (TCP ones do)
                if ":" not in serial:
                    usb_devices.append(serial)
                    _usb_serial_file.write_text(serial)

        if not usb_devices:
            return None

        # Use previously known serial first, then any USB device
        preferred = None
        if _usb_serial_file.exists():
            known = _usb_serial_file.read_text().strip()
            if known in usb_devices:
                preferred = known
        serial = preferred or usb_devices[0]

        subprocess.run(["adb", "-s", serial, "tcpip", "5555"],
                       capture_output=True, timeout=10)
        import time
        time.sleep(2)  # give adbd time to restart in TCP mode
        return serial
    except Exception:
        return None


def _send_ntfy(target, message, title, tags="robot,heavy_check_mark"):
    try:
        from dotenv import load_dotenv
        load_dotenv(f"{os.path.dirname(os.path.abspath(__file__))}/.env")
        import requests
        _ntfy = os.getenv("NTFY_TOPIC")
        if _ntfy:
            requests.post(
                f"https://ntfy.sh/{_ntfy}",
                data=message.encode("utf-8"),
                headers={"Title": title, "Tags": tags, "Priority": "default"},
                timeout=5,
            )
    except Exception:
        pass


def ensure_connected(target="vivo"):
    target_lower = target.lower()
    home = os.path.expanduser("~")
    local_path = Path(f"{os.path.dirname(os.path.abspath(__file__))}/.{target_lower}_ip")
    home_path = Path(f"{home}/.{target_lower}_ip")

    device_ip = None
    if home_path.exists():
        device_ip = home_path.read_text().strip()
    elif local_path.exists():
        device_ip = local_path.read_text().strip()

    original_ip = device_ip

    # --- Step 1: Try cached IP ---
    if device_ip and _adb_ok(device_ip):
        return device_ip

    print(f"[resolve] '{target}' not reachable at {device_ip}. Scanning network...")
    if device_ip:
        subprocess.run(f"adb disconnect {device_ip}", shell=True, stderr=subprocess.DEVNULL)

    # --- Step 2: Resolve new IP by MAC ---
    resolve()

    if home_path.exists():
        device_ip = home_path.read_text().strip()
        print(f"[resolve] Re-resolved {target} -> {device_ip}")

    if device_ip:
        subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)
        if _adb_ok(device_ip):
            if device_ip != original_ip:
                _send_ntfy(target, f"{target.upper()} IP auto-updated to {device_ip}",
                           f"{target.capitalize()} IP Auto-Healed")
            return device_ip

    # --- Step 3: Vivo-specific — try USB to re-enable tcpip ---
    if target_lower == "vivo":
        print(f"[resolve] Wireless ADB failed. Trying USB fallback to re-enable tcpip...")
        usb_serial = _enable_tcpip_via_usb(target_lower)
        if usb_serial and device_ip:
            subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)
            if _adb_ok(device_ip):
                print(f"[resolve] Vivo recovered via USB tcpip -> {device_ip}")
                _send_ntfy(target,
                           f"VIVO ADB TCP re-enabled via USB. Now on {device_ip}",
                           "Vivo USB Auto-Heal", tags="robot,usb,heavy_check_mark")
                return device_ip

    print(f"[resolve] WARNING: '{target}' could not be recovered automatically.")
    _send_ntfy(target,
               f"{target.upper()} offline and could not self-heal. Manual intervention needed.",
               f"{target.capitalize()} Offline", tags="warning,robot")
    return None
