import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

url = "https://www.vlr.gg/team/18300"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

# Get the first match link
match_link = None
for a in soup.find_all('a', href=True):
    href = a['href']
    parts = href.split('/')
    if len(parts) >= 3 and parts[1].isdigit() and '-vs-' in parts[2]:
        match_link = a
        break

if match_link:
    print(f"Match Link URL: {match_link['href']}")
    print("\nAll child elements structure:")
    for child in match_link.find_all(True):
        class_name = child.get('class', [])
        text = child.get_text(strip=True)
        if text:
            print(f"Tag: <{child.name}> Class: {class_name} Text: '{text}'")
else:
    print("No match link found.")
