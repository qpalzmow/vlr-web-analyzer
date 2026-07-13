import urllib.request
import urllib.parse
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

match_url = "https://www.vlr.gg/701039/edward-gaming-vs-tyloo-vct-2026-china-stage-2-w2"
encoded_url = urllib.parse.quote(match_url)
details_url = f"http://localhost:8000/api/match-details?url={encoded_url}"

print(f"Requesting: {details_url}")
try:
    with urllib.request.urlopen(details_url) as res:
        data = json.loads(res.read().decode('utf-8'))
        print("Success!")
        print(f"Keys: {list(data.keys())}")
        print(f"Details: {data.get('details')}")
        print(f"Team A Events count: {len(data.get('team_a_events', []))}")
        print(f"Team B Events count: {len(data.get('team_b_events', []))}")
        if data.get('team_a_events'):
            print(f"Sample Event A: {data['team_a_events'][0]}")
except Exception as e:
    print(f"Failed with error: {e}")
