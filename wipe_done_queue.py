import requests
import os
public_url = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", "lf_sec_9e21808ccce4d37"))
headers = {"X-Secret-Token": token}
res = requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:ig_done_queue", "value": "[]"})
print("Wiped Cloudflare KV ig_done_queue:", res.status_code)
