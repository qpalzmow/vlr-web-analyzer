import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

team_id = "1120"
url = f"https://www.vlr.gg/team/stats/{team_id}"
res = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(res.text, 'html.parser')

print("1. Checking form parameter names in dropdown filters:")
selects = soup.find_all('select')
for s in selects:
    # Check if this select is for event
    options = s.find_all('option')
    is_event_select = any('event' in opt.get_text().lower() or opt.get('value', '').isdigit() for opt in options)
    if is_event_select:
        print(f"Select Tag: name='{s.get('name')}', class='{s.get('class')}'")
        print(f"  First 3 options: {[(opt.get('value'), opt.get_text(strip=True)) for opt in options[:3]]}")

# Let's test actual fetches with ?event= and ?event_id=
event_id = "2952" # EWC
url_event = f"https://www.vlr.gg/team/stats/{team_id}/?event={event_id}"
url_event_id = f"https://www.vlr.gg/team/stats/{team_id}/?event_id={event_id}"

for u in [url_event, url_event_id]:
    print(f"\nFetching: {u}")
    r = requests.get(u, headers=HEADERS, timeout=10)
    s_temp = BeautifulSoup(r.text, 'html.parser')
    table = s_temp.find('table', class_='mod-team-maps')
    if table:
        tbody = table.find('tbody')
        rows = tbody.find_all('tr') if tbody else []
        print(f"  Found map stats table! Rows count: {len(rows)}")
        if rows:
            print(f"  Sample row map: {rows[0].find_all('td')[0].get_text(strip=True)}")
    else:
        print("  Map stats table NOT found on this URL!")
