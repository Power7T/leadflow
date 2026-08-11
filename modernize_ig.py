import re

with open("instagram_sender.py", "r") as f:
    code = f.read()

# Add import asyncio at the top
if "import asyncio" not in code:
    code = "import asyncio\n" + code

# Replace def with async def for key target functions
functions_to_async = [
    r"def is_adb_reachable\(",
    r"def adb\(",
    r"def adb_read_xml\(",
    r"def restart_android_uiautomator\(",
    r"def get_ui_coords\(",
    r"def get_screen_text_set\(",
    r"def type_text\(",
    r"def unlock_screen\(",
    r"def is_message_already_sent\(",
    r"def verify_sent_message\(",
    r"def bored_human_simulator\(",
    r"def account_warmup\(",
    r"def acquire_phone_lock\("
]

for func in functions_to_async:
    code = re.sub(func, r"async " + func.replace(r"\(", "("), code)

# Replace time.sleep with await asyncio.sleep inside async functions
code = re.sub(r"time\.sleep\(([^)]+)\)", r"await asyncio.sleep(\1)", code)

# Replace helper calls with await calls
code = re.sub(r"(?<!async )(?<!def )(?<!await )\badb\(", "await adb(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\badb_read_xml\(", "await adb_read_xml(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bget_ui_coords\(", "await get_ui_coords(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\btype_text\(", "await type_text(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bunlock_screen\(", "await unlock_screen(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bis_message_already_sent\(", "await is_message_already_sent(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bverify_sent_message\(", "await verify_sent_message(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bbored_human_simulator\(", "await bored_human_simulator(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\baccount_warmup\(", "await account_warmup(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bacquire_phone_lock\(", "await acquire_phone_lock(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\bis_adb_reachable\(", "await is_adb_reachable(", code)
code = re.sub(r"(?<!async )(?<!def )(?<!await )\brestart_android_uiautomator\(", "await restart_android_uiautomator(", code)

# 1. Update is_adb_reachable
is_adb_reachable_code = '''async def is_adb_reachable(target: str, timeout: int = 5) -> bool:
    host, _, port_str = target.partition(":")
    port = int(port_str) if port_str.isdigit() else 5555
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False'''
code = re.sub(r"async def is_adb_reachable\(target: str, timeout: int = 5\) -> bool:.*?return False", is_adb_reachable_code, code, flags=re.DOTALL)

# 2. Update adb
adb_code = '''async def adb(cmd: str) -> str:
    """Run an ADB command on the device asynchronously and return its stdout"""
    global FIRESTICK_IP
    FIRESTICK_IP = _resolve_adb_target()

    try:
        proc = await asyncio.create_subprocess_shell(
            f"adb -s {FIRESTICK_IP} {cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=45)
        return stdout.decode('utf-8', errors='ignore')
    except asyncio.TimeoutExpired:
        log.warning(f"ADB command timed out: {cmd}")
        return ""
    except Exception as e:
        log.debug(f"ADB Error on '{cmd}': {e}")
        return ""'''

code = re.sub(r"async def adb\(cmd: str\) -> str:.*?return \"\"", adb_code, code, flags=re.DOTALL)

