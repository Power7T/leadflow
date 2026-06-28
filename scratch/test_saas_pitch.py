import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_writer import generate_all

def test_saas_pitch():
    lead = {
        "id": 2001,
        "name": "Miami Beach Cleaning Co",
        "category": "Cleaning Service",
        "pitch_type": "leadflow_saas",
        "email": "owner@miamiclean.com",
        "city": "Miami",
        "gap": "Looking for local cleaning clients in Facebook groups"
    }
    
    scraped = {
        "title": "Miami Beach Cleaning Co",
        "description": "Airbnb cleaning services in Miami.",
        "og_image": "",
        "about_text": "",
        "services": ["Airbnb cleaning", "Post-construction cleaning"],
        "images": [],
        "accent_color": "",
        "hero_text": "",
        "tagline": ""
    }
    
    print("Testing outreach generation for SaaS CRM campaign...")
    drafts = generate_all(lead, demo_url="", channels=["email", "instagram"], scraped=scraped)
    
    print("\n--- Generated Email Draft ---")
    print(drafts.get("email", "N/A"))
    print("\n--- Generated Instagram DM Draft ---")
    print(drafts.get("instagram", "N/A"))
    
    email_draft = drafts.get("email", "").lower()
    instagram_draft = drafts.get("instagram", "").lower()
    
    # Assertions to ensure it pitches SaaS / CRM / LeadFlow instead of website builds
    assert "website" not in email_draft or "leadflow" in email_draft or "crm" in email_draft, \
        "Email draft seems to focus on building a website instead of SaaS CRM!"
        
    print("\n[SUCCESS] SaaS outreach generation test completed successfully!")

if __name__ == "__main__":
    test_saas_pitch()
