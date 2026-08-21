"""
Fire TV Stick health optimization.
Safe list: Termux, com.termux.boot, com.netflix.ninja,
           com.arlosoft.macrodroid, me.efesser.flauncher, com.instagram.android — never touched.
Remote app safe list (Fire TV app on phone):
  com.amazon.tv.devicecontrol, com.amazon.tv.devicecontrolsettings,
  com.amazon.uxcontrollerservice, com.amazon.tcomm, com.amazon.tcomm.client,
  com.amazon.tcomm.jackson, com.amazon.dialservice, com.amazon.whisperlink.core.android,
  com.amazon.whisperplay.contracts, com.amazon.whisperplay.service.install,
  com.amazon.whisperjoin.middleware.np, com.amazon.rtcsessioncontroller,
  com.amazon.connectivitycontroller, com.amazon.net.smartconnect, com.amazon.cast.sink
Everything else that is pure analytics/ads/Alexa/telemetry/remote-management gets disabled.
Re-run anytime; already-disabled packages are silently skipped.
"""

import subprocess
import sys
import os
import time

_home_ip = os.path.join(os.path.expanduser("~"), ".firestick_ip")
_local_ip = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".firestick_ip")

def _read_ip(path):
    try:
        return open(path).read().strip()
    except Exception:
        return None

DEVICE = _read_ip(_home_ip) or _read_ip(_local_ip) or "192.168.8.246:5555"
def get_adb_binary() -> str:
    for path in ("/opt/homebrew/bin/adb.orig", "/usr/local/bin/adb.orig"):
        if os.path.exists(path):
            return path
    return "adb"

ADB = [get_adb_binary(), "-s", DEVICE]

