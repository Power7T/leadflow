import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo_generator import generate_demo_html

lead = {
    "name": "Miami Fitness Group",
    "category": "Gym",
    "pitch_type": "leadflow_saas"
}
html = generate_demo_html(lead)
if "Claim this CRM" in html:
    print("SUCCESS: CTA Block updated correctly!")
else:
    print("FAIL: CTA Block was not updated.")
