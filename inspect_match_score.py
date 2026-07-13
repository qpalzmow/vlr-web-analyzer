import requests
from bs4 import BeautifulSoup
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

match_url = "https://www.vlr.gg/701345/kiss-vs-jft-gc-game-changers-2026-oceania-split-2-lbf"
print(f"Fetching match page: {match_url}")

res = requests.get(match_url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("\n1. Searching for score elements in the header:")

# Check match-header-vs
header_vs = soup.find(class_='match-header-vs')
if header_vs:
    print(f"Found match-header-vs: {header_vs.get_text(strip=True)}")
    # Find individual score spans
    score_left = header_vs.find(class_='match-header-vs-score-left')
    score_right = header_vs.find(class_='match-header-vs-score-right')
    if score_left and score_right:
        print(f"Map Score parsed: {score_left.get_text(strip=True)} - {score_right.get_text(strip=True)}")
        
# Check match-header-note (contains status like "LIVE" or "Final")
note = soup.find(class_='match-header-note')
if note:
    print(f"Status Note: {note.get_text(strip=True)}")

# Let's find map-specific scores
print("\n2. Searching for map scores:")
map_containers = soup.find_all(class_='vm-stats-games-game')
for idx, container in enumerate(map_containers):
    # Get map name
    map_name_elem = container.find(class_='map')
    map_name = map_name_elem.get_text(strip=True) if map_name_elem else f"Map {idx+1}"
    
    # Get scores
    score_elems = container.find_all(class_='score')
    scores = [s.get_text(strip=True) for s in score_elems]
    
    print(f"  Container {idx}: Map: {map_name}, Scores: {scores}")

# Let's check how the live round tracker is structured
# In live matches, there is a round-history container
round_history = soup.find_all(class_='vlr-round-history')
print(f"\n3. Found {len(round_history)} round history elements")
