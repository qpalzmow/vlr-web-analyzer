import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def clean_text(text):
    if not text:
        return ""
    import re
    return re.sub(r'\s+', ' ', text).strip()

match_url = "https://www.vlr.gg/701345/kiss-vs-jft-gc-game-changers-2026-oceania-split-2-lbf"
res = requests.get(match_url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

# Get overall map score from main header
score_left = ""
score_right = ""
vs_score_container = soup.find(class_='match-header-vs-score')
if vs_score_container:
    spans = vs_score_container.find_all('span')
    score_spans = []
    for s in spans:
        cls = s.get('class', [])
        if any('match-header-vs-score-' in c for c in cls) and 'colon' not in ''.join(cls):
            score_spans.append(s)
    if len(score_spans) >= 2:
        score_left = clean_text(score_spans[0].get_text())
        score_right = clean_text(score_spans[1].get_text())

print(f"Overall Series Score: {score_left} - {score_right}")

# Get status
status_note = ""
header_note = soup.find(class_='match-header-note')
# Or search class match-header-vs-note
vs_notes = soup.find_all(class_='match-header-vs-note')
# If live, sometimes vs_note contains "live"
status_texts = [clean_text(n.get_text()) for n in vs_notes]
print(f"Header notes: {status_texts}")

print("\nParsing individual maps:")
maps_played = []
for game_div in soup.find_all(class_='vm-stats-game'):
    header = game_div.find(class_='vm-stats-game-header')
    if not header:
        continue
        
    map_name_div = header.find(class_='map')
    if map_name_div:
        map_name = clean_text(map_name_div.get_text()).replace('PICK', '').strip()
        # Clean potential double spaces or duration text
        # Duration is in div class map-duration
        duration_div = map_name_div.find(class_='map-duration')
        if duration_div:
            # strip duration text from map_name
            dur_text = clean_text(duration_div.get_text())
            map_name = map_name.replace(dur_text, '').strip()
        # Remove any digit prefix (like "1 Ascent" or "2 Pearl" if it gets merged)
        map_name = map_name.split()[-1] # Usually map name is the last word
        
        scores = header.find_all(class_='score')
        if len(scores) >= 2:
            s_a = clean_text(scores[0].get_text())
            s_b = clean_text(scores[1].get_text())
            maps_played.append({
                "map": map_name,
                "score_a": s_a,
                "score_b": s_b
            })

for m in maps_played:
    print(f"  Map: {m['map']}, Score: {m['score_a']} - {m['score_b']}")
