import sys
from app.scraper.http import request_with_retry
from bs4 import BeautifulSoup
sys.stdout.reconfigure(encoding='utf-8')

# Search for Pacific event on VLR.gg/events
res = request_with_retry("https://www.vlr.gg/events")
soup = BeautifulSoup(res.text, "html.parser")
for a in soup.find_all("a", href=True):
    txt = a.get_text(strip=True)
    if "pacific" in txt.lower() or "vct" in txt.lower():
        print(f"Event: {txt} -> {a['href']}")
