import subprocess
import base64
import json
import urllib.request
import ssl

def get_profile_access_token(profile_num):
    keychain_path = Path.home() / ".gemini-profiles" / f"profile{profile_num}" / "Library" / "Keychains" / "login.keychain-db"
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
        print(f"Error reading token for profile {profile_num}: {e}")
        return None

def test_auth_token_image():
    token = get_profile_access_token(1)
    if not token:
        print("Failed to retrieve token")
        return
        
    print(f"Retrieved token: {token[:20]}... (length: {len(token)})")
    
    models = ["gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-3-pro-image"]
    ctx = ssl._create_unverified_context()
    
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Generate a clean high-quality square logo for a dentist clinic named 'Smile Bright', with modern teal styling."}
                    ]
                }
            ]
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            print(f"Calling {model} via Bearer token with timeout 15s...")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                response_data = json.loads(resp.read().decode('utf-8'))
            
            candidates = response_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                img_part = None
                for part in parts:
                    if "inlineData" in part and part["inlineData"].get("mimeType", "").startswith("image/"):
                        img_part = part["inlineData"]
                        break
                        
                if img_part:
                    mime = img_part["mimeType"]
                    img_bytes = base64.b64decode(img_part["data"])
                    out_file = f"scratch/test_auth_{model}.jpg"
                    with open(out_file, "wb") as f:
                        f.write(img_bytes)
                    print(f"  [SUCCESS] Generated image saved to {out_file} (Size: {len(img_bytes)} bytes)")
                    return
                else:
                    text_response = parts[0].get("text", "") if parts else ""
                    print(f"  [NO IMAGE] Returned text: {text_response[:120]}")
            else:
                print(f"  [ERROR] Response structure: {response_data}")
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "read"):
                try:
                    err_msg += " | details: " + e.read().decode().strip()
                except Exception:
                    pass
            print(f"  [FAILED] Model {model} error: {err_msg[:200]}")

if __name__ == "__main__":
    test_auth_token_image()
