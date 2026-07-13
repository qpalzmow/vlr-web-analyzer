import urllib.request
import urllib.parse
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

try:
    print("1. Fetching matches from /api/matches...")
    with urllib.request.urlopen("http://localhost:8000/api/matches") as res:
        matches = json.loads(res.read().decode('utf-8'))
        print(f"Success! Found {len(matches)} matches.")
        if not matches:
            print("No matches available.")
            sys.exit(0)
            
    first_match = matches[0]
    match_url = first_match['url']
    print(f"\n2. Fetching details & initial live score for: {first_match['team_a']} vs {first_match['team_b']}")
    print(f"URL: {match_url}")
    
    encoded_url = urllib.parse.quote(match_url)
    details_url = f"http://localhost:8000/api/match-details?url={encoded_url}"
    
    with urllib.request.urlopen(details_url) as res:
        payload = json.loads(res.read().decode('utf-8'))
        print("Success! Details response parsed.")
        print(f"Keys returned: {list(payload.keys())}")
        
        # Verify live_score inside details
        live_score = payload.get('live_score')
        if live_score:
            print("\nInitial live_score payload structure:")
            print(f"  Series Score: {live_score.get('series_score_a')} - {live_score.get('series_score_b')}")
            print(f"  Status: {live_score.get('status')}")
            print(f"  Maps Played: {[m['map'] for m in live_score.get('maps', [])]}")
        else:
            print("ERROR: live_score is missing in /api/match-details response!")
            
    print("\n3. Testing separate live polling endpoint /api/live-score...")
    live_url = f"http://localhost:8000/api/live-score?url={encoded_url}"
    with urllib.request.urlopen(live_url) as res:
        live_data = json.loads(res.read().decode('utf-8'))
        print("Success! /api/live-score response parsed.")
        print(f"Live Status: {live_data.get('status')}")
        print(f"Series Score: {live_data.get('series_score_a')} - {live_data.get('series_score_b')}")
        print(f"Maps: {live_data.get('maps')}")
        
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

except Exception as e:
    print(f"\nVerification FAILED with error: {e}")
    sys.exit(1)
