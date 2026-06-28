import sys
import urllib.parse
import requests
import re
from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).parents[2]))
from ai_writer import _run
from extractor import HEADERS

def scrape_instagram_profile_via_google(handle: str) -> dict:
    print(f"Scraping IG profile via Google for: {handle}")
    query = f"{handle} instagram bio followers"
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            print("Google search request failed.")
            return {}
        html = r.text
    except Exception as e:
        print(f"Error fetching: {e}")
        return {}
        
    soup = BeautifulSoup(html, "lxml")
    
    # Strip unnecessary parts to keep text clean and short
    for script in soup(["script", "style", "header", "footer", "nav"]):
        script.decompose()
        
    text_content = soup.get_text(separator="\n")
    # Clean up empty lines
    lines = [l.strip() for l in text_content.split("\n") if l.strip()]
    cleaned_text = "\n".join(lines)[:4000] # Limit to 4000 chars
    
    prompt = f"""Analyze the following Google Search results for the Instagram handle "{handle}".
Extract the person's real display name, their Instagram bio (about description), their followers count, and their niche/category (e.g. Gaming Creator, Fitness Influencer, Food Blogger, Travel Creator, Business/Agency, etc.).

Google Search Results:
{cleaned_text}

Provide your output exactly in this format:
Name: <extracted display name>
Bio: <extracted bio or about description>
Category: <niche category>
Followers: <followers count, e.g. 1883 or 1.8K>
"""

    res = _run(prompt)
    print("\n--- Gemini Output ---")
    print(res)
    print("---------------------\n")
    
    info = {
        "name": handle.capitalize(),
        "instagram": handle,
        "category": "Instagram Creator",
        "bio": f"Instagram profile for @{handle}",
        "profile_pic": "",
        "followers": "N/A",
        "following": "N/A",
        "posts": "N/A"
    }
    
    for line in res.split("\n"):
        if line.startswith("Name:"):
            info["name"] = line.replace("Name:", "").strip()
        elif line.startswith("Bio:"):
            info["bio"] = line.replace("Bio:", "").strip()
        elif line.startswith("Category:"):
            info["category"] = line.replace("Category:", "").strip()
        elif line.startswith("Followers:"):
            info["followers"] = line.replace("Followers:", "").strip()
            
    return info

if __name__ == "__main__":
    info = scrape_instagram_profile_via_google("pswithaj")
    print("Final Extracted Dict:")
    print(info)