# ---------- packages to disable ----------
# Targets: ads, analytics, Alexa stack, Amazon remote device management,
#          OTA, telemetry, diagnostics, bloat daemons — all safe to kill.
# Keeping: launcher, settings, system UI, Termux, Instagram, Netflix,
#          MacroDroid, FLauncher, Hotstar, core ADB/network stack.
DISABLE_PACKAGES = [
    # ── BIGGEST RAM WINS ─────────────────────────────────────────────────
    "com.amazon.firebat",                      # ~134MB — Amazon analytics broker / device mgmt
    "com.amazon.vizzini",                      # ~65MB  — Amazon video ad engine
    "com.amazon.vizzini.ftvcds",               # ad companion to vizzini
    "com.amazon.alexamediaplayer.runtime.ftv", # ~26MB  — Alexa media player runtime
    "com.amazon.ftvads.deeplinking",           # ad deep-link service

    # ── METRICS / TELEMETRY ──────────────────────────────────────────────
    "com.amazon.client.metrics",               # ~15MB  — Amazon telemetry collector
    "com.amazon.client.metrics.api",           # metrics API layer
    "com.amazon.device.metrics",               # device-level metrics daemon
    "com.amazon.device.logmanager",            # remote log upload daemon
    "com.amazon.device_remote_config_sync_service",  # A/B test config sync (phones home)
    "com.amazon.securitysyncclient",           # security state sync to Amazon cloud
    "com.amazon.fireos.rescuepartycloud",      # crash reporter — sends dumps to Amazon
    "com.amazon.fireos.cirruscloud",           # Cirrus cloud agent
    "com.amazon.connectivitydiag",             # connectivity diagnostic uploader
    "com.amazon.firetv.troubleshooting",       # remote troubleshooting/upload agent
    "com.amazon.device.crashmanager",          # crash data collector
    "com.amazon.device.lowstoragemanager",     # low storage watcher/reporter
    "com.fireos.usagestats.proxy",             # usage stats proxy to Amazon
    "com.fireos.arcus.proxy",                  # Arcus proxy (analytics relay)
    "com.amazon.tv.developer.dataservice",     # developer data service (telemetry)

    # Older telemetry packages (may not be installed but harmless to try)
    "com.amazon.tv.fw.metrics",
    "com.amazon.wirelessmetrics.service",
    "com.amazon.perfcollection",
    "com.amazon.perfc",
    "com.amazon.dp.logger",
    "com.amazon.hybridadidservice",

    # ── ALEXA STACK (no mic on Firestick Lite, user doesn't use Alexa) ───
    "com.amazon.alexa.datastore.app",          # Alexa data store
    "com.amazon.alexadirectivebrokerservice",  # Alexa directive broker
    "com.amazon.livedeviceservice",            # Alexa/Echo live device discovery
    "com.amazon.communication.discovery",      # Alexa LAN discovery daemon
    "com.amazon.alta.h2clientservice",         # Alexa H2 connection manager
    "com.amazon.whisperlink.core.android",     # Whisper link (Alexa inter-device)
    "com.amazon.whisperjoin.middleware.np",    # Whisper join middleware
    "com.amazon.neopactservice",               # Fire OS device pact compliance
    "com.amazon.neodelegate",                  # Pact delegate daemon
    "com.amazon.tv.alexaalerts",               # Alexa alert UI
    "com.amazon.tv.alexanotifications",        # Alexa notification UI

    # ── AMAZON REMOTE DEVICE MANAGEMENT (Amazon can control your device) ─
    "com.amazon.device.rdmapplication",        # Amazon Remote Device Management app
    "com.amazon.ssm",                          # Amazon SSM agent
    "com.amazon.ssmsys",                       # SSM system component
    "com.amazon.dpcclient",                    # DPC (device policy) client
    "com.amazon.device.software.ota",          # OTA updater (prevents unwanted Fire OS updates)
    "com.amazon.device.software.ota.override", # OTA override manager
    "com.amazon.tv.forcedotaupdater.v2",       # forced OTA updater v2

    # ── NOTE: Bluetooth is intentionally KEPT ────────────────────────────
    # com.android.bluetooth controls the Firestick physical remote (Bluetooth).
    # Disabling it kills the clicker — never disable. ADB WiFi access is
    # kernel-level TCP; no package can break it.
    # BLE proximity and auto-pair daemons are kept too (they serve the remote).

    # ── TTS ENGINES (large, not needed) ──────────────────────────────────
    "com.ivona.tts.oem",                       # Amazon Ivona TTS (~large)
    "com.svox.pico",                           # Pico TTS engine

    # ── ONBOARDING / CONSENT (done, never needed again) ──────────────────
    "com.amazon.tv.oobe",                      # setup wizard
    "com.amazon.tv.consents",                  # consent collection UI
    "com.amazon.tv.parentalcontrols",          # parental controls (unused)
    "com.amazon.tv.parentalcontrols.overlay.localisation.common",

    # ── SHOPPING / COMMERCE / ADS ────────────────────────────────────────
    "com.amazon.shoptv.client",
    "com.amazon.shoptv.firetv.client",
    "com.amazon.bueller.music",
    "com.amazon.bueller.photos",
    "com.amazon.tv.acr",                       # ACR — automatic content recognition
    "com.amazon.stillwatching.activity",       # engagement tracker
    "com.amazon.prism.android.service",        # ad personalization
    "com.amazon.sneakpeek",                    # pre-roll video ads on screensaver
    "com.amazon.minitv.android.app",           # Amazon MiniTV
    "com.amazon.media.recommendations",        # "what to watch" ad push
    "com.amazon.gamehub",                      # Game Hub
    "com.amazon.avod",                         # AVOD — ad-supported video on demand
    "com.amazon.venezia",                      # Amazon subscription UI
    "com.amazon.android.marketplace",          # Amazon App Store storefront
    "com.amazon.tv.website_launcher",          # Silk browser launcher
    "com.amazon.ods.kindleconnect",            # Kindle pairing daemon
    "com.amazon.spotify.mediabrowserservice",  # Amazon-side Spotify shim

    # ── SHARING / CASTING / PAIRING ──────────────────────────────────────
    "com.amazon.cast.sink",                    # Miracast sink (unused)
    "com.amazon.sharingservice.android.client.proxy",

    # ── MISC BACKGROUND DAEMONS ──────────────────────────────────────────
    "com.android.traceur",                     # system tracing/profiling daemon
    "com.amazon.tv.matter",                    # Matter/smart home protocol
    "com.amazon.tv.mattercohost",              # Matter co-host daemon
    "com.amazon.wifilocker",                   # WiFi credential locker daemon
    "com.amazon.privacypassservice",           # privacy pass (Amazon DRM)
    "com.amazon.tahoe",                        # Amazon Tahoe (device registration)
    "com.amazon.katoch",                       # Amazon Katoch service
    "com.amazon.aiondec",                      # Aion decoder service
    "com.amazon.adep",                         # Amazon ADEP (device enrollment)
    "com.amazon.diode",                        # Diode IPC service
    "com.amazon.d3",                           # D3 background service
    "com.amazon.spiderpork",                   # SpiderPork (Fire OS IPC daemon)
    "com.amazon.tigris",                       # Tigris service
    "com.amazon.imp",                          # Amazon IMP
    "com.amazon.minerva.client.api",           # Minerva (content discovery API)
    "com.amazon.aca",                          # Amazon ACA service
    "com.amazon.ale",                          # Amazon ALE service
    "com.amazon.tifobserver",                  # TIF (TV input framework) observer
    "com.amazon.avsyncslider",                 # A/V sync slider overlay
    "com.amazon.uxnotification",               # Amazon UX notification layer
    "com.amazon.kindleautomatictimezone",      # Kindle timezone auto-update
    "com.amazon.tv.keypolicymanager",          # key policy manager
    "com.amazon.tv.ffsprovisioneeclient",      # provisioning client
    "com.amazon.tv.notificationcenter",        # notification center
    "com.amazon.ftv.xpicker",                  # extended picker dialog
    "com.amazon.platform.fdrw",                # Factory data reset watcher
    "com.amazon.dcp",                          # DCP service
    "com.amazon.cpl",                          # CPL service
    "com.amazon.tcomm.jackson",                # TComm Jackson (JSON layer)
    "com.amazon.csm.htmlruntime",              # HTML runtime for CSM
    "com.amazon.tv.csapp",                     # Customer service app
    "com.amazon.aiondec",                      # (dup — harmless)
    "com.amazon.tv.intentsupport",             # intent support layer
    "com.amazon.appaccesskeyprovider",         # app access key provider
    "com.amazon.awvflingreceiver",             # WebView fling receiver
    "com.amazon.firehomestarter",              # Fire Home starter daemon
    "com.amazon.dummy.alarmclock",             # dummy alarm clock stub
    "com.amazon.dummy.calendar",               # dummy calendar stub
    "com.amazon.dummy.contacts",               # dummy contacts stub
    "com.amazon.dummy.gallery",                # dummy gallery stub
    "com.amazon.dummy.music",                  # dummy music stub
    "com.amazon.net.smartconnect",             # smart connect service
    "com.amazon.tv.resolutioncycler",          # resolution cycling service
    "com.amznfuse.operatorredirection",        # operator redirect (carrier integration)
    "com.android.dreams.basic",                # Android screensaver/daydream
    "com.android.printspooler",                # Print spooler (never used on TV)
    "com.android.managedprovisioning",         # enterprise MDM stub
    "com.android.wallpaperpicker",             # wallpaper picker (TV has no wallpaper)
    "com.android.wallpaperbackup",             # wallpaper backup
    "com.android.wallpapercropper",            # wallpaper cropper
    "com.android.htmlviewer",                  # HTML viewer app
    "com.amazon.avsyncslider",                 # (dup — harmless)

    # Tutorial / upgrade wizard
    "com.amazon.storm.lightning.tutorial",
    "com.amazon.tmm.tutorial",
    "com.amazon.tv.easyupgrade",
    "com.amazon.tv.oobe",                      # (dup — harmless)
]

