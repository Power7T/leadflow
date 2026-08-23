import subprocess
import os

def run_adb_cmd(device_ip: str, command: str, timeout: int = 15) -> str:
    """
    Executes an ADB shell command against a specified target IP with an explicit timeout.
    Returns standard output as string, or empty string on failure/timeout.
    """
    adb_bin = "/opt/homebrew/bin/adb.orig" if os.path.exists("/opt/homebrew/bin/adb.orig") else "adb"
    full_cmd = f"{adb_bin} -s {device_ip} shell {command}"
    try:
        res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0:
            return res.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"[adb_utils] Command timed out after {timeout}s on {device_ip}: {command}")
    except Exception as e:
        print(f"[adb_utils] Error running ADB command on {device_ip}: {e}")
    return ""
