import os
import sys
import json

PORT = int(os.environ.get("PORT", 7860))

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PUBLIC_DIR = os.path.abspath(os.path.join(BASE_DIR, 'public'))
PUBLIC_DIR_NORM = os.path.normcase(os.path.normpath(PUBLIC_DIR))

# Allowed domain allowlist to prevent SSRF
ALLOWED_VLR_HOSTS = {"www.vlr.gg", "vlr.gg"}

ALL_KNOWN_MAPS = [
    "Ascent", "Bind", "Breeze", "Haven", "Icebox", "Lotus", "Split", 
    "Sunset", "Abyss", "Fracture", "Pearl", "Summit"
]

# Core VCT Partner teams (Pacific, Americas, EMEA, China) guaranteed to be pre-cached
CORE_S_TIER_TEAMS = {
    # Pacific
    '14': 'T1', '918': 'Global Esports', '17': 'Gen.G', '8185': 'DRX', '624': 'Paper Rex',
    '878': 'Rex Regum Qeon', '6199': 'Team Secret', '5448': 'ZETA DIVISION', '8304': 'Talon Esports',
    '278': 'DetonatioN FocusMe', '6387': 'Bleed Esports', '11229': 'VARREL', '13690': 'Sin Prisa Gaming',
    '11382': 'Nongshim RedForce',
    # Americas
    '2': 'Sentinels', '6961': 'LOUD', '2359': 'Leviatán', '1034': 'NRG', '5248': 'Evil Geniuses',
    '188': 'Cloud9', '120': '100 Thieves', '2355': 'KRÜ Esports', '2406': 'FURIA', '7386': 'MIBR',
    '11058': 'G2 Esports', '11040': '2Game Esports',
    # EMEA
    '2593': 'Fnatic', '474': 'Team Liquid', '4915': 'NAVI', '8877': 'Karmine Corp',
    '2059': 'Team Vitality', '1184': 'FUT Esports', '1001': 'Team Heretics', '397': 'BBL Esports',
    '7035': 'KOI', '13123': 'GIANTX', '12165': 'Gentle Mates', '478': 'Apeks',
    # China
    '1120': 'EDward Gaming', '628': 'FunPlus Phoenix', '12010': 'Bilibili Gaming', '12685': 'Trace Esports',
    '13790': 'Wolves Esports', '11981': 'Dragon Ranger Gaming', '14137': 'Titan Esports Club',
    '731': 'TYLOO', '1119': 'All Gamers', '12064': 'Nova Esports', '13576': 'JD Gaming', '13788': 'XLG Esports'
}

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def load_tier_config():
    """Load tier keywords from external config file. Falls back to hardcoded defaults."""
    config_path = os.path.join(BASE_DIR, 'tier_config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('s_tier', []), config.get('a_tier', [])
    except Exception:
        return (
            ["Champions", "Masters", "International League", "Pacific", "Americas",
             "EMEA", "CN", "World Cup", "EWC", "Championship",
             "Kickoff", "Stage 1", "Stage 2", "Playoffs", "Grand Final", "VCT", "Valorant Champions Tour"],
            ["Challengers", "Game Changers", "Academy", "Rising Stars", "Ascension"]
        )

# Multi-Tier TTL Caching Configuration
CACHE_TTLS = {
    'matches': 600,         # 10 minutes for matches list
    'match_details': 300,   # 5 minutes
    'team_events': 300,     # 5 minutes
    'event_map_pool': 600,  # 10 minutes
    'live_score': 10,       # 10 seconds for live scores
    'team_stats': 600,      # 10 minutes
    'team_roster': 600,     # 10 minutes
    'player_stats': 300,    # 5 minutes
    'pistol_stats': 300,    # 5 minutes
    'team_form': 300,       # 5 minutes
}
