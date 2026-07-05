# leadflow_control_cli.py – Simple CLI to interact with the FastAPI control layer or Cloudflare Worker

"""Usage examples:
   python leadflow_control_cli.py health                     # ping the health endpoint
   python leadflow_control_cli.py generate --tier tier1      # generate IG draft for a random Tier 1 user
   python leadflow_control_cli.py generate --username alice  # generate IG draft for specific username

Environment variables:
   LEADFLOW_API_URL – base URL of the API (default: http://127.0.0.1:8000)
   LEADFLOW_WORKER_URL – base URL of the deployed Cloudflare Worker (if you prefer that)
"""

import os
import argparse
import sys
from typing import Optional

import httpx

def get_base_url() -> str:
    # Prefer the worker URL if set, otherwise fall back to local FastAPI server
    return os.getenv("LEADFLOW_WORKER_URL") or os.getenv("LEADFLOW_API_URL", "http://127.0.0.1:8000")

def health_check() -> None:
    url = f"{get_base_url().rstrip('/')}/health"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        print("✅ Health check succeeded:")
        print(resp.json())
    except Exception as exc:
        print(f"❌ Health check failed: {exc}", file=sys.stderr)
        sys.exit(1)

def generate_ig(tier: Optional[str] = None, username: Optional[str] = None, message: Optional[str] = "Hello!") -> None:
    url = f"{get_base_url().rstrip('/')}/generate_ig"
    payload = {"message": message}
    if username:
        payload["username"] = username
    else:
        payload["tier"] = tier
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print("✅ IG draft generated:")
        print(f"Username   : {data['username']}")
        print(f"DM Link    : {data['dm_link']}")
        print(f"Profile    : {data['profile_link']}")
    except Exception as exc:
        print(f"❌ Failed to generate IG draft: {exc}", file=sys.stderr)
        sys.exit(1)

def main() -> None:
    parser = argparse.ArgumentParser(description="LeadFlow control CLI (FastAPI / Cloudflare Worker)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # health subcommand
    subparsers.add_parser("health", help="Ping the health endpoint")

    # generate subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate IG draft")
    group = gen_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tier", choices=["tier1", "tier2"], help="Select tier to pick a random username")
    group.add_argument("--username", help="Specific Instagram username (without @)")
    gen_parser.add_argument("--message", default="Hello!", help="Message text for the DM link")

    args = parser.parse_args()

    if args.command == "health":
        health_check()
    elif args.command == "generate":
        generate_ig(tier=args.tier, username=args.username, message=args.message)

if __name__ == "__main__":
    main()