# 3. Update adb_read_xml
adb_read_xml_code = '''async def adb_read_xml() -> str:
    """
    Dump uiautomator XML and return its full content reliably.
    On self-hosted Vivo (localhost:5555), reads via base64 to avoid 8k pipe truncation.
    """
    FIRESTICK_IP = _resolve_adb_target()

    # Strategy 1: dump to file, read back via base64 — avoids ADB shell pipe 8k truncation
    try:
        proc1 = await asyncio.create_subprocess_shell(
            f"adb -s {FIRESTICK_IP} shell uiautomator dump /sdcard/window_dump.xml",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        await asyncio.wait_for(proc1.communicate(), timeout=30)
        
        proc2 = await asyncio.create_subprocess_shell(
            f"adb -s {FIRESTICK_IP} shell base64 /sdcard/window_dump.xml",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=30)
        b64_data = stdout2.decode('ascii', errors='ignore')
        if b64_data.strip():
            import base64 as _b64
            xml_data = _b64.b64decode(b64_data.replace('\\n', '').replace('\\r', '')).decode('utf-8', errors='ignore')
            xml_stripped = xml_data.strip()
            if xml_stripped.startswith("<?xml") or xml_stripped.startswith("<hierarchy"):
                log.debug(f"[adb_read_xml] base64 read succeeded ({len(xml_data)} bytes)")
                return xml_data
            log.warning(f"[adb_read_xml] base64 returned bad XML: {repr(xml_stripped[:80])}")
    except Exception as e:
        log.warning(f"[adb_read_xml] base64 strategy failed: {e}")

    # Strategy 2: exec-out direct pipe (may truncate on some devices)
    try:
        proc3 = await asyncio.create_subprocess_shell(
            f"adb -s {FIRESTICK_IP} exec-out uiautomator dump /dev/tty",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout3, _ = await asyncio.wait_for(proc3.communicate(), timeout=30)
        xml_data = stdout3.decode('utf-8', errors='ignore')
        xml_stripped = xml_data.strip()
        if xml_stripped.startswith("<?xml") or xml_stripped.startswith("<hierarchy"):
            log.debug(f"[adb_read_xml] exec-out succeeded ({len(xml_data)} bytes)")
            return xml_data
        log.warning(f"[adb_read_xml] exec-out bad XML: {repr(xml_stripped[:80])}")
    except Exception as e:
        log.warning(f"[adb_read_xml] exec-out failed: {e}")

    return ""'''

code = re.sub(r"async def adb_read_xml\(\) -> str:.*?return \"\"", adb_read_xml_code, code, flags=re.DOTALL)

# 4. acquire_phone_lock
acquire_lock_code = '''async def acquire_phone_lock(ip: str, timeout_seconds: int = 180) -> bool:
    """Atomic lock with wait-queue and 5-minute stale lock detection to prevent deadlocks."""
    import time

    # Fast-fail if the device is not reachable — no point blocking for 180s
    if not await is_adb_reachable(ip):
        log.warning(f"[ADB] Device {ip} not reachable (TCP check failed) — skipping lock acquire.")
        return False

    start_time = time.time()
    lock_cmd = f"adb -s {ip} shell mkdir /sdcard/ig_automation_lock 2>/dev/null"

    while time.time() - start_time < timeout_seconds:
        proc = await asyncio.create_subprocess_shell(lock_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if proc.returncode == 0:
            return True  # Lock acquired successfully

        # Lock exists. Check if it's a stale lock (older than 5 mins)
        try:
            p_time = await asyncio.create_subprocess_shell(f"adb -s {ip} shell date +%s", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            p_stat = await asyncio.create_subprocess_shell(f"adb -s {ip} shell stat -c %Y /sdcard/ig_automation_lock", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out_time, _ = await p_time.communicate()
            out_stat, _ = await p_stat.communicate()
            cur_time_str = out_time.decode().strip()
            lock_time_str = out_stat.decode().strip()
            if cur_time_str.isdigit() and lock_time_str.isdigit():
                if (int(cur_time_str) - int(lock_time_str)) > 300:
                    log.warning("⚠️ STALE LOCK DETECTED: A previous script crashed. Force-clearing the lock.")
                    p_rm = await asyncio.create_subprocess_shell(f"adb -s {ip} shell rmdir /sdcard/ig_automation_lock", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    await p_rm.wait()
        except Exception:
            pass
        await asyncio.sleep(5)

    log.error(f"Timed out after {timeout_seconds}s waiting in queue for the phone lock.")
    return False'''

code = re.sub(r"async def acquire_phone_lock\(ip: str, timeout_seconds: int = 180\) -> bool:.*?return False", acquire_lock_code, code, flags=re.DOTALL)

# Update send_instagram_dm definition to send_instagram_dm_async
code = code.replace("async def send_instagram_dm(username: str, message: str) -> bool:", "async def send_instagram_dm_async(username: str, message: str) -> bool:")

# Synchronous wrapper to append
sync_wrapper = """

def send_instagram_dm(username: str, message: str) -> bool:
    \"\"\"Synchronous wrapper around send_instagram_dm_async to run inside non-async BackgroundScheduler threads cleanly.\"\"\"
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.run_until_complete(send_instagram_dm_async(username, message))
    else:
        return asyncio.run(send_instagram_dm_async(username, message))
"""
code += sync_wrapper

with open("instagram_sender.py", "w") as f:
    f.write(code)

print("instagram_sender.py modernized successfully!")
