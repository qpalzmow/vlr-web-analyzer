import http.server
import json
import urllib.parse as urlparse
import os
import traceback
import scraper

import time
import threading

PORT = int(os.environ.get("PORT", 8000))

# Resolve public directory absolutely so the server can be safely started from anywhere.
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'public'))

LIVE_SCORE_CACHE = {} # key: match_url, value: (timestamp, data)
cache_lock = threading.Lock()
CACHE_TTL = 20          # seconds — live score TTL
CACHE_GC_INTERVAL = 60  # seconds — how often to run garbage collection
_last_gc_ts = 0.0

def get_cached_live_score(match_url):
    global _last_gc_ts
    now = time.time()
    with cache_lock:
        # Periodic full GC — prevents memory leak when traffic is low.
        if now - _last_gc_ts > CACHE_GC_INTERVAL:
            expired = [k for k, (ts, _) in LIVE_SCORE_CACHE.items() if now - ts > CACHE_GC_INTERVAL]
            for k in expired:
                del LIVE_SCORE_CACHE[k]
            _last_gc_ts = now
            
        if match_url in LIVE_SCORE_CACHE:
            ts, data = LIVE_SCORE_CACHE[match_url]
            if now - ts < CACHE_TTL:
                return data

    try:
        data = scraper.get_live_score(match_url)
    except Exception:
        data = {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    
    with cache_lock:
        LIVE_SCORE_CACHE[match_url] = (now, data)
        
    return data

def _safe_future_result(future, default):
    """Safely resolve a future, returning `default` if it raised."""
    if future is None:
        return default
    try:
        return future.result()
    except Exception:
        return default

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
                
                # Fetch recent 12 events and map pool in parallel!
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_a = executor.submit(scraper.get_team_events, details["team_a_id"]) if details.get("team_a_id") else None
                    future_b = executor.submit(scraper.get_team_events, details["team_b_id"]) if details.get("team_b_id") else None
                    future_pool = executor.submit(scraper.get_event_map_pool, details.get("event_id")) if details.get("event_id") else None
                    
                    team_a_events = _safe_future_result(future_a, [])[:12]
                    team_b_events = _safe_future_result(future_b, [])[:12]
                    map_pool = _safe_future_result(future_pool, [])
                
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
        # Map requested path to public directory (resolved absolutely at import time).
        req_path = path
        if req_path == '/' or req_path == '/index.html':
            req_path = '/index.html'
            
        # Clean and prevent traversal. Use realpath to resolve any symlinks.
        safe_path = os.path.normpath(req_path.lstrip('/'))
        # Reject any path containing backslashes or null bytes outright.
        if '\x00' in safe_path or '..' in safe_path.split(os.sep):
            self.send_response(404)
            send_cors_headers()
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return
        full_filepath = os.path.realpath(os.path.join(PUBLIC_DIR, safe_path))
        
        # Verify the file is strictly inside the public folder.
        try:
            is_sub = os.path.commonpath([PUBLIC_DIR]) == os.path.commonpath([PUBLIC_DIR, full_filepath])
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

        # 1. API: Get recent form
        elif path == '/api/analyze/form':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8'))
                
                team_a_id = body.get('team_a_id', '')
                team_b_id = body.get('team_b_id', '')
                
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_a = executor.submit(scraper.get_team_form, team_a_id) if team_a_id else None
                    future_b = executor.submit(scraper.get_team_form, team_b_id) if team_b_id else None
                    
                    form_a = _safe_future_result(future_a, [])
                    form_b = _safe_future_result(future_b, [])
                
                response_data = {
                    "form_a": form_a,
                    "form_b": form_b
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return

        # 2. API: Get map stats
        elif path == '/api/analyze/maps':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8'))
                
                team_a_id = body.get('team_a_id', '')
                team_b_id = body.get('team_b_id', '')
                event_ids = body.get('event_ids', None)
                
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_a = executor.submit(scraper.get_team_maps_stats, team_a_id, event_ids) if team_a_id else None
                    future_b = executor.submit(scraper.get_team_maps_stats, team_b_id, event_ids) if team_b_id else None
                    
                    maps_a = _safe_future_result(future_a, {})
                    maps_b = _safe_future_result(future_b, {})
                
                response_data = {
                    "maps_a": maps_a,
                    "maps_b": maps_b
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return

        # 3. API: Get ace players
        elif path == '/api/analyze/aces':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8'))
                
                team_a_id = body.get('team_a_id', '')
                team_b_id = body.get('team_b_id', '')
                event_ids = body.get('event_ids', None)
                
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_a = executor.submit(scraper.get_team_roster, team_a_id) if team_a_id else None
                    future_b = executor.submit(scraper.get_team_roster, team_b_id) if team_b_id else None
                    
                    roster_a = _safe_future_result(future_a, [])
                    roster_b = _safe_future_result(future_b, [])
                
                ace_a = self.find_ace_player(roster_a, event_ids)
                ace_b = self.find_ace_player(roster_b, event_ids)
                
                response_data = {
                    "ace_a": ace_a,
                    "ace_b": ace_b
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_response(str(e))
            return
        else:
            self.send_response(404)
            send_cors_headers()
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def find_ace_player(self, roster, event_ids):
        if not roster:
            return {
                "nickname": "N/A",
                "acs": 0.0,
                "kd_margin": 0,
                "agents": ["N/A"]
            }
            
        def get_stats_for_player(p):
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
                # Capitalize first char only, preserving the rest of the name.
                # e.g. "reyna" -> "Reyna", "ojİye" -> "Ojİye"
                def _cap(s):
                    if not s:
                        return s
                    return s[0].upper() + s[1:]
                p_data["agents"] = [_cap(x[0]) for x in p_data["agents"][:3]]
                if not p_data["agents"]:
                    p_data["agents"] = ["N/A"]
                return p_data
            except Exception:
                return None

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            players_data = list(executor.map(get_stats_for_player, roster))
            
        valid_players = [p for p in players_data if p is not None]
        if not valid_players:
            return {
                "nickname": "N/A",
                "acs": 0.0,
                "kd_margin": 0,
                "agents": ["N/A"]
            }
            
        return max(valid_players, key=lambda x: x["acs"])

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
