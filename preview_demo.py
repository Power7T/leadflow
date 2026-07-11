import os
import sys

# Ensure LeadFlow is in path
sys.path.append("/Users/chandan/leadflow")

from demo_generator import generate_demo_html

# A fully populated dummy business
dummy_business = {
    "id": "preview_123",
    "name": "Apex Pest Control",
    "category": "pest control",
    "city": "Austin",
    "google_rating": 4.9,
    "google_reviews": 128,
    "website": "https://example.com",
}

website_data = {
    "hero_text": "Fast & Reliable Pest Extermination in Austin",
    "about_text": "Since 2012, Apex Pest Control has been keeping Austin homes safe from termites, rodents, and scorpions with pet-friendly, eco-safe treatments.",
    "services": [
        {"title": "Termite Control", "desc": ""},
        {"title": "Rodent Removal", "desc": ""},
        {"title": "Mosquito Spraying", "desc": ""},
        {"title": "Bed Bug Extermination", "desc": ""}
    ]
}

try:
    final_html = generate_demo_html(dummy_business, website_data=website_data)
    
    # Save the rendered HTML to a file so the user can open it
    out_path = "/Users/chandan/leadflow/scratch/demo_preview.html"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_html)
        
    print(f"Generated successfully: {out_path}")
except Exception as e:
    print(f"Error generating demo: {e}")
