import requests
from bs4 import BeautifulSoup
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Agents page for event 2153
url = "https://www.vlr.gg/event/agents/2153/game-changers-2024-north-america-series-3"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("1. Searching for select options (dropdown filters) on Agents page:")
selects = soup.find_all('select')
for s in selects:
    name = s.get('name', '')
    options = [opt.get_text(strip=True) for opt in s.find_all('option')]
    print(f"Select name='{name}': {options}")
    
# Let's see if we can find any map names
all_known_maps = ["Ascent", "Bind", "Breeze", "Haven", "Icebox", "Lotus", "Split", "Sunset", "Abyss", "Fracture", "Pearl", "Summit"]
page_text = soup.get_text(' ')
detected = [m for m in all_known_maps if re.search(r'\b' + re.escape(m) + r'\b', page_text, re.I)]
print(f"\n2. Detected maps on the agents page text: {detected}")
