import scraper
import sys

sys.stdout.reconfigure(encoding='utf-8')

team_a_id = "1120"
team_b_id = "731"

print(f"Fetching events for Team A ({team_a_id})...")
events_a = scraper.get_team_events(team_a_id)
print(f"Events A count: {len(events_a)}")
for e in events_a[:5]:
    print(f"  ID: {e['id']}, Name: {e['name']}")

print(f"\nFetching events for Team B ({team_b_id})...")
events_b = scraper.get_team_events(team_b_id)
print(f"Events B count: {len(events_b)}")
for e in events_b[:5]:
    print(f"  ID: {e['id']}, Name: {e['name']}")
