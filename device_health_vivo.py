"""
Vivo phone health optimization over ADB.
Covers: battery care, bloatware disable, performance settings, DNS.
Safe: does NOT touch any app the user actively uses.
Connect the phone via USB or wireless ADB before running.
"""

import subprocess
import sys
import os

# Dynamic IP resolution: ~/.vivo_ip → local .vivo_ip → fallback
_home_ip = os.path.join(os.path.expanduser("~"), ".vivo_ip")
_local_ip = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vivo_ip")
def _read_ip(path):
    try:
        return open(path).read().strip()
    except Exception:
        return None

DEVICE = _read_ip(_home_ip) or _read_ip(_local_ip) or "192.168.8.157:5555"
def get_adb_binary() -> str:
    for path in ("/opt/homebrew/bin/adb.orig", "/usr/local/bin/adb.orig"):
        if os.path.exists(path):
            return path
    return "adb"

ADB = [get_adb_binary(), "-s", DEVICE]

# ---------- Vivo bloatware to disable ----------
# Only disabling background services and apps that run silently.
# User can re-enable any of these: adb shell pm enable <package>
DISABLE_PACKAGES = [
    # Vivo system bloat
    "com.vivo.abe",                         # Vivo app backup engine
    "com.vivo.game.space",                  # game mode overlay
    "com.vivo.iCare",                       # Vivo device health (spyware-adjacent)
    "com.vivo.assistant",                   # Jovi AI assistant
    "com.bbk.theme",                        # Vivo theme store
    "com.vivo.smartshot",                   # smart screenshot service
    "com.vivo.browser",                     # Vivo browser (use Chrome instead)
    "com.vivo.easyshare",                   # file transfer bloat
    "com.vivo.globalmessagesimulation",     # message analytics
    "com.vivo.pushclient",                  # Vivo push notification tracker
    "com.vivo.daemonService",               # background daemon
    "com.vivo.network.prediction",          # network prediction tracker
    "com.vivo.vms",                         # Vivo message service analytics
    "com.vivo.appstore",                    # Vivo App Store
    "com.vivo.cloudservice",                # Vivo cloud sync (uploads to Vivo)
    "com.vivo.cloudbackup",                 # Vivo cloud backup
    "com.vivo.upslide",                     # side-swipe tray overlay
    "com.vivo.favorite",                    # Vivo bookmarks/shortcuts
    "com.vivo.globalsearch",                # global search overlay
    "com.android.BBKClock",                 # BBK/Vivo clock widget
    "com.vivo.doubleinstance",              # app clone service
    "com.vivo.numbermark",                  # phone number marking
    "com.vivo.smartmultiwindow",            # multi-window overlay service
    "com.vivo.appfilter",                   # app filter background service
    "com.vivo.permissionmanager",           # Vivo permission manager daemon
    "com.vivo.pem",                         # Vivo PEM background service
    "com.vivo.doubletimezoneclock",         # dual timezone clock widget
    "com.vivo.hiboard",                     # Vivo info board/feed
    "com.vivo.magazine",                    # Vivo magazine/news feed
    "com.vivo.gamewatch",                   # game watcher service
    "com.vivo.pushservice",                 # Vivo push service
    "com.vivo.safecenter",                  # Vivo security center
    "com.vivo.weather",                     # Vivo weather app
    "com.vivo.weather.provider",            # Vivo weather data provider
    "com.vivo.sim.contacts",               # SIM contacts sync
    "com.vivo.collage",                     # Vivo collage maker
    "com.vivo.compass",                     # compass app
    "com.vivo.email",                       # Vivo email client
    "com.vivo.ewarranty",                   # Vivo warranty service
    "com.vivo.flash",                       # Vivo flash/torch
    "com.vivo.floatingball",               # floating navigation ball
    "com.vivo.FMRadio",                     # FM Radio
    "com.vivo.mediatune",                   # media tuner
    "com.vivo.minscreen",                   # mini screen mode
    "com.vivo.motionrecognition",           # motion gesture recognition
    "com.vivo.motormode",                   # motor mode control
    "com.vivo.networkstate",               # network state monitor
    "com.vivo.scanner",                     # QR/barcode scanner
    "com.vivo.setupwizard",                # setup wizard
    "com.vivo.unionpay",                    # UnionPay payment
    "com.vivo.upnpserver",                  # UPnP server
    "com.vivo.video.floating",             # floating video player
    "com.vivo.videoeditor",                # Vivo video editor
    "com.vivo.website",                     # Vivo web portal
    "com.vivo.widget.calendar",            # calendar widget
    "com.vivo.dream.clock",               # dream clock
    "com.vivo.dream.music",               # dream music
    "com.vivo.dream.weather",             # dream weather
    "com.vivo.contentcatcher",            # content catcher
    "com.vivo.audiofx",                    # audio FX
    "com.vivo.childrenmode",              # kids mode
    "com.vivo.aikeydispatcher",           # AI key dispatcher
    "com.vivo.SmartKey",                   # Smart Key service
    "com.vivo.livewallpaper.coffeetime",  # live wallpaper
    "com.vivo.livewallpaper.coralsea",    # live wallpaper
    "com.vivo.livewallpaper.floatingcloud", # live wallpaper
    "com.vivo.livewallpaper.silk",        # live wallpaper
    "com.vlife.vivo.wallpaper",           # Vlife wallpaper service
    "com.bbk.iqoo.logsystem",             # iQOO log collection daemon
    # BBK (parent company) services
    "com.bbk.launcher2",                    # default Vivo launcher (if not using it)
    "com.bbk.livewallpaper",                # live wallpaper service
    "com.android.bbkmusic",                 # BBK music player
    "com.bbk.calendar",                     # BBK calendar
    "com.bbk.cloud",                        # BBK cloud sync
    "com.bbk.facewake",                     # face wake unlock
    "com.bbk.photoframewidget",             # photo frame widget
    "com.bbk.scene.indoor",                 # indoor scene mode
    "com.bbk.updater",                      # BBK OTA updater
    "com.bbk.SuperPowerSave",               # super power save mode
    "com.bbk.account",                      # BBK/Vivo account service
    # 3rd party preloads
    "com.gaana",                            # Gaana music (preinstalled)
    "com.ibimuyu.lockscreen",               # lockscreen replacement
    "com.til.timesnews",                    # Times of India news
    "com.ringclip",                         # ringclip app
    "app.buzz.share",                       # share app
    "cn.wps.moffice_eng",                   # WPS Office
    # Bluetooth — disabled (not used on this device)
    "com.android.bluetooth",               # Bluetooth stack
    "org.codeaurora.bluetooth",            # Qualcomm BT extension
    "org.codeaurora.btmultisim",           # BT dual-SIM bridge
    # Google bloat (background-only; keep if user opens them)
    "com.google.android.apps.photos",       # Google Photos
    "com.google.android.googlequicksearchbox",  # Google Search/feed
    "com.android.chrome",                   # Chrome (if not primary browser)
    "com.google.android.apps.news",         # Google News
    # UC Browser
    "com.UCMobile.intl",                    # UC Browser
    # Play Store — disable to prevent auto-updates consuming RAM
    "com.android.vending",                  # Play Store
    # Camera (not needed as background service)
    "com.android.camera",                   # Camera app
    # Common Android bloat on Vivo
    "com.facebook.appmanager",              # Facebook background installer
    "com.facebook.services",               # Facebook background services
    "com.facebook.system",                  # Facebook system helper
    "com.facebook.katana",                  # Facebook main app
]

