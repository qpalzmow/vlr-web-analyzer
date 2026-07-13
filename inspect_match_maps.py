import requests
from bs4 import BeautifulSoup
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Inspect the GC Oceania Split 2 Lower Final match
url = "https://www.vlr.gg/701345/kiss-vs-jft-gc-game-changers-2026-oceania-split-2-lbf"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("1. Map elements in the match page:")
# Typically, maps are in divs with class 'vm-stats-games' or tabs
# Let's inspect class structures containing map names
for div in soup.find_all(class_=re.compile(r'map|game|veto', re.I)):
    classes = div.get('class', [])
    text = clean_text = re.sub(r'\s+', ' ', div.get_text()).strip()
    if text and len(text) < 150:
        print(f"Tag: <{div.name}> Class: {classes} Text: '{text}'")

print("\n2. Veto / Map pool text:")
veto_container = soup.find(class_='match-header-note')
if veto_container:
    print(f"Header note: '{veto_container.get_text().strip()}'")

# Check map tabs
map_tabs = soup.find_all(class_='vm-stats-games-nav-item')
for tab in map_tabs:
    print(f"Map tab text: '{tab.get_text().strip()}'")
