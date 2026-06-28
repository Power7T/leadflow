import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from demo_generator import generate_demo_html
from deploy import deploy_demo
from database import get_conn, get_lead_by_id

def main():
    bids = [3217, 2967, 2965, 3218, 2966]
    print(f"Deploying live HTML demos for existing test leads: {bids}...")
    
    conn = get_conn()
    for bid in bids:
        full_lead = get_lead_by_id(bid)
        if not full_lead:
            print(f"ID {bid} not found in database. Skipping.")
            continue
        name = full_lead["name"]
        print(f"Processing ID {bid}: '{name}'")
        
        try:
            demo_html = generate_demo_html(full_lead)
            if demo_html:
                res = deploy_demo(bid, name, demo_html)
                if res.get("ok"):
                    url = res["url"]
                    conn.execute("UPDATE businesses SET visual_preview_url=?, demo_tunnel_url=? WHERE id=?", (url, url, bid))
                    print(f"  Live at: {url}")
                else:
                    print(f"  Deploy failed: {res.get('error')}")
            else:
                print("  Failed to generate demo HTML.")
        except Exception as e:
            print(f"  Error: {e}")
            
    conn.commit()
    conn.close()
    print("Done deploying test demos.")

if __name__ == "__main__":
    main()
