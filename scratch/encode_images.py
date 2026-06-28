import base64
import glob
import re

brain_dir = str(Path.home() / ".gemini-profiles")
templates_dir = str(Path(__file__).parents[2] / "demo_templates")

images = {
    "valet_laundry.html": ("hero_laundry_*.jpg", "https://images.unsplash.com/photo-1545173168-9f1947eebb7f?auto=format&fit=crop&w=2000&q=80"),
    "trash.html": ("hero_trash_*.jpg", "https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?auto=format&fit=crop&w=2000&q=80"),
    "handyman.html": ("hero_handyman_*.jpg", "https://images.unsplash.com/photo-1581141849291-1125c7b692b5?auto=format&fit=crop&w=2000&q=80"),
    "interiordesign.html": ("hero_interiordesign_*.jpg", "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?auto=format&fit=crop&w=2000&q=80")
}

for html_file, (img_pattern, old_url) in images.items():
    img_path = glob.glob(f"{brain_dir}/{img_pattern}")[0]
    with open(img_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode()
    
    data_uri = f"data:image/jpeg;base64,{b64_data}"
    
    html_path = f"{templates_dir}/{html_file}"
    with open(html_path, "r") as f:
        content = f.read()
    
    content = content.replace(old_url, data_uri)
    
    with open(html_path, "w") as f:
        f.write(content)
    
    print(f"Updated {html_file}")
