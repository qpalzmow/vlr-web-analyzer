import scraper
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("1. Fetching matches...")
matches = scraper.get_matches()
edg_match = None
for m in matches:
    if "EDward Gaming" in m['team_a'] or "EDward Gaming" in m['team_b'] or "TYLOO" in m['team_a'] or "TYLOO" in m['team_b']:
        edg_match = m
        break

if not edg_match:
    print("EDward Gaming vs TYLOO match not found in matches list!")
    # Just print the first 5 matches to see what is available
    print("Matches available:")
    for m in matches[:5]:
        print(f"  {m['team_a']} vs {m['team_b']} ({m['url']})")
    sys.exit(0)
    
print(f"\n2. Found EDG match: {edg_match['team_a']} vs {edg_match['team_b']}")
print(f"URL: {edg_match['url']}")

print("\n3. Fetching match details...")
details = scraper.get_match_details(edg_match['url'])
print(f"Details: {json.dumps(details, indent=2)}")

team_a_id = details["team_a_id"]
team_b_id = details["team_b_id"]

print(f"\n4. Fetching Team A (ID: {team_a_id}) Form...")
form_a = scraper.get_team_form(team_a_id)
print(f"Form A: {form_a}")

print(f"\n5. Fetching Team A (ID: {team_a_id}) Maps...")
maps_a = scraper.get_team_maps_stats(team_a_id)
print(f"Maps A (keys): {list(maps_a.keys())}")

print(f"\n6. Fetching Team A (ID: {team_a_id}) Roster...")
roster_a = scraper.get_team_roster(team_a_id)
print(f"Roster A: {roster_a}")
