import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

match_url = "https://www.vlr.gg/701345/kiss-vs-jft-gc-game-changers-2026-oceania-split-2-lbf"
res = requests.get(match_url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("1. Searching for vm-stats-games container:")
games_container = soup.find(class_='vm-stats-games')
if games_container:
    print("Found vm-stats-games!")
    for game in games_container.find_all(recursive=False):
        print(f"\nChild class: {game.get('class', [])}")
        print(game.prettify()[:500])
else:
    print("vm-stats-games NOT found.")
    # Search for anything with vm-stats
    for div in soup.find_all('div'):
        cls = div.get('class', [])
        if any('vm-stats' in c for c in cls):
            print(f"Found other stats div: {cls}")
            break
            
print("\n2. Scanning all elements containing map names (Ascent, Split, Pearl, etc.):")
for div in soup.find_all('div'):
    txt = div.get_text(strip=True)
    if txt in ['Ascent', 'Pearl', 'Breeze', 'Haven', 'Lotus', 'Split', 'Sunset']:
        print(f"Div with class {div.get('class', [])} contains map name: {txt}")
        # Print parent class
        parent = div.parent
        print(f"  Parent class: {parent.get('class', [])} -> {parent.get_text(strip=True)[:100]}")
