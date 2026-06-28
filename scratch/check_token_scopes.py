import subprocess
import base64
import json
import urllib.request
import ssl

def get_profile_access_token(profile_num):
    keychain_path = str(Path.home() / ".gemini-profiles" / f"profile{profile_num}" / "Library" / "Keychains" / "login.keychain-db")
    cmd = ["security", "find-generic-password", "-w", "-s", "gemini", "-a", "antigravity", keychain_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = (result.stdout or "").strip()
        if not output:
            return None
        if output.startswith("go-keyring"):
            parts = output.split(":", 1)
            payload = parts[1] if len(parts) > 1 else output
        else:
            payload = output
        decoded_bytes = base64.b64decode(payload)
        data = json.loads(decoded_bytes.decode('utf-8', errors='ignore'))
        return data.get("token", {}).get("access_token")
    except Exception as e:
        return None

def check_scopes():
    token = get_profile_access_token(1)
    if not token:
        print("No token found")
        return
        
    url = f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"
    ctx = ssl._create_unverified_context()
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode())
        print("Token Info:")
        print(json.dumps(data, indent=2))
    except Exception as e:
        print("Failed to get token info:", e)

if __name__ == "__main__":
    check_scopes()
