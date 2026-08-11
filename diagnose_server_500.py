import traceback
from app.scraper import vlr
from app.cache import get_cached_live_score

def diagnose():
    print("=== CLI Diagnostic Tool for VLR Web Analyzer ===")
    matches = vlr.get_matches()
    if not matches:
        print("[-] No matches returned.")
        return
    sample_match = matches[0]
    url = sample_match["url"]
    print(f"[+] Inspecting sample match: {sample_match['team_a']} vs {sample_match['team_b']}")
    
    try:
        details = vlr.get_match_details(url)
        print("  1. Match Details OK:", details)
        
        team_a_events = vlr.get_team_events(details["team_a_id"])[:12]
        print(f"  2. Team A Events OK (Count: {len(team_a_events)})")
        
        team_b_events = vlr.get_team_events(details["team_b_id"])[:12]
        print(f"  3. Team B Events OK (Count: {len(team_b_events)})")
        
        map_pool = vlr.get_event_map_pool(details.get("event_id"))
        print("  4. Event Map Pool OK:", map_pool)
        
        live_score = get_cached_live_score(url, vlr.get_live_score)
        print("  5. Live Score OK:", live_score)
        
        adv_metrics = vlr.get_team_advanced_metrics(details["team_a_id"])
        print("  6. Advanced Metrics OK:", adv_metrics)
        
        print("\n=== DIAGNOSTICS SUCCESSFUL: 0 ERRORS DETECTED ===")
    except Exception as e:
        print("\n[!] DIAGNOSTIC FAILURE AT STEP:")
        traceback.print_exc()

if __name__ == '__main__':
    diagnose()
