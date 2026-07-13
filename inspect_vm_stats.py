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
    print("Found vm-stats!")
    # Print the immediate children of vm-stats
    children = vm_stats.find_all(recursive=False)
    print(f"Immediate children count: {len(children)}")
    for idx, child in enumerate(children):
        print(f"  Child {idx}: Tag: {child.name}, Class: {child.get('class', [])}")
        # Print a small text snippet of the child
        print(f"    Text: {child.get_text(' ', strip=True)[:200]}")
        
    # Search for map tabs inside vm-stats
    game_selectors = vm_stats.find_all(class_='vm-stats-games')
    print(f"\nFound {len(game_selectors)} .vm-stats-games elements inside vm-stats")
    
    # Search for divs with class 'vm-stats-game'
    game_divs = vm_stats.find_all(class_='vm-stats-game')
    print(f"Found {len(game_divs)} .vm-stats-game elements inside vm-stats")
    for idx, d in enumerate(game_divs):
        print(f"  Game {idx} text: {d.get_text(' ', strip=True)[:150]}")
else:
    print("vm-stats not found.")
