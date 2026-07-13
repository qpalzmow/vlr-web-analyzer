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

vm_stats = soup.find(class_='vm-stats')
if vm_stats:
    game_divs = vm_stats.find_all(class_='vm-stats-game')
    if game_divs:
        print("--- First vm-stats-game HTML ---")
        # Print up to 1000 characters of the prettified HTML
        print(game_divs[0].prettify()[:2500])
