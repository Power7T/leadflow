"""
Unified device health runner.
Usage:
  python device_health.py           # both devices
  python device_health.py firestick # Fire TV only
  python device_health.py vivo      # Vivo phone only
"""

import subprocess
import sys
import os

ADB_BIN = "/opt/homebrew/bin/adb.orig"


def load_ip_from_file(path, default):
    try:
        return open(path).read().strip()
    except Exception:
        return default


def _resolve_ip(home_file, local_file, fallback):
    """Resolve device IP: ~/.xxx_ip → local .xxx_ip → hardcoded fallback."""
    home_path = os.path.join(os.path.expanduser("~"), home_file)
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_file)
    return load_ip_from_file(home_path, load_ip_from_file(local_path, fallback))


# Dynamic IP resolution (updated by resolve_devices.py)
FS_IP = _resolve_ip(".firestick_ip", ".firestick_ip", "192.168.0.113:5555")
VIVO_IP = _resolve_ip(".vivo_ip", ".vivo_ip", "192.168.0.162:5555")


def connect_device(ip):
    out = subprocess.run(
        [ADB_BIN, "connect", ip],
        capture_output=True, text=True
    ).stdout.strip()
    return "connected" in out or "already connected" in out


def device_online(ip):
    result = subprocess.run(
        [ADB_BIN, "-s", ip, "shell", "echo", "ok"],
        capture_output=True, text=True
    )
    return result.stdout.strip() == "ok"



def run_script(script_path, label):
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    python = sys.executable if sys.executable else "python3"
    result = subprocess.run([python, script_path])
    return result.returncode == 0


def main():
    target = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if target not in ("firestick", "vivo", "both"):
        print("Usage: python device_health.py [firestick|vivo|both]")
        sys.exit(1)

    here = os.path.dirname(os.path.abspath(__file__))

    # Resolve IPs from saved files (updated by resolve_devices.py)
    fs_ip = load_ip_from_file(os.path.join(here, ".firestick_ip"), FS_IP)
    vivo_ip = load_ip_from_file(os.path.join(here, ".vivo_ip"), VIVO_IP)

    results = {}

    if target in ("firestick", "both"):
        print(f"\nConnecting to Fire TV Stick at {fs_ip}...")
        connect_device(fs_ip)
        if device_online(fs_ip):
            ok = run_script(os.path.join(here, "device_health_firestick.py"), "Fire TV Stick")  # noqa
            results["firestick"] = "OK" if ok else "ERRORS (check output above)"
        else:
            print(f"  SKIP: Fire TV Stick not reachable at {fs_ip}")
            results["firestick"] = "OFFLINE"

    if target in ("vivo", "both"):
        print(f"\nConnecting to Vivo phone at {vivo_ip}...")
        connect_device(vivo_ip)
        if device_online(vivo_ip):
            ok = run_script(os.path.join(here, "device_health_vivo.py"), "Vivo Phone")
            results["vivo"] = "OK" if ok else "ERRORS (check output above)"
        else:
            print(f"  SKIP: Vivo phone not reachable at {vivo_ip}")
            print("  Make sure wireless debugging is on: Settings → Developer Options → Wireless debugging")
            results["vivo"] = "OFFLINE"

    print(f"\n{'='*50}")
    print("  Summary")
    print(f"{'='*50}")
    for device, status in results.items():
        print(f"  {device:<12} {status}")
    print()


if __name__ == "__main__":
    main()
