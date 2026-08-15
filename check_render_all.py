import sys
import httpx
sys.stdout.reconfigure(encoding='utf-8')

res = httpx.get("https://vlr-web-analyzer.onrender.com/api/matches", timeout=15.0)
matches = res.json()
print(f"Total: {len(matches)}")
for m in matches:
    print(f"[{m.get('region')}] [{m.get('tier')}] {m.get('team_a')} vs {m.get('team_b')} | {m.get('event')}")
