import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo_generator import generate_demo_html
from ai_writer import generate_all

def test_lead_generation(business_id, name, category, pitch_type, expected_template, expected_has_demo):
    lead = {
        "id": business_id,
        "name": name,
        "category": category,
        "pitch_type": pitch_type,
        "email": "test@example.com"
    }
    
    # Test template rendering and selection
    # We pass empty website_data to simulate basic scraping
    scraped = {
        "title": name,
        "description": "Premium service provider.",
        "og_image": "",
        "about_text": "We are a top-tier provider.",
        "services": ["Service A", "Service B"],
        "images": [],
        "accent_color": "",
        "hero_text": "",
        "tagline": ""
    }
    
    html = generate_demo_html(lead, scraped)
    
    # Check if the generated HTML has the specific signature or titles
    assert html is not None, "Failed to generate HTML"
    
    # Test if it resolved to the right template
    # Let's inspect the resolved template name by mock or printing
    # In demo_generator, we can search for identifiers in the HTML
    has_treeservice = "Professional Tree Care & Emergency Removal" in html
    has_detailing = "Premium Auto Detailing & Ceramic Coating" in html
    has_cleaning = "Premium Commercial Cleaning & Janitorial" in html
    
    resolved = None
    if has_treeservice: resolved = "treeservice.html"
    elif has_detailing: resolved = "detailing.html"
    elif has_cleaning: resolved = "cleaning.html"
    
    print(f"Lead: {name} ({category}) -> Resolved: {resolved} (Expected: {expected_template})")
    assert resolved == expected_template, f"Expected template {expected_template}, but got something else."
    
    # Test draft generation to check if demo_url is correctly overridden
    demo_url_input = "https://demo.leadflow.com/xyz"
    drafts = generate_all(lead, demo_url=demo_url_input, channels=None, scraped=scraped)
    
    # The email/message drafts should NOT contain demo_url if contractor
    email_draft = drafts.get("email", "")
    has_demo = demo_url_input in email_draft
    
    print(f"  Demo URL Input: {demo_url_input}")
    print(f"  Demo URL in Draft: {has_demo} (Expected: {expected_has_demo})")
    assert has_demo == expected_has_demo, f"Expected has_demo={expected_has_demo}, but got {has_demo}"
    print("  [PASS]\n")

if __name__ == "__main__":
    print("Running Template and Contractor Filter Tests...")
    
    # 1. Commercial Cleaning (Should resolve to cleaning.html, and SHOULD allow demo URL)
    test_lead_generation(
        business_id=1001,
        name="Apex Janitorial Services",
        category="Commercial Cleaning",
        pitch_type="leadflow_saas",
        expected_template="cleaning.html",
        expected_has_demo=True
    )
    
    # 2. Auto Detailing (Should resolve to detailing.html, but SHOULD NOT allow demo URL as a contractor)
    test_lead_generation(
        business_id=1002,
        name="Velocity Ceramic Detailing",
        category="Auto Detailing Studio",
        pitch_type="leadflow_saas",
        expected_template="detailing.html",
        expected_has_demo=False
    )
    
    # 3. Tree Service (Should resolve to treeservice.html, but SHOULD NOT allow demo URL as a contractor)
    test_lead_generation(
        business_id=1003,
        name="Timberline Arborists",
        category="Tree Service & Removal",
        pitch_type="leadflow_saas",
        expected_template="treeservice.html",
        expected_has_demo=False
    )
    
    print("All tests passed successfully!")
