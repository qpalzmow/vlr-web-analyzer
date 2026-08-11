from app.scraper.vlr import (
    get_matches,
    get_match_details,
    get_event_map_pool,
    get_team_events,
    get_live_score,
    get_team_form,
    get_single_team_stats_page,
    get_team_maps_stats,
    get_player_stats_page,
    get_player_stats,
    get_team_roster,
    get_team_advanced_metrics,
)
from app.scraper.parsers import clean_text, safe_int, safe_float
from app.scraper.metrics import normalize_team_name, team_matches, calculate_advanced_metrics, find_ace_player_from_stats
from app.config import ALL_KNOWN_MAPS

_normalize_team_name = normalize_team_name
_team_matches = team_matches
