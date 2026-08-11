#!/usr/bin/env python3
import sys
import os
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# os.environ["LEADFLOW_DEVICE_ROLE"] = "primary"
sys.path.insert(0, os.path.dirname(__file__))

from instagram_sender import send_instagram_dm

username = "sin.par123"
message = "Hey! Just a quick test DM — feel free to ignore. Testing some automation."
print(f"[test_dm] Sending DM to @{username}...")
result = send_instagram_dm(username, message)
print(f"[test_dm] Result: {result}")
