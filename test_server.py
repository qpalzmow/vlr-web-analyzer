import threading
import time
import urllib.request
import urllib.parse
import json
import server

def run_server():
    server.run()

# Start server in a background daemon thread
t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2) # Give server 2 seconds to start

print("Testing GET /api/matches...")
try:
    with urllib.request.urlopen("http://localhost:8000/api/matches") as res:
        data = json.loads(res.read().decode('utf-8'))
        print(f"Matches count: {len(data)}")
        if len(data) > 0:
            print("First match sample:")
            print(json.dumps(data[0], indent=2))
            
            # Use the first match url to test /api/match-details
            match_url = data[0]['url']
            print(f"\nTesting GET /api/match-details for {match_url}...")
            encoded_url = urllib.parse.quote(match_url)
            with urllib.request.urlopen(f"http://localhost:8000/api/match-details?url={encoded_url}") as det_res:
                details = json.loads(det_res.read().decode('utf-8'))
                print("Match details returned successfully!")
                print(f"Team A: {details['details']['team_a_name']} ({details['details']['team_a_id']})")
                print(f"Team B: {details['details']['team_b_name']} ({details['details']['team_b_id']})")
                print(f"Team A events count: {len(details['team_a_events'])}")
                
                # Test POST /api/analyze
                print("\nTesting POST /api/analyze...")
                payload = {
                    "team_a_id": details['details']['team_a_id'],
                    "team_b_id": details['details']['team_b_id'],
                    "event_ids": [details['team_a_events'][0]['id']] if len(details['team_a_events']) > 0 else []
                }
                req = urllib.request.Request(
                    "http://localhost:8000/api/analyze",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req) as ana_res:
                    analysis = json.loads(ana_res.read().decode('utf-8'))
                    print("Analysis completed successfully!")
                    print(f"Form A: {analysis['form_a']}")
                    print(f"Ace A Nickname: {analysis['ace_a']['nickname']}")
                    print(f"Ace A ACS: {analysis['ace_a']['acs']}")
        print("\nALL BACKEND API TESTS SUCCESSFUL!")
except Exception as e:
    print(f"TEST FAILED: {e}")
