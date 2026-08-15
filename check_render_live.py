import sys
import httpx
sys.stdout.reconfigure(encoding='utf-8')

try:
    res = httpx.get("https://vlr-web-analyzer.onrender.com/api/matches", timeout=15.0)
    matches = res.json()
    pacific_matches = [m for m in matches if m.get('region') == 'Pacific']
    print(f"Total Matches on Render: {len(matches)} | Pacific: {len(pacific_matches)}")
    for m in pacific_matches:
        print(f" - {m.get('team_a')} vs {m.get('team_b')} ({m.get('event')})")
except Exception as e:
    print(f"Error: {e}")
