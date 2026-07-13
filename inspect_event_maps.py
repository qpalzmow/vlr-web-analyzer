import requests
from bs4 import BeautifulSoup
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

event_id = "2153"
urls = [
    f"https://www.vlr.gg/event/stats/{event_id}",
    f"https://www.vlr.gg/event/stats/{event_id}/?menu=maps",
    f"https://www.vlr.gg/event/stats/{event_id}/?menu=map-stats"
]

for url in urls:
    print(f"\nFetching: {url}")
    res = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Look for table with maps or select list
    tables = soup.find_all('table')
    print(f"Found {len(tables)} tables")
    for idx, table in enumerate(tables):
        headers = [th.get_text(strip=True) for th in table.find_all('th')]
        print(f"  Table {idx} Headers: {headers}")
        
        # Check if Map is in headers
        if any('map' in h.lower() for h in headers):
            print("  -> Found MAP Table!")
            rows = table.find_all('tr')[1:5]
            for r in rows:
                print(f"    Row: {[td.get_text(strip=True) for td in r.find_all('td')]}")
