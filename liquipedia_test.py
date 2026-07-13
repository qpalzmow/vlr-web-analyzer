import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_liquipedia_map_pool(tournament_name):
    # 1. Search DuckDuckGo HTML for the Liquipedia tournament page
    query = f"site:liquipedia.net/valorant \"{tournament_name}\""
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    print(f"Searching DuckDuckGo: {url}")
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print("DDG search failed")
            return []
    except Exception as e:
        print(f"Search network error: {e}")
        return []
        
    soup = BeautifulSoup(res.text, 'html.parser')
    links = soup.find_all('a', class_='result__url', href=True)
    
    wiki_url = None
    for link in links:
        href = link['href']
        # Extract actual URL from DDG redirect if necessary
        if 'uddg=' in href:
            parsed = urllib.parse.urlparse(href)
            params = urllib.parse.parse_qs(parsed.query)
            actual_url = params.get('uddg', [None])[0]
            if actual_url and 'liquipedia.net/valorant/' in actual_url:
                wiki_url = actual_url
                break
        elif 'liquipedia.net/valorant/' in href:
            wiki_url = href
            break
            
    if not wiki_url:
        # Retry search with looser terms if exact name fails
        print("No exact page found, retrying with loose query...")
        query_loose = f"site:liquipedia.net/valorant {tournament_name}"
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query_loose)}"
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.find_all('a', class_='result__url', href=True)
        for link in links:
            href = link['href']
            if 'uddg=' in href:
                parsed = urllib.parse.urlparse(href)
                params = urllib.parse.parse_qs(parsed.query)
                actual_url = params.get('uddg', [None])[0]
                if actual_url and 'liquipedia.net/valorant/' in actual_url:
                    wiki_url = actual_url
                    break
                    
    if not wiki_url:
        print("Liquipedia URL not found.")
        return []
        
    print(f"Found Liquipedia Page: {wiki_url}")
    
    # 2. Fetch and parse Liquipedia Page
    try:
        wiki_res = requests.get(wiki_url, headers=HEADERS, timeout=10)
        if wiki_res.status_code != 200:
            print(f"Failed to fetch wiki page: {wiki_res.status_code}")
            return []
    except Exception as e:
        print(f"Wiki fetch error: {e}")
        return []
        
    wiki_soup = BeautifulSoup(wiki_res.text, 'html.parser')
    
    # Map names to search for (all known Valorant maps)
    all_known_maps = ["Ascent", "Bind", "Breeze", "Haven", "Icebox", "Lotus", "Split", "Sunset", "Abyss", "Fracture", "Pearl", "Summit"]
    detected_maps = set()
    
    # Liquipedia pages put the map pool under a specific infobox block or lists
    # We can inspect the infobox (table with class infobox-card) or divs with class map-pool
    infobox = wiki_soup.find(class_='infobox-card')
    if infobox:
        infobox_text = infobox.get_text(' ')
        # Find matches of map names in infobox (case-insensitive)
        for m in all_known_maps:
            if re.search(r'\b' + re.escape(m) + r'\b', infobox_text, re.I):
                detected_maps.add(m)
                
    # If not found in infobox, inspect map-pool templates
    # Often map pool is listed under headers containing "Map Pool"
    headers = wiki_soup.find_all(['h2', 'h3', 'h4'])
    for h in headers:
        if 'map' in h.get_text().lower() and 'pool' in h.get_text().lower():
            # Check the sibling elements for map names
            sibling = h.find_next_sibling()
            while sibling and sibling.name not in ['h2', 'h3', 'h4']:
                sibling_text = sibling.get_text(' ')
                for m in all_known_maps:
                    if re.search(r'\b' + re.escape(m) + r'\b', sibling_text, re.I):
                        detected_maps.add(m)
                sibling = sibling.find_next_sibling()
                
    # Fallback: scan whole page text for map pool sections
    if not detected_maps:
        print("Scanning whole page text for map pool patterns...")
        page_text = wiki_soup.get_text(' ')
        # Find map names that appear together in lists or lists near "map pool"
        # We can look for sections containing "Map Pool"
        for m in all_known_maps:
            if re.search(r'\b' + re.escape(m) + r'\b', page_text, re.I):
                detected_maps.add(m)
                
    return sorted(list(detected_maps))

# Test with GC Oceania Split 2
maps = get_liquipedia_map_pool("Game Changers 2026: Oceania Split 2")
print(f"Detected Maps: {maps}")
