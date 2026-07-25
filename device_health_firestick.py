"""
Fire TV Stick health optimization.
Safe list: Termux, com.termux.boot, com.netflix.ninja,
           com.arlosoft.macrodroid, me.efesser.flauncher — never touched.
Remote app safe list (Fire TV app on phone):
  com.amazon.tv.devicecontrol, com.amazon.tv.devicecontrolsettings,
  com.amazon.uxcontrollerservice, com.amazon.tcomm, com.amazon.tcomm.client,
  com.amazon.tcomm.jackson, com.amazon.dialservice, com.amazon.whisperlink.core.android,
  com.amazon.whisperplay.contracts, com.amazon.whisperplay.service.install,
  com.amazon.whisperjoin.middleware.np, com.amazon.rtcsessioncontroller,
  com.amazon.connectivitycontroller, com.amazon.net.smartconnect, com.amazon.cast.sink
Everything else that is pure analytics/ads/bloat gets disabled.
Re-run anytime; already-disabled packages are silently skipped.
"""

import subprocess
import sys

DEVICE = "192.168.0.113:5555"
ADB = ["adb", "-s", DEVICE]

# ---------- packages to disable ----------
# Only disabling clear bloat: ads, analytics, shopping, ACR, telemetry,
# duplicate Amazon media services, OTA auto-update, unused Alexa extras.
# Keeping: launcher, settings, system UI, bluetooth, NFC, core Amazon services,
#          Termux, Instagram, Netflix, MacroDroid, FLauncher, Hotstar.
DISABLE_PACKAGES = [
    # Ads & tracking
    "com.amazon.ftvads.deeplinking",
    "com.amazon.hybridadidservice",
    "com.amazon.client.metrics",          # analytics client
    "com.amazon.tv.fw.metrics",           # firmware metrics
    "com.amazon.wirelessmetrics.service", # wireless analytics
    "com.amazon.perfcollection",          # perf telemetry uploader
    "com.amazon.perfc",                   # perf collector
    "com.amazon.device.metrics",          # device analytics
    "com.fireos.usagestats.proxy",        # usage stats proxy to Amazon
    "com.amazon.dp.logger",              # data plane logger
    # Shopping / commerce
    "com.amazon.shoptv.client",
    "com.amazon.shoptv.firetv.client",
    "com.amazon.bueller.music",           # Amazon Music shopping
    "com.amazon.bueller.photos",          # Amazon Photos shopping
    # ACR (Automatic Content Recognition — listens to what you watch)
    "com.amazon.tv.acr",
    # Alexa extras (not core; core Alexa for voice nav is kept)
    "com.amazon.tv.alexaalerts",
    "com.amazon.tv.alexanotifications",
    # OTA auto-updates (we update manually)
    "com.amazon.tv.forcedotaupdater.v2",
    # Still watching / engagement tracking
    "com.amazon.stillwatching.activity",
    # Prism (Amazon ad personalization service)
    "com.amazon.prism.android.service",
    # NOTE: com.amazon.device.sync is system-protected — skip
    # Sneakpeek (pre-roll video ads on screensaver)
    "com.amazon.sneakpeek",
    # MiniTV (Amazon MiniTV streaming ads)
    "com.amazon.minitv.android.app",
    # Media recommendations (push "what to watch" ads)
    "com.amazon.media.recommendations",
    # Game Hub
    "com.amazon.gamehub",
    # OOBE / setup wizard (already done)
    "com.amazon.tv.oobe",
    # Tutorial
    "com.amazon.storm.lightning.tutorial",
    "com.amazon.tmm.tutorial",
    # Easy upgrade wizard
    "com.amazon.tv.easyupgrade",
]

# ---------- settings to apply ----------
GLOBAL_SETTINGS = {
    # DNS — Cloudflare private DNS
    "private_dns_mode": "hostname",
    "private_dns_specifier": "one.one.one.one",
    # Background process cap (Fire TV default is 0 = unlimited)
    "max_cached_processes": "8",
    # Disable background data for unnecessary services
    "background_data": "1",
}

SECURE_SETTINGS = {
    # Disable always-on listening indicator light
    "voice_interaction_service_enabled": "0",
}

