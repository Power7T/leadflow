import os
from pathlib import Path

base_dir = str(Path(__file__).parent.parent / "demo_templates")

# 1. accountant.html
acc_path = os.path.join(base_dir, "accountant.html")
with open(acc_path, "r") as f:
    acc = f.read()
# Note: It had {{ hero_img }} in the About section. Let's fix it to use accountant-about.jpg
acc = acc.replace('{{ hero_img }}', 'https://power7t.github.io/leadflow-demos/accountant-about.jpg')
# Also the Unsplash link
acc = acc.replace('https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=700&q=80', 'https://power7t.github.io/leadflow-demos/accountant-hero.jpg')
with open(acc_path, "w") as f:
    f.write(acc)

# 2. moving.html
mov_path = os.path.join(base_dir, "moving.html")
with open(mov_path, "r") as f:
    mov = f.read()
mov = mov.replace("url('{{ hero_img }}')", "url('https://power7t.github.io/leadflow-demos/moving-hero.jpg')")
mov = mov.replace('{{ hero_img }}', 'https://power7t.github.io/leadflow-demos/moving-about.jpg')
with open(mov_path, "w") as f:
    f.write(mov)

# 3. landscaping.html
lan_path = os.path.join(base_dir, "landscaping.html")
with open(lan_path, "r") as f:
    lan = f.read()
lan = lan.replace("url('{{ hero_img }}')", "url('https://power7t.github.io/leadflow-demos/landscaping-hero.jpg')")
lan = lan.replace('{{ hero_img }}', 'https://power7t.github.io/leadflow-demos/landscaping-about.jpg')
with open(lan_path, "w") as f:
    f.write(lan)

# 4. interiordesign.html (assuming it has no images, let's check it first)
print("Updated accountant, moving, landscaping.")
