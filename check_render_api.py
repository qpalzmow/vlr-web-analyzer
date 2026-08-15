import sys
import httpx
sys.stdout.reconfigure(encoding='utf-8')

try:
    res = httpx.get("https://vlr-web-analyzer.onrender.com/api/matches", timeout=15.0)
    print(f"Status Code: {res.status_code}")
    matches = res.json()
    print(f"Total matches returned from Render: {len(matches)}")
    for m in matches:
        print(f"[{m.get('region')}] [{m.get('tier')}] {m.get('team_a')} vs {m.get('team_b')} ({m.get('event')})")
except Exception as e:
    print(f"Error: {e}")
