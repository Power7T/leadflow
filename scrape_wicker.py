import urllib.request
from bs4 import BeautifulSoup
import urllib.parse
import sys

base_url = "https://www.wickerparkfitness.com"

def fetch_page(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read()
        return BeautifulSoup(html, 'html.parser')
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

soup = fetch_page(base_url)
if not soup:
    sys.exit(1)

# Find navigation links
links = set()
for a in soup.find_all('a', href=True):
    href = a['href']
    if href.startswith('/'):
        full_url = urllib.parse.urljoin(base_url, href)
        links.add(full_url)
    elif base_url in href:
        links.add(href)

print("Found links:", links)

pages = {}
for link in list(links)[:15]: # Limit to avoid taking too long
    print(f"\n--- Fetching {link} ---")
    page_soup = fetch_page(link)
    if page_soup:
        # Extract text, trying to avoid head and script tags
        for script in page_soup(["script", "style", "header", "footer", "nav"]):
            script.extract()
        text = page_soup.get_text(separator=' ', strip=True)
        print(text[:1000]) # Print first 1000 chars

