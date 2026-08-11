#!/usr/bin/env python3
"""
One-shot script: deletes all sync:log:XXXXX keys from Cloudflare KV
by calling the Worker's DELETE /api/sync endpoint in a loop.
Each call deletes one page (~1000 keys). Run until all cleared.
"""
import requests
import time
import os

PUBLIC_URL = "https://leadflow-relay.chandango12.workers.dev"
TOKEN = "lf_sec_9e21808ccce4d37"

total_deleted = 0
rounds = 0

while True:
    rounds += 1
    print(f"Round {rounds}: sending DELETE /api/sync ...")
    try:
        r = requests.delete(
            f"{PUBLIC_URL}/api/sync",
            headers={"X-Secret-Token": TOKEN, "Content-Length": "0"},
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            deleted = data.get("deleted", 0)
            total_deleted += deleted
            print(f"  Deleted {deleted} keys this round. Total so far: {total_deleted}")
            if deleted == 0:
                print("No more sync:log: keys found. Cleanup complete!")
                break
        else:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            print("  Retrying in 5s...")
            time.sleep(5)
    except Exception as e:
        print(f"  Error: {e}. Retrying in 5s...")
        time.sleep(5)

    time.sleep(2)

print(f"\nDone. Total keys deleted: {total_deleted}")
