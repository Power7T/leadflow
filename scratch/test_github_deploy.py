import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from deploy import deploy_demo, is_live
from dotenv import load_dotenv

load_dotenv()

def main():
    print("Testing GitHub deployment pipeline...")
    token = os.getenv("GITHUB_TOKEN")
    print(f"Using GITHUB_TOKEN: {token[:10]}...{token[-5:] if token else ''}")
    
    # Try deploying a dummy html file
    bid = 9999
    name = "Test Business Pipeline Verification"
    html = "<html><body><h1>LeadFlow Deployment Test Success</h1></body></html>"
    
    print("Running deploy_demo...")
    res = deploy_demo(bid, name, html)
    print("Result:", res)
    
    if res["ok"]:
        url = res["url"]
        print(f"Deploy pushed to GitHub successfully! URL: {url}")
        print("Checking if live (polling)...")
        live = is_live(url, wait=30)
        print("Is Live:", live)
    else:
        print("Deploy failed:", res["error"])

if __name__ == "__main__":
    main()
