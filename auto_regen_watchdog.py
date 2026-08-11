#!/usr/bin/env python3
"""
Watchdog: waits for KV quota to reset, then regenerates all missing demos.
Runs in background on the phone. Self-contained — no Mac needed.
Lead list is hardcoded from Mac's DB (222 leads with numeric demo URLs).
Logs to ~/leadflow/auto_regen_watchdog.log
"""
import os
import sys
import time
import logging
import requests
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SCRIPT_DIR, "auto_regen_watchdog.log")
WORKER_URL = "https://leadflow-relay.chandango12.workers.dev"
LOCAL_SERVER = "http://127.0.0.1:8765"
POLL_INTERVAL = 300   # check every 5 min
BATCH_SLEEP = 4       # seconds between individual regen calls
DONE_FLAG = os.path.join(SCRIPT_DIR, ".regen_done")

# Hardcoded from Mac's DB — leads whose demo_tunnel_url ends in /demo/<number>
MISSING_LEADS = [
    (1348, "M&I MAIDS"),
    (1530, "805 Window Cleaning"),
    (1705, "FreshHive Cleaning Hub"),
    (1706, "Eco Window Cleaning"),
    (1707, "West Coast Vent Cleaning, Inc."),
    (2410, "Full Spectrum Solar"),
    (2507, "Polaron Solar Energy - Edmonton"),
    (2613, "NC Orchid Cleaning"),
    (2614, "Lucie's Home Services Inc."),
    (2642, "Jaybees Valet Laundry"),
    (2660, "www.BraniffHoover.com"),
    (2721, "Beyond Cleaning"),
    (2722, "King's Green Cleaning"),
    (2723, "Special Cleaning Services"),
    (2865, "Minit Maids"),
    (2880, "Moving Queensland"),
    (2912, "Reliable Heating & Cooling LLC"),
    (2913, "Home Heating Service, Inc."),
    (2914, "Springs Heating & Cooling"),
    (2915, "Furnace World"),
    (2916, "BullsEye Plumbing Heating & Air of Colorado Springs"),
    (2917, "A & A Professional Cooling and Heating"),
    (2918, "Rocky Mountain Climate Heating and Cooling"),
    (2919, "Around The Clock Heating, Air Conditioning, Plumbing & Electric"),
    (2920, "Click Heating and Air"),
    (2921, "HVAC Solutions"),
    (2922, "Calibrating Air Heating & Cooling, Inc."),
    (2923, "Signature Springs HVAC Inc."),
    (2940, "Apex Landscape Works LLC"),
    (2941, "Plumbing Dubai UAE"),
    (2942, "Eagle Drain Cleaning Drain Line Jetting Movers And Packers, , Handyman, Plumber, Electrical Services Abu Dhabi & Dubai"),
    (2943, "Allway Technical Services - AC Repair & Maintenance | Electrician | Plumber | Handyman in Abu Dhabi"),
    (2944, "Perfix General Maintenance LLC"),
    (2945, "ROYAL RAJAB TRADING COMPANY L.L.C"),
    (2946, "Iwin Electrical And Plumbing Works llc Abu Dhabi."),
    (2947, "FixPro AC Maintenance, Duct & Exhaust Cleaning, Plumbing, Sanitization, Sofa Cleaning, General Maintenance and MEP"),
    (2948, "HR Contracting and General Maintenance L.L.C"),
    (2949, "Gulf Dunes Landscape And Agriculture Services"),
    (2954, "Cool Moving Philadelphia"),
    (2955, "Helping Hands Movers"),
    (2956, "Georges Moving Cleaning Company"),
    (3001, "Domestic Air Conditioning"),
    (3002, "Atmostherm Ltd"),
    (3003, "Baynes Air Conditioning"),
    (3004, "Manchester cooling & refrigeration Ltd"),
    (3005, "Houlkair"),
    (3006, "Bespoke Climate Solutions Ltd"),
    (3007, "Air Conditioning Accessories"),
    (3008, "Kwikool Ltd"),
    (3009, "UK INAIAH HVAC TECHNOLOGY CO., LTD"),
    (3010, "HVAC ONLINE LIMITED"),
    (3011, "Refrigeration U.K Ltd"),
    (3037, "Squeegee Squad Window Cleaning: Springfield-Branson"),
    (3038, "LCS Kleen-Aire"),
    (3039, "Bee Clean Carpet & Restoration - Serving Springfield for 19 Years"),
    (3040, "Busy Bee Janitorial LLC"),
    (3041, "MovePro Moving and Storage"),
    (3042, "New Day Mover"),
    (3043, "Kraft Moving Service, INC"),
    (3044, "Here To There Movers"),
    (3045, "Mega Muscle Movers"),
    (3046, "Three Rivers Commercial Moving and Installations"),
    (3047, "Hoover The Mover"),
    (3048, "PODS Moving & Storage"),
    (3049, "North American Van Lines"),
    (3142, "Zuriclean - Cleaning Company"),
    (3143, "Clean Clean Services"),
    (3144, "Zurich-Cleaning GmbH"),
    (3145, "Cleaning24"),
    (3146, "PureClean Delgado Ponce"),
    (3147, "NW Clean GmbH"),
    (3148, "Sauberblitz Cleaning company in zurich"),
    (3149, "Batmaid Zurich"),
    (3150, "Reinigungsservice Zurich GmbH"),
    (3151, "Clean Service Scaramuzzo AG | Reinigungsfirma Zurich"),
    (3152, "Make It Clean - Profesionelle Polster und Leder Reininung"),
    (3153, "SSI Schweiz AG"),
    (3154, "AVEA Reinigungen GmbH"),
    (3170, "Sunshine Tree Trimming"),
    (3171, "Grove Tree Service & Landscaping"),
    (3172, "Miami Tree Crew"),
    (3173, "Premium Tree Service"),
    (3174, "Sam's Tree Service"),
    (3175, "Miami Stump Brothers"),
    (3176, "Jireh Tree Care LLC"),
    (3177, "Big Ron's Tree Service"),
    (3178, "Sunny Bliss Plumbing & Air"),
    (3179, "Hernandez Plumbing Co."),
    (3180, "Morata Plumbing"),
    (3181, "Miami Dade Plumbing"),
    (3182, "2 Bros Plumbing"),
    (3183, "Ez Plumbing Repair Services"),
    (3184, "SOS 24/7 Plumbing Corp | Plomero | Plomeros"),
    (3185, "AAAPLUMBINGSERVICES COM"),
    (3186, "Mr. Rooter Plumbing of North Miami Beach"),
    (3187, "AS4Less Landscaping"),
    (3188, "M.C. GENERAL LANDSCAPING, INC."),
    (3189, "PHB Landscaping & Nursery"),
    (3190, "Casaplanta Garden Center"),
    (3201, "Pinkys Moving Service"),
    (3202, "Mike's Moving, Inc."),
    (3203, "AMWAT Moving Warehousing Storage"),
    (3204, "Browning Moving & Storage"),
    (3205, "AmeriMOVE"),
    (3206, "Allied Van Lines"),
    (3207, "Community Moving & Storage"),
    (3265, "RC Air Heating & Air Conditioning Service"),
    (3266, "American Plumbing, Heating, Air & Electrical"),
    (3267, "Accurate Electric, Plumbing, Heating and Air"),
    (3291, "Brothers Worldwide Cleaning LLC"),
    (3292, "Staar Maid & House Cleaning"),
    (3293, "Beck N Call Home and Office Cleaning Services"),
    (3294, "J&K Flooring and Cleaning"),
    (3295, "Rasmussen Cleaning Service - DFW"),
    (3296, "Dallas Maids"),
    (3297, "Cornerstone Chem-Dry"),
    (3298, "Emily's Maids"),
    (3299, "Eco Green"),
    (3300, "AT Dryer Vent Cleaning"),
    (3329, "Cleaner Co"),
    (3330, "Perth Home Cleaners"),
    (3331, "Housekeeping WA"),
    (3332, "SuperPro Cleaning Services"),
    (3333, "All Buzz Cleaning Services"),
    (3334, "Nexus Kleen"),
    (3335, "Perth Cleaning Masters"),
    (3336, "ORCA Cleaning"),
    (3337, "Fresh Aroma Cleaning Services"),
    (3338, "Done & Dustd Cleaning"),
    (3339, "iClean Perth | Office & Home Cleaning Services"),
    (3352, "Sperry Tree Care Co"),
    (3353, "Tim's Tree Removal and Services"),
    (3354, "Artistic Arborist LLC"),
    (3355, "Pacific Plumbing and Rooter"),
    (3356, "Petersen Plumbing"),
    (3357, "Kevin Cohen Plumbing"),
    (3358, "Action Drain LLC-Plumbing Eugene"),
    (3359, "Ready Rooter & Chapman Plumbing"),
    (3360, "Mr. Rooter Plumbing of Eugene"),
    (3361, "Home Comfort Heating & Air Conditioning, Plumbing and Electrical"),
    (3362, "Drain Raider Rooter Services LLC"),
    (3363, "Don Lewis Plumbing Service LLC"),
    (3364, "Mayday Plumbing Co."),
    (3365, "Sniders Plumbing"),
    (3366, "Twin Rivers Plumbing"),
    (3367, "The Plumbing Works"),
    (3368, "Drainmaster Inc"),
    (3369, "Graham Landscape & Design LLC"),
    (3370, "GrassRoots Landscape Company"),
    (3371, "Terrazas Yard Maintenance & Construction LLC"),
    (3372, "All Seasons Landscape Maintenance"),
    (3373, "OregonScapes"),
    (3374, "Reese Landscapes"),
    (3375, "Eugene Landscape & Irrigation"),
    (3376, "Thompson Landscape Company"),
    (3377, "LandArc Landscaping & Design"),
    (3378, "Keystone Landscape & Design LLC"),
    (3379, "OREGON YARD CARE & CONSTRUCTION LLC. LICENSE # 16983 CCB#223760. LCB #100632"),
    (3380, "Accountants on the Go, LLC"),
    (3381, "Kernutt Stokes - Eugene Certified Public Accountants & Consultants"),
    (3382, "Isler CPA"),
    (3383, "Capstone Accounting and Tax"),
    (3384, "Jones & Roth CPAs & Business Advisors"),
    (3385, "Dorman & Dorman, CPA's"),
    (3386, "BKS CPAs"),
    (3387, "Shotola & Hale CPA's, LLC"),
    (3388, "E-T Tax Service Inc."),
    (3389, "Powers Howard Quimby LLP Certified Public Accountants"),
    (3390, "Houck Evarts & Company LLC"),
    (3391, "Liberty Tax"),
    (3392, "Donald J Sherry CPA"),
    (3393, "Accurate Bookkeeping & Tax Service"),
    (3394, "Xel Advisors"),
    (3395, "Jamey R Ritter CPA"),
    (3396, "JB CPA LLC"),
    (3397, "L. Burdick & Associates"),
    (3398, "Cascade Moving & Logistics"),
    (3399, "WDA Movers, LLC"),
    (3400, "Cross Town Movers and Storage"),
    (3401, "Elite Relocation Services"),
    (3402, "Emerald Moving Inc"),
    (3403, "Easier Moving"),
    (3404, "Skinny Wimp Moving Of Eugene"),
    (3405, "Premier Family Chiropractic -Family Chiropractor"),
    (3406, "Journey Chiropractic"),
    (3407, "The Joint Chiropractic"),
    (3409, "NuSpine Chiropractic - Overland Park"),
    (3411, "Total Care Chiropractic"),
    (3412, "The Health & Wellness Clinic"),
    (3413, "Chiro One Chiropractic & Wellness Center of Overland Park North"),
    (3414, "Genesis Health Clubs - Overland Park"),
    (3419, "KS Athletic Club - Gym in Overland Park, KS"),
    (3420, "Chiefs Fit"),
    (3421, "FIT HOUSE 24HR"),
    (3422, "Body Shop Gym - 24hrs"),
    (3424, "Goddess Maker Fitness"),
    (3425, "Orangetheory Fitness"),
    (3427, "The Brass Onion"),
    (3428, "Of Course Kitchen & Company"),
    (3430, "YaYas Euro Bistro in Overland Park"),
    (3431, "Strang Hall"),
    (3432, "Cafe Provence"),
    (3433, "Bowles Dental - Overland Park"),
    (3436, "Williams Family Dentistry"),
    (3437, "Grace Dental"),
    (3439, "Kansas City Dental Implants & Oral Surgery - Overland Park"),
    (3440, "Blue Valley Smiles"),
    (3441, "Leawood Dental"),
    (3442, "Albert Dental"),
    (3443, "Love To Smile: Complete Family & Implant Dentistry"),
    (3444, "Dentists of Overland Park"),
    (3445, "Brookridge Dentistry"),
    (3447, "HT Complete Family Dentistry"),
    (3448, "Wycliff Family Dentistry - Overland Park, KS"),
    (3449, "Prairie Park Dental Dr. Jason R. Patterson and Dr. Corey J. Hinrichs"),
    (3450, "MO's Barber"),
    (3451, "Perfect Image Barber shop"),
    (3453, "Maggie's Barbershop"),
    (3456, "Tapia Fades Barbershop & Lounge"),
    (3457, "KC Barber Co."),
    (3458, "Great American Barber Shop"),
    (3460, "Instagram Official"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog")


def load_env():
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def get_secret():
    return os.getenv("LEADFLOW_SECRET_TOKEN", "lf_sec_9e21808ccce4d37")


def kv_quota_available() -> bool:
    try:
        r = requests.post(
            f"{WORKER_URL}/api/kv",
            headers={"X-Secret-Token": get_secret()},
            json={"key": "_regen_probe", "value": str(time.time())},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 500 and "limit" in r.text.lower():
            return False
        return r.status_code < 500
    except Exception as e:
        log.warning(f"KV probe error: {e}")
        return False


def check_demo_url(bid: int) -> str:
    """Check current demo_tunnel_url from local server for this lead."""
    try:
        r = requests.get(f"{LOCAL_SERVER}/leads/{bid}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("demo_tunnel_url", "") or ""
    except Exception:
        pass
    return ""


def generate_demo(bid: int, name: str) -> bool:
    try:
        resp = requests.post(
            f"{LOCAL_SERVER}/leads/{bid}/generate",
            json={"channels": ["email"]},
            timeout=200,
        )
        if resp.status_code == 200:
            data = resp.json()
            url = data.get("demo_url", "")
            if url and "/demo/" in url and not re.search(r"/demo/\d+$", url):
                log.info(f"  [OK] {name} -> {url}")
                return True
            else:
                log.warning(f"  [WARN] {name} got no slug URL: {url!r}")
                return False
        else:
            log.error(f"  [FAIL] {name} HTTP {resp.status_code}: {resp.text[:150]}")
            return False
    except Exception as e:
        log.error(f"  [FAIL] {name}: {e}")
        return False


def load_completed_ids() -> set:
    done_path = os.path.join(SCRIPT_DIR, ".regen_completed_ids")
    if os.path.exists(done_path):
        with open(done_path) as f:
            return set(int(x.strip()) for x in f if x.strip().isdigit())
    return set()


def save_completed_id(bid: int):
    done_path = os.path.join(SCRIPT_DIR, ".regen_completed_ids")
    with open(done_path, "a") as f:
        f.write(f"{bid}\n")


def run_regen() -> bool:
    completed = load_completed_ids()
    remaining = [(bid, name) for bid, name in MISSING_LEADS if bid not in completed]

    if not remaining:
        log.info("All leads already completed!")
        return True

    log.info(f"Starting regen for {len(remaining)} remaining leads ({len(completed)} already done)...")
    ok = fail = 0

    for i, (bid, name) in enumerate(remaining, 1):
        # Re-check quota every 10 leads
        if i % 10 == 1 and i > 1:
            if not kv_quota_available():
                log.warning(f"KV quota exhausted mid-run at lead {i}. Will resume next reset.")
                return False

        log.info(f"[{i}/{len(remaining)}] {name} (id={bid})")
        if generate_demo(bid, name):
            ok += 1
            save_completed_id(bid)
        else:
            fail += 1

        if i < len(remaining):
            time.sleep(BATCH_SLEEP)

    log.info(f"Regen complete: {ok} OK, {fail} failed.")
    return fail == 0


def main():
    load_env()

    # Check if all done
    completed = load_completed_ids()
    if len(completed) >= len(MISSING_LEADS):
        log.info("All leads already completed (done flag). Exiting.")
        sys.exit(0)

    log.info("=== Auto-regen watchdog started ===")
    log.info(f"Total leads to process: {len(MISSING_LEADS)}, already done: {len(completed)}")
    log.info(f"Will poll every {POLL_INTERVAL}s until KV quota resets, then regen missing demos.")

    while True:
        completed = load_completed_ids()
        remaining_count = len(MISSING_LEADS) - len(completed)

        if remaining_count == 0:
            log.info("All demos regenerated! Watchdog done.")
            sys.exit(0)

        log.info(f"{remaining_count} leads still need demos. Checking KV quota...")

        if kv_quota_available():
            log.info("KV quota available! Starting regen...")
            success = run_regen()
            if success:
                log.info("All demos regenerated successfully.")
                sys.exit(0)
            else:
                log.info(f"Partial regen — will retry after next KV reset. Sleeping {POLL_INTERVAL}s.")
        else:
            log.info(f"KV quota still exhausted. Sleeping {POLL_INTERVAL}s...")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