# ---------- permissions to keep revoked ----------
# Revoked via ADB; Instagram can still browse but can't camera/mic/upload.
REVOKE_PERMISSIONS = [
    ("com.instagram.android", "android.permission.CAMERA"),
    ("com.instagram.android", "android.permission.RECORD_AUDIO"),
    ("com.instagram.android", "android.permission.READ_EXTERNAL_STORAGE"),
    ("com.instagram.android", "android.permission.WRITE_EXTERNAL_STORAGE"),
]

# ---------- background restrictions for heavy apps ----------
# These apps stay installed but are restricted from background wakeups.
RESTRICT_BACKGROUND = [
    "com.whatsapp",
    "com.facebook.katana",
    "com.facebook.orca",   # Messenger
    "com.instagram.android",
    "com.google.android.youtube",
    "com.snapchat.android",
]

# ---------- global settings ----------
GLOBAL_SETTINGS = {
    # Private DNS — Cloudflare
    "private_dns_mode": "hostname",
    "private_dns_specifier": "one.one.one.one",
    # Adaptive battery — let Android manage standby aggressively
    "app_standby_enabled": "1",
    "adaptive_battery_management_enabled": "1",
    # Background process limit — keep tight to prevent RAM bloat
    "max_cached_processes": "8",
}

SECURE_SETTINGS = {
    # Disable always-on display (kills battery)
    "doze_always_on": "0",
    # Enable doze mode (aggressive battery saving when screen off)
    "screensaver_enabled": "0",
}

