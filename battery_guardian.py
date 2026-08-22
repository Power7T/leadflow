"""
Battery Guardian — Vivo 1807 charge limiter via ADB battery spoofing.

Real battery range kept to 20–60%.
Android is shown 0–100% mapped from that real range.
When real level hits 60%, Android is told "100% Full" → charge IC stops.
When real level drops to 20%, Android is told "0%" → charge IC resumes.
"""

import subprocess
import time
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BatteryGuardian] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("battery_guardian")

_home_ip = os.path.join(os.path.expanduser("~"), ".vivo_ip")
_local_ip = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vivo_ip")

def _read_ip(path):
    try:
        return open(path).read().strip()
    except Exception:
        return None

def _get_active_device():
    try:
        import resolve_devices
        res = resolve_devices.ensure_connected("vivo")
        if res:
            return res
    except Exception:
        pass
    return _read_ip(_home_ip) or _read_ip(_local_ip) or "192.168.8.157:5555"

DEVICE = _get_active_device()
def get_adb_binary() -> str:
    for path in ("/opt/homebrew/bin/adb.orig", "/usr/local/bin/adb.orig"):
        if os.path.exists(path):
            return path
    return "adb"

ADB = [get_adb_binary(), "-s", DEVICE]

REAL_HIGH = 60   # real % → spoof as 100 (stop charging)
REAL_LOW  = 20   # real % → spoof as 0   (resume charging)

CHECK_INTERVAL = 300  # seconds between checks (5 min)

_spoofing = False  # track whether we've applied a spoof


def adb(cmd):
    result = subprocess.run(ADB + cmd, capture_output=True, text=True)
    return result.stdout.strip()


def get_real_level():
    """Read real battery level by temporarily resetting spoof, reading, then re-applying if needed."""
    adb(["shell", "dumpsys", "battery", "reset"])
    time.sleep(0.5)
    out = adb(["shell", "dumpsys", "battery"])
    level = None
    ac = False
    for line in out.splitlines():
        if "level:" in line:
            try:
                level = int(line.split(":")[1].strip())
            except ValueError:
                pass
        if "AC powered: true" in line:
            ac = True
    return level, ac


def spoof(level, status):
    adb(["shell", "dumpsys", "battery", "set", "level", str(level)])
    adb(["shell", "dumpsys", "battery", "set", "status", str(status)])


def reset_spoof():
    adb(["shell", "dumpsys", "battery", "reset"])


def map_display_level(real):
    """Map real 20–60 range linearly to display 0–100."""
    clamped = max(REAL_LOW, min(REAL_HIGH, real))
    return int((clamped - REAL_LOW) / (REAL_HIGH - REAL_LOW) * 100)


def run():
    global _spoofing
    log.info(f"Starting. Device={DEVICE} | Limits: {REAL_LOW}%–{REAL_HIGH}% real → shown as 0–100%")

    while True:
        real, ac_powered = get_real_level()

        if real is None:
            log.warning("Could not read battery level — device unreachable?")
            time.sleep(CHECK_INTERVAL)
            continue

        display = map_display_level(real)
        log.info(f"Real={real}% | Display={display}% | AC={ac_powered} | Spoofing={_spoofing}")

        if real >= REAL_HIGH:
            # At ceiling — spoof as 100% Full to stop charging
            spoof(100, 5)  # status 5 = Full
            _spoofing = True
            log.info(f"Real {real}% >= {REAL_HIGH}% — spoofed to 100% Full. Charging halted.")

        elif real <= REAL_LOW:
            # At floor — reset spoof so Android sees real low level and resumes charging
            reset_spoof()
            _spoofing = False
            log.info(f"Real {real}% <= {REAL_LOW}% — spoof reset. Charging resumed.")

        else:
            # Mid-range — show linearly mapped display level, normal status
            if _spoofing:
                # Was blocking charge — now below ceiling, allow charge again
                spoof(display, 2)  # status 2 = Charging
                log.info(f"Real {real}% in range — spoofed display to {display}%, status=Charging.")
            else:
                # Not spoofing, leave Android alone
                reset_spoof()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Interrupted — resetting battery spoof before exit.")
        reset_spoof()
        sys.exit(0)