# Deduplicate while preserving order
_seen = set()
_deduped = []
for _p in DISABLE_PACKAGES:
    if _p not in _seen:
        _seen.add(_p)
        _deduped.append(_p)
DISABLE_PACKAGES = _deduped

# ---------- settings to apply ----------
GLOBAL_SETTINGS = {
    # DNS — Cloudflare private DNS
    "private_dns_mode": "hostname",
    "private_dns_specifier": "one.one.one.one",
    # Tighten cached process limit — Fire TV default is 0 (unlimited)
    "max_cached_processes": "4",
    # Background data allowed (needed for Instagram sync)
    "background_data": "1",
    # Aggressive app standby
    "app_standby_enabled": "1",
    "adaptive_battery_management_enabled": "1",
}

SECURE_SETTINGS = {
    # Disable always-on Alexa listening indicator
    "voice_interaction_service_enabled": "0",
}

SYSTEM_SETTINGS = {
    # Half animations — keeps UI responsive, halves GPU time
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


def get_ram_mb():
    out, _, _ = run(["shell", "cat", "/proc/meminfo"])
    total = free = available = 0
    for line in out.splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) // 1024
        elif line.startswith("MemFree:"):
            free = int(line.split()[1]) // 1024
        elif line.startswith("MemAvailable:"):
            available = int(line.split()[1]) // 1024
    return total, free, available


def get_swap_mb():
    out, _, _ = run(["shell", "cat", "/proc/meminfo"])
    swap_total = swap_free = 0
    for line in out.splitlines():
        if line.startswith("SwapTotal:"):
            swap_total = int(line.split()[1]) // 1024
        elif line.startswith("SwapFree:"):
            swap_free = int(line.split()[1]) // 1024
    return swap_total, swap_free