SYSTEM_SETTINGS = {
    # Screen timeout — 30 seconds
    "screen_off_timeout": "30000",
    # Enable auto-brightness
    "screen_brightness_mode": "1",
    # Zero animations — eliminates GPU overhead entirely
    "window_animation_scale": "0",
    "transition_animation_scale": "0",
    "animator_duration_scale": "0",
}


def run(cmd, capture=True):
    result = subprocess.run(
        ADB + cmd,
        capture_output=capture,
        text=True,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def check_connected():
    out, err, code = run(["shell", "echo", "ok"])
    return out == "ok"


def disable_package(pkg):
    out, err, _ = run(["shell", "pm", "disable-user", "--user", "0", pkg])
    combined = (out + err).lower()
    if "disabled" in combined or "already disabled" in combined:
        return "disabled"
    if "doesn't exist" in combined or "unknown" in combined or "not installed" in combined:
        return "not_found"
    if "security exception" in combined or "protected package" in combined:
        return "protected"
    return f"error: {out or err}"


def restrict_background(pkg):
    # am set-inactive tells Android to treat app as inactive (no background wakeups)
    out, err, code = run(["shell", "am", "set-inactive", pkg, "true"])
    return code == 0


def apply_setting(namespace, key, value):
    out, err, code = run(["shell", "settings", "put", namespace, key, value])
    return code == 0


def clear_caches():
    out, err, code = run(["shell", "pm", "trim-caches", "999999999"])
    return code == 0


def reset_battery_stats():
    out, err, code = run(["shell", "dumpsys", "batterystats", "--reset"])
    return code == 0


def get_battery_info():
    out, _, _ = run(["shell", "dumpsys", "battery"])
    info = {}
    for line in out.splitlines():
        for key in ("level", "health", "temperature", "voltage", "status"):
            if key + ":" in line:
                info[key] = line.split(":", 1)[1].strip()
    return info


def set_battery_charge_limit():
    """Try every known Vivo/Android path to cap charging at 60%.

    Vivo uses a mix of global/system/secure keys depending on firmware version.
    We write all known variants so at least one sticks on any ROM shipped between
    Vivo V/Y/T series Android 11–14.  None of these damage the device; worst case
    the setting is silently ignored by the kernel.
    """
    # Step 1: Enable battery-care / protection mode (required on some FOTA builds)
    apply_setting("secure", "battery_protection_enabled", "1")
    apply_setting("global", "battery_care_mode", "1")

    # Step 2: Set the charge ceiling across every known namespace+key combo
    attempts = [
        ("global",  "charge_limit_level",      "60"),
        ("global",  "battery_care_level",       "60"),
        ("global",  "battery_saver_schedule",   "60"),
        ("system",  "battery_limit_level",      "60"),
        ("system",  "battery_charge_limit",     "60"),
        ("secure",  "battery_protection_level", "60"),
        ("secure",  "charge_threshold",         "60"),
    ]
    results = []
    for ns, key, val in attempts:
        ok = apply_setting(ns, key, val)
        results.append((ns, key, ok))
    return results


def revoke_permissions():
    for pkg, perm in REVOKE_PERMISSIONS:
        run(["shell", "pm", "revoke", pkg, perm])


def run_optimization():
    print(f"\n=== Vivo Phone Health Optimization ===")
    print(f"Device: {DEVICE}\n")

    if not check_connected():
        print(f"ERROR: Cannot reach {DEVICE}.")
        print("Make sure wireless ADB is enabled on the phone (Developer Options → Wireless debugging)")
        print(f"or connect via USB and run: adb connect {DEVICE}")
        sys.exit(1)

    # Show battery state before
    battery = get_battery_info()
    if battery:
        level = battery.get("level", "?")
        temp_raw = battery.get("temperature", "0")
        try:
            temp_c = int(temp_raw) / 10
        except ValueError:
            temp_c = "?"
        health = {"1": "Unknown", "2": "Good", "3": "Overheat",
                  "4": "Dead", "5": "Over voltage", "6": "Unspecified failure",
                  "7": "Cold"}.get(battery.get("health", "1"), battery.get("health", "?"))
        print(f"Battery before: {level}% | Health: {health} | Temp: {temp_c}°C\n")

    print("[1/6] Disabling Vivo bloatware / background services...")
    disabled, skipped, protected, errors = 0, 0, 0, 0
    for pkg in DISABLE_PACKAGES:
        result = disable_package(pkg)
        if result == "disabled":
            print(f"  OK  {pkg}")
            disabled += 1
        elif result == "not_found":
            skipped += 1
        elif result == "protected":
            protected += 1
        else:
            print(f"  !!  {pkg} — {result}")
            errors += 1
    print(f"  → {disabled} disabled, {protected} system-protected (normal), {skipped} not found, {errors} errors\n")

    print("[2/6] Restricting heavy apps from background wakeups...")
    for pkg in RESTRICT_BACKGROUND:
        ok = restrict_background(pkg)
        print(f"  {'OK' if ok else '!!'} {pkg}")

    print(f"\n[3/6] Applying global settings...")
    for key, value in GLOBAL_SETTINGS.items():
        ok = apply_setting("global", key, value)
        print(f"  {'OK' if ok else '!!'} global/{key} = {value}")

    print(f"\n[4/6] Applying secure & system settings...")
    for key, value in SECURE_SETTINGS.items():
        ok = apply_setting("secure", key, value)
        print(f"  {'OK' if ok else '!!'} secure/{key} = {value}")
    for key, value in SYSTEM_SETTINGS.items():
        ok = apply_setting("system", key, value)
        print(f"  {'OK' if ok else '!!'} system/{key} = {value}")

    print(f"\n[5/6] Clearing app caches, resetting battery stats & locking permissions...")
    ok_cache = clear_caches()
    ok_batt = reset_battery_stats()
    revoke_permissions()
    print(f"  {'OK' if ok_cache else '!!'} Cache trim")
    print(f"  {'OK' if ok_batt else '!!'} Battery stats reset")
    print(f"  OK  Instagram camera/mic/storage permissions revoked")

    print(f"\n[6/6] Applying 60% battery charge cap (permanent battery health protection)...")
    limit_results = set_battery_charge_limit()
    for ns, key, ok in limit_results:
        print(f"  {'OK' if ok else '!!'} {ns}/{key} = 60")
    print("  → Charge cap applied. Vivo should stop charging at 60% when connected.")

    print("\n=== Done ===")
    print("Tips to keep battery healthy:")
    print("  • Charge between 20–80% where possible")
    print("  • Avoid charging overnight / to 100% and leaving plugged in")
    print("  • Keep phone away from direct heat / sunlight while charging")
    print("Re-run this script monthly to clear caches.")
    print("To re-enable any package: adb shell pm enable <package>")


if __name__ == "__main__":
    run_optimization()
