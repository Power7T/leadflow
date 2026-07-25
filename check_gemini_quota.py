import os
import json
import urllib.request
import ssl
import certifi

from dotenv import load_dotenv

load_dotenv("/Users/chandan/leadflow/.env")

keys_str = os.getenv("GEMINI_API_KEY", "")
keys = [k.strip() for k in keys_str.split(",") if k.strip()]

print(f"Testing {len(keys)} Gemini keys...")

payload = json.dumps({
    "contents": [{"parts": [{"text": "Say strictly the word 'Test'"}]}],
    "generationConfig": {"maxOutputTokens": 20, "temperature": 0.1},
}).encode()

ctx = ssl.create_default_context(cafile=certifi.where())

success = 0
exhausted = 0
suspended = 0
other_errors = 0

for i, key in enumerate(keys):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if "candidates" in data:
                print(f"Key {i+1} (...{key[-6:]}): ✅ Active/Working")
                success += 1
            else:
                print(f"Key {i+1} (...{key[-6:]}): ⚠️ Unexpected response format")
                
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        if e.code == 429:
            print(f"Key {i+1} (...{key[-6:]}): ❌ Exhausted (Quota/Rate Limit, 429)")
            exhausted += 1
        elif e.code == 400 and "API key not valid" in body:
            print(f"Key {i+1} (...{key[-6:]}): ❌ Invalid API Key")
        elif e.code == 403 and "suspended" in body.lower():
            print(f"Key {i+1} (...{key[-6:]}): ❌ Suspended (403 Forbidden - Consumer Suspended)")
            suspended += 1
        else:
            reason = "Unknown"
            try:
                err_json = json.loads(body)
                reason = err_json.get("error", {}).get("message", "Unknown reason")
            except:
                reason = str(e.code)
            print(f"Key {i+1} (...{key[-6:]}): ⚠️ Error {e.code}: {reason}")
            other_errors += 1
    except Exception as e:
        print(f"Key {i+1} (...{key[-6:]}): ⚠️ Other error: {e}")
        other_errors += 1

print(f"\nSummary: {success} Working | {exhausted} Exhausted (429) | {suspended} Suspended (403) | {other_errors} Other errors")
