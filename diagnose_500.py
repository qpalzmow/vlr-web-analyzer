import scraper
import traceback

url = "https://www.vlr.gg/370584/kr-blaze-vs-looking-for-laburo-game-changers-2026-latam-south-stage-2-gf"
try:
    print("Testing match details scraping...")
    details = scraper.get_match_details(url)
    print("Scraped details:", details)
    
    print("Testing event map pool scraping...")
    if details.get("event_id"):
        pool = scraper.get_event_map_pool(details["event_id"])
        print("Map pool:", pool)
        
    print("Testing team events scraping...")
    if details.get("team_a_id"):
        events_a = scraper.get_team_events(details["team_a_id"])
        print("Team A events count:", len(events_a))
except Exception as e:
    traceback.print_exc()
