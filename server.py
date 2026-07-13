import http.server
import json
import urllib.parse as urlparse
import os
import traceback
import scraper

import time
import threading

PORT = int(os.environ.get("PORT", 8000))

LIVE_SCORE_CACHE = {} # key: match_url, value: (timestamp, data)
cache_lock = threading.Lock()

def get_cached_live_score(match_url):
    now = time.time()
    with cache_lock:
        # Clear expired entries to prevent memory leaks
        expired = [k for k, (ts, _) in LIVE_SCORE_CACHE.items() if now - ts > 60]
        for k in expired:
            del LIVE_SCORE_CACHE[k]
            
        if match_url in LIVE_SCORE_CACHE:
            ts, data = LIVE_SCORE_CACHE[match_url]
            if now - ts < 20: # 20 second TTL
                return data
                
    data = scraper.get_live_score(match_url)
    
    with cache_lock:
        LIVE_SCORE_CACHE[match_url] = (now, data)
        
    return data

class VLRWebServer(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Handle CORS preflight request
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        
        # Enable CORS and disable browser caching for API requests
        def send_cors_headers():
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            
        # 1. API: Get Matches List
        if path == '/api/matches':
            try:
                matches = scraper.get_matches()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(matches, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return
            
        # 2. API: Get Match Details & Events list
        elif path == '/api/match-details':
            query = urlparse.parse_qs(parsed.query)
            match_url = query.get('url', [None])[0]
            if not match_url:
                self.send_error_response("Missing match url parameter", 400)
                return
                
            try:
                details = scraper.get_match_details(match_url)
                
                # Fetch recent 12 events for both teams
                team_a_events = scraper.get_team_events(details["team_a_id"])[:12]
                team_b_events = scraper.get_team_events(details["team_b_id"])[:12]
                
                # Fetch dynamic tournament map pool
                map_pool = scraper.get_event_map_pool(details.get("event_id"))
                
                # Fetch initial live score
                live_score = get_cached_live_score(match_url)
                
                response_data = {
                    "details": details,
                    "team_a_events": team_a_events,
                    "team_b_events": team_b_events,
                    "map_pool": map_pool,
                    "live_score": live_score
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return
            
        # 2.5 API: Get Live Score
        elif path == '/api/live-score':
            query = urlparse.parse_qs(parsed.query)
            match_url = query.get('url', [None])[0]
            if not match_url:
                self.send_error_response("Missing match url parameter", 400)
                return
                
            try:
                live_score = get_cached_live_score(match_url)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(live_score, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return

        # 3. Generic Static Files Server
        # Map requested path to public directory
        req_path = path
        if req_path == '/' or req_path == '/index.html':
            req_path = '/index.html'
            
        # Clean and prevent traversal
        safe_path = os.path.normpath(req_path.lstrip('/'))
        full_filepath = os.path.join(os.getcwd(), 'public', safe_path)
        
        # Verify the file is strictly inside the public folder
        public_dir = os.path.join(os.getcwd(), 'public')
        try:
            is_sub = os.path.commonpath([public_dir]) == os.path.commonpath([public_dir, full_filepath])
        except Exception:
            is_sub = False
            
        if is_sub and os.path.exists(full_filepath) and os.path.isfile(full_filepath):
            # Map extensions to mime types
            ext = os.path.splitext(full_filepath)[1].lower()
            mime_map = {
                '.html': 'text/html; charset=utf-8',
                '.js': 'application/javascript; charset=utf-8',
                '.css': 'text/css; charset=utf-8',
                '.ico': 'image/x-icon',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.json': 'application/json; charset=utf-8'
            }
            content_type = mime_map.get(ext, 'application/octet-stream')
            self.serve_file(full_filepath, content_type)
        else:
            self.send_response(404)
            send_cors_headers()
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        
        # Enable CORS and disable browser caching for API requests
        def send_cors_headers():
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')

        # 0. API: Log browser JS errors
        if path == '/api/log-error':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8'))
                print(f"\n>>> [BROWSER ERROR LOGGED]:\n{json.dumps(body, indent=2)}\n")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(b'{"status":"logged"}')
            except Exception as e:
                self.send_error_response(str(e))
            return

        # 1. API: Run full analysis
        elif path == '/api/analyze':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8'))
                
                team_a_id = body.get('team_a_id', '')
                team_b_id = body.get('team_b_id', '')
                event_ids = body.get('event_ids', None) # List of event IDs
                
                # Perform analysis crawling step by step
                form_a = scraper.get_team_form(team_a_id)
                form_b = scraper.get_team_form(team_b_id)
                
                maps_a = scraper.get_team_maps_stats(team_a_id, event_ids)
                maps_b = scraper.get_team_maps_stats(team_b_id, event_ids)
                
                roster_a = scraper.get_team_roster(team_a_id)
                roster_b = scraper.get_team_roster(team_b_id)
                
                # Find Ace players
                ace_a = self.find_ace_player(roster_a, event_ids)
                ace_b = self.find_ace_player(roster_b, event_ids)
                
                response_data = {
                    "form_a": form_a,
                    "form_b": form_b,
                    "maps_a": maps_a,
                    "maps_b": maps_b,
                    "ace_a": ace_a,
                    "ace_b": ace_b
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e) + "\n" + traceback.format_exc())
            return
        else:
            self.send_response(404)
            send_cors_headers()
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def find_ace_player(self, roster, event_ids):
        best_player = None
        best_acs = -1.0
        
        for p in roster:
            try:
                stats = scraper.get_player_stats(p["id"], event_ids)
                rounds = stats["rounds"]
                acs = stats["weighted_acs"] / rounds if rounds > 0 else 0.0
                
                p_data = {
                    "nickname": p["name"],
                    "acs": acs,
                    "kd_margin": stats["kills"] - stats["deaths"],
                    "agents": sorted(stats["agents"].items(), key=lambda x: x[1], reverse=True)
                }
                
                # Extract top 3 agents
                p_data["agents"] = [x[0].capitalize() for x in p_data["agents"][:3]]
                if not p_data["agents"]:
                    p_data["agents"] = ["N/A"]
                    
                if acs > best_acs:
                    best_acs = acs
                    best_player = p_data
            except Exception:
                continue
                
        if not best_player:
            return {
                "nickname": "N/A",
                "acs": 0.0,
                "kd_margin": 0,
                "agents": ["N/A"]
            }
        return best_player

    def serve_file(self, filepath, content_type):
        if not os.path.exists(filepath):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File Not Found")
            return
            
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error_response(str(e))

    def send_error_response(self, message, code=500):
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": message}, ensure_ascii=False).encode('utf-8'))
        except Exception:
            pass  # Ignore if client already closed the connection

def run():
    # Use ThreadingHTTPServer so that concurrent requests don't block the server!
    from http.server import ThreadingHTTPServer
    server_address = ('', PORT)
    httpd = ThreadingHTTPServer(server_address, VLRWebServer)
    print(f"Starting server on port {PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == '__main__':
    run()
