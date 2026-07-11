import os
import shutil
import re

BASE_DIR = "/Users/chandan/leadflow/demo_templates"

MAPPINGS = [
    {
        "new_file": "pestcontrol.html",
        "base_file": "roofer.html",
        "replacements": {
            r"Roofer": "Pest Control",
            r"Roofing": "Pest Control",
            r"Roof": "Property",
            r"roof": "property"
        }
    },
    {
        "new_file": "autorepair.html",
        "base_file": "remodeler.html",
        "replacements": {
            r"Remodeling": "Auto Repair",
            r"Remodeler": "Mechanic",
            r"Home": "Vehicle",
            r"home": "vehicle",
            r"Build": "Repair",
            r"build": "repair",
            r"Contractor": "Collision Center"
        }
    },
    {
        "new_file": "homebuilder.html",
        "base_file": "remodeler.html",
        "replacements": {
            r"Remodeling": "Custom Homes",
            r"Remodeler": "Architect",
            r"Renovation": "New Construction"
        }
    },
    {
        "new_file": "vet.html",
        "base_file": "dentist.html",
        "replacements": {
            r"Dental": "Veterinary",
            r"Dentist": "Veterinarian",
            r"Smile": "Pet",
            r"Teeth": "Animal",
            r"Patient": "Pet",
            r"patient": "pet"
        }
    },
    {
        "new_file": "wedding.html",
        "base_file": "medspa.html",
        "replacements": {
            r"Medical Spa": "Wedding Venue",
            r"Aesthetics": "Event Planning",
            r"Treatment": "Event",
            r"treatment": "event",
            r"Clinic": "Venue"
        }
    }
]

for m in MAPPINGS:
    base_path = os.path.join(BASE_DIR, m["base_file"])
    new_path = os.path.join(BASE_DIR, m["new_file"])
    
    if not os.path.exists(base_path):
        print(f"Skipping {m['new_file']}, {m['base_file']} not found.")
        continue
        
    with open(base_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    for pattern, repl in m["replacements"].items():
        content = re.sub(pattern, repl, content, flags=re.IGNORECASE)
        
    with open(new_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"Created {m['new_file']} from {m['base_file']}")
