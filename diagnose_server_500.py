import scraper
import traceback
import time

LIVE_SCORE_CACHE = {}

def get_cached_live_score(match_url):
    return None

url = "https://www.vlr.gg/370584/kr-blaze-vs-looking-for-laburo-game-changers-2026-latam-south-stage-2-gf"
try:
    details = scraper.get_match_details(url)
    print("1. details ok:", details)
    
    team_a_events = scraper.get_team_events(details["team_a_id"])[:12]
    print("2. team_a_events ok, count:", len(team_a_events))
    
    team_b_events = scraper.get_team_events(details["team_b_id"])[:12]
    print("3. team_b_events ok, count:", len(team_b_events))
    
    map_pool = scraper.get_event_map_pool(details.get("event_id"))
    print("4. map_pool ok:", map_pool)
    
    live_score = get_cached_live_score(url)
    print("5. live_score ok:", live_score)
    
    response_data = {
        "details": details,
        "team_a_events": team_a_events,
        "team_b_events": team_b_events,
        "map_pool": map_pool,
        "live_score": live_score
    }
    print("All ok!")
except Exception as e:
    traceback.print_exc()