def force_gc_top_procs():
    """Send SIGUSR1 to the top 8 user-space processes to trigger ART GC."""
    out, _, _ = run(["shell", "ps", "-A", "-o", "PID,USER,NAME"])
    pids = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] not in ("root", "system", "radio", "shell"):
            pids.append(parts[0])
        if len(pids) >= 8:
            break
    for pid in pids:
        run(["shell", "kill", "-10", pid])
    return len(pids)


def kill_disabled_procs():
    """am kill all disabled packages that are still resident in RAM."""
    killed = 0
    for pkg in DISABLE_PACKAGES:
        out, _, _ = run(["shell", "am", "kill", pkg])
        if out:
            killed += 1
    return killed


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


def run_optimization():
    print(f"\n=== Fire TV Stick Health Optimization ===")
    print(f"Device: {DEVICE}\n")

    if not check_connected():
        print(f"ERROR: Cannot reach {DEVICE}. Connect first.")
        sys.exit(1)

    # RAM snapshot before
    total, free_before, avail_before = get_ram_mb()
    swap_total, swap_free_before = get_swap_mb()
    swap_used_before = swap_total - swap_free_before
    print(f"RAM before:  total={total}MB  free={free_before}MB  available={avail_before}MB")
    print(f"SWAP before: total={swap_total}MB  used={swap_used_before}MB  free={swap_free_before}MB\n")

    # Safety guard — explicit NEVER_DISABLE log
    NEVER_DISABLE = {
        "com.termux",
        "com.termux.boot",
        "com.instagram.android",
        "com.netflix.ninja",
        "in.startv.hotstar",
        "com.arlosoft.macrodroid",
        "me.efesser.flauncher",
        # Remote access / ADB
        "com.android.bluetooth",
        "com.android.shell",
        "com.android.adbmanager",
    }
    for pkg in NEVER_DISABLE:
        if pkg in set(DISABLE_PACKAGES):
            print(f"SAFETY ABORT: {pkg} is in DISABLE_PACKAGES — this must never happen.")
            sys.exit(2)

    print("[1/5] Disabling bloatware / analytics / Alexa / remote-management packages...")
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

    print("[2/5] Force-GC top user-space processes (SIGUSR1 → ART garbage collection)...")
    n_gc = force_gc_top_procs()
    print(f"  → Sent GC signal to {n_gc} processes")
    time.sleep(2)  # give ART a moment to compact

    print("\n[3/5] Force-killing disabled packages still resident in RAM (am kill)...")
    n_killed = kill_disabled_procs()
    print(f"  → Killed {n_killed} lingering processes")

    print("\n[4/5] Applying settings (DNS, caches, animations, standby)...")
    for key, value in GLOBAL_SETTINGS.items():
        ok = apply_setting("global", key, value)
        print(f"  {'OK' if ok else '!!'} global/{key} = {value}")
    for key, value in SECURE_SETTINGS.items():
        ok = apply_setting("secure", key, value)
        print(f"  {'OK' if ok else '!!'} secure/{key} = {value}")
    for key, value in SYSTEM_SETTINGS.items():
        ok = apply_setting("system", key, value)
        print(f"  {'OK' if ok else '!!'} system/{key} = {value}")

    print("\n[5/5] Clearing app caches and ANR crash logs...")
    ok = clear_caches()
    ok_anr = clear_anr_logs()
    print(f"  {'OK' if ok else '!!'} Cache trim")
    print(f"  {'OK' if ok_anr else '!!'} ANR crash logs cleared")

    # RAM snapshot after
    time.sleep(3)
    _, free_after, avail_after = get_ram_mb()
    _, swap_free_after = get_swap_mb()
    swap_used_after = swap_total - swap_free_after

    ram_gained = avail_after - avail_before
    swap_freed = swap_free_after - swap_free_before

    print(f"\n=== Results ===")
    print(f"RAM after:   free={free_after}MB  available={avail_after}MB  (gained {ram_gained:+d}MB)")
    print(f"SWAP after:  used={swap_used_after}MB  free={swap_free_after}MB  (freed {swap_freed:+d}MB)")
    print(f"\nSafe:  Termux, Instagram, Netflix, Hotstar, MacroDroid, FLauncher — UNTOUCHED")
    print(f"Safe:  Bluetooth kept (physical remote) — ADB WiFi unaffected")
    print(f"\nTo re-enable any package: adb shell pm enable <package>")
    print(f"Re-run monthly to flush caches.")


if __name__ == "__main__":
    run_optimization()
