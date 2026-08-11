#!/usr/bin/env python3
"""
Regenerates and deploys demos for the 222 leads that have numeric-format
demo URLs (/demo/NNNN) and no HTML in Cloudflare KV.
Run after KV write limit resets (UTC midnight).
"""
import sys
import os
import time
import sqlite3
import re
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("regen_demos")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

DB_PATH = os.path.join(SCRIPT_DIR, "leadflow.db")
BATCH_SIZE = 50   # stop each run at 50 to stay under daily KV write limit
SLEEP_BETWEEN = 3  # seconds between API calls


def get_missing_leads():
    numeric_pattern = re.compile(r"/demo/\d+$")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name, demo_tunnel_url FROM businesses WHERE demo_tunnel_url IS NOT NULL AND demo_tunnel_url != ''").fetchall()
    conn.close()
    return [(r["id"], r["name"], r["demo_tunnel_url"]) for r in rows if numeric_pattern.search(r["demo_tunnel_url"] or "")]


def generate_and_deploy(bid: int) -> bool:
    """Calls the local server /leads/{bid}/generate endpoint."""
    try:
        resp = requests.post(
            f"http://127.0.0.1:8765/leads/{bid}/generate",
            json={"channels": ["email"]},
            timeout=200,
        )
        if resp.status_code == 200:
            data = resp.json()
            demo_url = data.get("demo_url", "")
            if demo_url and "/demo/" in demo_url and not re.search(r"/demo/\d+$", demo_url):
                log.info(f"  [OK] Demo deployed: {demo_url}")
                return True
            else:
                log.warning(f"  [WARN] Generate returned no slug URL: {demo_url!r}")
                return False
        else:
            log.error(f"  [FAIL] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        log.error(f"  [FAIL] Exception: {e}")
        return False


def main():
    missing = get_missing_leads()
    log.info(f"Found {len(missing)} leads with missing/stale demo URLs")

    if not missing:
        log.info("Nothing to do — all demos are deployed.")
        return

    to_process = missing[:BATCH_SIZE]
    log.info(f"Processing {len(to_process)} (batch of {BATCH_SIZE}) ...")

    ok = 0
    fail = 0
    kv_limit_hit = False

    for i, (bid, name, old_url) in enumerate(to_process, 1):
        log.info(f"[{i}/{len(to_process)}] Generating demo for: {name} (ID {bid})")

        # Quick pre-check: if KV is still over limit, stop early
        try:
            test = requests.post(
                "https://leadflow-relay.chandango12.workers.dev/api/kv",
                headers={"X-Secret-Token": os.getenv("LEADFLOW_SECRET_TOKEN", "")},
                json={"key": "_regen_probe", "value": "1"},
                timeout=10,
            )
            if test.status_code == 500 and "limit exceeded" in test.text:
                log.error("KV daily write limit still exceeded — stopping. Re-run after UTC midnight.")
                kv_limit_hit = True
                break
        except Exception:
            pass

        success = generate_and_deploy(bid)
        if success:
            ok += 1
        else:
            fail += 1

        if i < len(to_process):
            time.sleep(SLEEP_BETWEEN)

    remaining = len(missing) - len(to_process)
    log.info(f"Done. {ok} deployed, {fail} failed. {remaining} leads still need demos (run again tomorrow).")
    if kv_limit_hit:
        sys.exit(1)


if __name__ == "__main__":
    # Load .env
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))

    main()
