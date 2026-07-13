import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

url = "https://www.vlr.gg/event/2153/game-changers-2026-oceania-split-2"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("All tournament sub-links found:")
for a in soup.find_all('a', href=True):
    href = a['href']
    text = a.get_text(strip=True)
    if '/event/' in href:
        print(f"Text: '{text}' Href: '{href}'")
