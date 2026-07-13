import scraper
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Team Liquid (ID: 474)
maps = scraper.get_team_maps_stats("474")
print(json.dumps(maps, indent=2, ensure_ascii=False))