SYSTEM_SETTINGS = {
    # Reduce animation scales (already 0 on this device but enforce)
    "window_animation_scale": "0.5",
    "transition_animation_scale": "0.5",
    "animator_duration_scale": "0.5",
    # Screen timeout 30 min — screen sleeps but Termux keeps running
    "screen_off_timeout": "1800000",
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


def apply_setting(namespace, key, value):
    out, err, code = run(["shell", "settings", "put", namespace, key, value])
    return code == 0


def clear_caches():
    out, err, code = run(["shell", "pm", "trim-caches", "999999999"])
    return code == 0


def clear_anr_logs():
    out, err, code = run(["shell", "rm", "-rf", "/data/anr/"])
    return code == 0


def reset_battery_stats():
    # Fire TV has no real battery but reset analytics counters anyway
    out, err, code = run(["shell", "dumpsys", "batterystats", "--reset"])
    return code == 0


def get_storage_info():
    out, _, _ = run(["shell", "df", "-h", "/data"])
    return out


def get_top_data_consumers():
    out, _, _ = run(["shell", "dumpsys", "diskstats"])
    lines = out.splitlines()
    data_free = next((l for l in lines if "Data-Free" in l), "")
    app_data = next((l for l in lines if "App Data Size" in l), "")
    return data_free, app_data


def run_optimization():
    print(f"\n=== Fire TV Stick Health Optimization ===")
    print(f"Device: {DEVICE}\n")

    if not check_connected():
        print(f"ERROR: Cannot reach {DEVICE}. Connect first.")
        sys.exit(1)

    # Show storage before
    data_free, _ = get_top_data_consumers()
    if data_free:
        print(f"Storage: {data_free.strip()}\n")

    print("[1/5] Ensuring Fire TV remote app packages are enabled...")
    # These are required for the Amazon Fire TV app (phone remote) to connect.
    # Explicitly enable them every run so they're never accidentally left disabled.
    REMOTE_PACKAGES = [
        "com.amazon.uxcontrollerservice",       # UX controller / remote input
        "com.amazon.whisperplay.service.install", # WhisperPlay install bridge
        "com.amazon.whisperjoin.middleware.np",  # device pairing / provisioning
        "com.amazon.tv.devicecontrol",           # device control service
        "com.amazon.tcomm",                      # transport communication
        "com.amazon.whisperlink.core.android",   # WhisperLink core
        "com.amazon.dialservice",                # DIAL protocol (app launch from phone)
        "com.amazon.rtcsessioncontroller",       # RTC session (remote control channel)
        "com.amazon.connectivitycontroller",     # connectivity management
    ]
    for pkg in REMOTE_PACKAGES:
        out, err, _ = run(["shell", "pm", "enable", pkg])
        combined = (out + err).lower()
        if "enabled" in combined:
            print(f"  OK  {pkg}")
        else:
            print(f"  !!  {pkg} — {out or err}")
    print()

    print("[2/5] Disabling bloatware / analytics packages...")
    disabled, skipped, protected, errors = 0, 0, 0, 0
    for pkg in DISABLE_PACKAGES:
        result = disable_package(pkg)
        if result == "disabled":
            print(f"  OK  {pkg}")
            disabled += 1
        elif result == "not_found":
            skipped += 1
        elif result == "protected":
            protected += 1  # Amazon locks these — expected, not an error
        else:
            print(f"  !!  {pkg} — {result}")
            errors += 1
    print(f"  → {disabled} disabled, {protected} system-protected (normal), {skipped} not found, {errors} errors\n")

    print("[3/5] Applying global settings...")
    for key, value in GLOBAL_SETTINGS.items():
        ok = apply_setting("global", key, value)
        print(f"  {'OK' if ok else '!!'} global/{key} = {value}")

    print("\n[4/5] Applying secure settings...")
    for key, value in SECURE_SETTINGS.items():
        ok = apply_setting("secure", key, value)
        print(f"  {'OK' if ok else '!!'} secure/{key} = {value}")

    print("\n  Applying system settings...")
    for key, value in SYSTEM_SETTINGS.items():
        ok = apply_setting("system", key, value)
        print(f"  {'OK' if ok else '!!'} system/{key} = {value}")

    print("\n[5/5] Clearing app caches and crash logs...")
    ok = clear_caches()
    ok_anr = clear_anr_logs()
    print(f"  {'OK' if ok else '!!'} Cache trim complete")
    print(f"  {'OK' if ok_anr else '!!'} ANR crash logs cleared")

    print("\n=== Done ===")
    print("Termux, Netflix, MacroDroid, FLauncher, Hotstar — UNTOUCHED.")
    print("Re-run this script monthly to clear caches.")
    print("To re-enable any package: adb shell pm enable <package>")
    print()
    print("TIP: Termux holds 1.9GB of data (leadflow + pip cache). Free space in Termux:")
    print("  pip cache purge && apt clean")


if __name__ == "__main__":
    run_optimization()
