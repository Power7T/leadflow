import os
import sys
import json

sys.path.append("/Users/chandan/leadflow")
from demo_generator import generate_demo_html

CONFIG_PATH = "/Users/chandan/leadflow/demo_templates/config.json"
PREVIEWS_DIR = "/Users/chandan/leadflow/demo_previews"

os.makedirs(PREVIEWS_DIR, exist_ok=True)

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

dummy_data = {
    "name": "Elite Premium Services",
    "category": "service",
    "city": "Austin",
    "google_rating": 5.0,
    "google_reviews": 342,
    "website": "https://example.com"
}

website_data = {
    "hero_text": "Experience the absolute best in town.",
    "about_text": "Since 2010, we have been the highest-rated local provider. We pride ourselves on luxury quality, extreme attention to detail, and unparalleled customer service.",
    "services": [
        {"title": "Premium Tier Service", "desc": "Our top-of-the-line offering."},
        {"title": "Standard Tier Service", "desc": "Highly requested everyday service."},
        {"title": "Maintenance Package", "desc": "Keep everything running smoothly."}
    ],
    "tagline": "Quality you can trust."
}

for t in config.get("templates", []):
    file_name = t["file"]
    # We assign the dummy category so the images load correctly if mapped
    dummy_data["category"] = t["niches"][0] if t["niches"] else "service"
    
    try:
        html = generate_demo_html(dummy_data, website_data=website_data)
        out_path = os.path.join(PREVIEWS_DIR, file_name)
        with open(out_path, "w", encoding="utf-8") as out_f:
            out_f.write(html)
        print(f"Generated preview for {file_name}")
    except Exception as e:
        print(f"Failed to generate {file_name}: {e}")
