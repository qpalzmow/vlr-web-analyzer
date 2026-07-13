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

header_vs = soup.find(class_='match-header-vs')
if header_vs:
    print("--- match-header-vs HTML ---")
    print(header_vs.prettify())
    
header_note = soup.find(class_='match-header-note')
if header_note:
    print("--- match-header-note HTML ---")
    print(header_note.prettify())
