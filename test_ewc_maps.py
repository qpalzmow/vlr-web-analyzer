import scraper
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

match_url = "https://www.vlr.gg/708424/100-thieves-vs-nongshim-redforce-esports-world-cup-2026-sf"
print(f"Fetching match details for EWC match: {match_url}")

details = scraper.get_match_details(match_url)
print(f"Details parsed: {json.dumps(details, indent=2)}")

event_id = details.get("event_id")
print(f"\nDetecting map pool for Event ID {event_id}...")

map_pool = scraper.get_event_map_pool(event_id)
print(f"Scraped map pool: {map_pool}")
