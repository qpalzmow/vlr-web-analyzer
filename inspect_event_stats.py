import requests
from bs4 import BeautifulSoup
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Event stats page for Game Changers 2026 Oceania Split 2
url = "https://www.vlr.gg/event/stats/2153"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print(f"Response status: {res.status_code}")

print("\n1. Searching for map names in event stats tables:")
# VLR event stats page has a table for maps or dropdowns
# Let's inspect all tables and cells
tables = soup.find_all('table')
print(f"Found {len(tables)} tables")

for idx, table in enumerate(tables):
    print(f"\nTable {idx}:")
    headers = [th.get_text(strip=True) for th in table.find_all('th')]
    print(f"Headers: {headers}")
    
    # Print first few rows
    rows = table.find_all('tr')[1:5]
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all('td')]
        print(f"  Row: {cells}")
