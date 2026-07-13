import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

url = "https://www.vlr.gg/matches"
print(f"Fetching {url}...")
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

match_items = soup.find_all('a', class_='match-item')
print(f"Found {len(match_items)} matches total")

live_count = 0
for item in match_items:
    # Live matches usually have class mod-live or elements like match-item-vs-team-status
    status_elem = item.find(class_='match-item-vs-team-status')
    status_text = status_elem.get_text(strip=True) if status_elem else ""
    
    # Or check score container
    score_container = item.find(class_='match-item-vs-team-score')
    score_text = score_container.get_text(strip=True) if score_container else ""
    
    # Or class contains "live"
    is_live = "live" in item.get('class', []) or "mod-live" in str(item) or "LIVE" in item.get_text()
    
    if is_live or status_text or score_text:
        live_count += 1
        print(f"\nMatch ID: {item.get('href', '').split('/')[1]}")
        print(f"Teams: {[t.get_text(strip=True) for t in item.find_all(class_='match-item-vs-team-name')]}")
        print(f"Status: '{status_text}'")
        print(f"Score: '{score_text}'")
        # Print item HTML snippet
        print(f"HTML snippet: {str(item)[:400]}")

print(f"\nFound {live_count} live or scored matches.")
