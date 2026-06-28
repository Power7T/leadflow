import sys
sys.path.append(str(Path(__file__).parents[2]))

from ai_writer import _run, SYSTEM_CONTEXT_WEB

prompt = """You are a master front-end designer and developer. Create a highly modern, premium, single-file HTML/CSS prototype landing page for an Instagram creator/business with the following profile:

Display Name: AJ | PS with AJ
Instagram Handle: @pswithaj
Category/Niche: Gaming Creator
Bio/Description: Your daily dose of gaming content.

Design Requirements:
1. Rich Aesthetics: Make the landing page feel extremely premium and stunning (wow at first glance). Use a dark-mode theme by default with elegant gradients (e.g., violet/pink/orange Instagram gradient style mixed with sleek dark backgrounds), glassmorphism, and responsive card layouts.
2. Structure:
   - Header/Navbar: Display Name, Instagram Handle link, and a Call-to-Action button.
   - Hero Section: Catchy headline tailored to their niche, bio description, followers count (if available), and a prominent CTA button (e.g. "Book Collaboration", "Join Community", or "Work With Me").
   - Offerings/Highlights: Based on their niche ("Gaming Creator") and bio ("Your daily dose of gaming content."), create 3-4 sample services or highlights. For example, if gaming: "Live Streams", "Game Reviews", "Community Events". Make the section look interactive and beautiful.
   - Profile/About Me: A clean section detailing who they are with a placeholder for their story.
   - Contact/Inquiry Form: A sleek, glassmorphic contact form.
   - Footer with copyrights and credits.
3. Code Quality:
   - Do NOT use Tailwind CSS. Use clean, raw CSS in a `<style>` tag.
   - Use Google Fonts (e.g., Inter, Outfit, or Poppins).
   - Use smooth hover transitions and micro-animations.
   - The output must be valid, complete HTML.
   - Do NOT include any markdown formatting or code blocks like ```html. Start directly with <!DOCTYPE html>.
"""

print("Calling _run...")
res = _run(prompt, system_context="You are an expert web developer. Return raw HTML/CSS only.")
print(f"Raw output length: {len(res)} characters")
print("--- Raw Output Preview (first 500 chars) ---")
print(res[:500])
print("--- Raw Output End (last 500 chars) ---")
print(res[-500:])
