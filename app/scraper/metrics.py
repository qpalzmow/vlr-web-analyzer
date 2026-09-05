import re
from typing import List, Dict, Any

def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r'[^a-z0-9\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def team_matches(a: str, b: str) -> bool:
    """Return True if team name a matches team name b.
    Priority:
    1) Exact string equality
    2) Long token overlap (>=4 chars)
    3) Short token word-boundary match
    """
    if not a or not b:
        return False
    norm_a = normalize_team_name(a)
    norm_b = normalize_team_name(b)
    if norm_a == norm_b:
        return True
    
    COMMON_WORDS = {'team', 'esports', 'gaming', 'club', 'the', 'and', 'pro'}
    long_tokens_a = set(t for t in norm_a.split() if len(t) >= 4 and t not in COMMON_WORDS)
    long_tokens_b = set(t for t in norm_b.split() if len(t) >= 4 and t not in COMMON_WORDS)
    if long_tokens_a and long_tokens_b:
        return bool(long_tokens_a & long_tokens_b)
    
    tokens_a = set(t for t in norm_a.split() if t not in COMMON_WORDS)
    tokens_b = set(t for t in norm_b.split() if t not in COMMON_WORDS)
    return bool(tokens_a & tokens_b)

def calculate_advanced_metrics(maps_data: dict, total_fk: int, total_fd: int, total_rounds: int, pistol_wins: int = 0, pistol_total: int = 0) -> dict:
    total_played = sum(s.get("played", 0) for s in maps_data.values())
    total_wins = sum(s.get("w", 0) for s in maps_data.values())
    map_win_rate = round((total_wins / total_played * 100), 1) if total_played > 0 else 50.0

    total_atk_won = sum(s.get("atk_won", 0) for s in maps_data.values())
    total_atk = sum(s.get("atk_total", 0) for s in maps_data.values())
    total_def_won = sum(s.get("def_won", 0) for s in maps_data.values())
    total_def = sum(s.get("def_total", 0) for s in maps_data.values())
    atk_win_rate = round((total_atk_won / total_atk * 100), 1) if total_atk > 0 else None
    def_win_rate = round((total_def_won / total_def * 100), 1) if total_def > 0 else None

    pistol_win_rate = round((pistol_wins / pistol_total * 100), 1) if pistol_total > 0 else None
    fk_fd_diff = total_fk - total_fd
    fk_fd_per_round = round(fk_fd_diff / max(total_rounds, 1), 4) if total_rounds > 0 else 0.0
    fk_fd_margin = round(fk_fd_diff / max(total_rounds, 1), 2) if total_rounds > 0 else 0.0

    return {
        "map_win_rate": map_win_rate,
        "atk_win_rate": atk_win_rate,
        "def_win_rate": def_win_rate,
        "pistol_win_rate": pistol_win_rate,
        "fk_fd_margin": fk_fd_margin,
        "fk_fd_diff": fk_fd_diff,
        "fk_fd_per_round": fk_fd_per_round,
        "total_played": total_played,
        "total_wins": total_wins,
        "total_fk": total_fk,
        "total_fd": total_fd,
        "top_compositions": []
    }

def find_ace_player_from_stats(players_stats: List[dict]) -> dict:
    valid_players = []
    for p in players_stats:
        if not p or p.get("rounds", 0) <= 0:
            continue
        rounds = p["rounds"]
        acs = p["weighted_acs"] / rounds if rounds > 0 else 0.0
        agents = sorted(p.get("agents", {}).items(), key=lambda x: x[1], reverse=True)
        agent_names = [a[0].capitalize() for a in agents[:3]] if agents else ["N/A"]
        valid_players.append({
            "nickname": p.get("name", "N/A"),
            "acs": round(acs, 1),
            "kd_margin": p.get("kills", 0) - p.get("deaths", 0),
            "agents": agent_names
        })

    if not valid_players:
        return {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]}

    return max(valid_players, key=lambda x: x["acs"])

def simulate_banpick(maps_a: dict, maps_b: dict, map_pool: list) -> dict:
    if not map_pool:
        return {"bans": [], "picks": []}
    
    def get_win_pct(maps_data, map_name):
        stats = maps_data.get(map_name, {})
        played = stats.get('played', 0)
        wins = stats.get('w', 0)
        return (wins / played * 100) if played > 0 else 50.0

    def get_smoothed_win_pct(maps_data, map_name):
        stats = maps_data.get(map_name, {})
        played = stats.get('played', 0)
        wins = stats.get('w', 0)
        return ((wins + 1) / (played + 2) * 100) if played > 0 else 50.0
    
    # Order-preserving deduplication of map pool
    available = list(dict.fromkeys(map_pool))
    bans = []
    picks = []
    
    for team_label, own_maps, opp_maps in [('Team A', maps_a, maps_b), ('Team B', maps_b, maps_a)]:
        if not available:
            break
        worst_map = None
        worst_diff = float('inf')
        for m in available:
            own_pct = get_smoothed_win_pct(own_maps, m)
            opp_pct = get_smoothed_win_pct(opp_maps, m)
            diff = own_pct - opp_pct
            if diff < worst_diff:
                worst_diff = diff
                worst_map = m
        if worst_map:
            bans.append({"map": worst_map, "team": team_label, "reason": f"Disadvantage: {worst_diff:+.1f}%"})
            available.remove(worst_map)
    
    for team_label, own_maps in [('Team A', maps_a), ('Team B', maps_b)]:
        if not available:
            break
        best_map = max(available, key=lambda m: get_smoothed_win_pct(own_maps, m))
        pct = get_win_pct(own_maps, best_map)
        picks.append({"map": best_map, "team": team_label, "win_pct": round(pct, 1)})
        available.remove(best_map)
    
    if available:
        decider = available[0]
        picks.append({"map": decider, "team": "Decider", "win_pct": 50.0})
    
    return {"bans": bans, "picks": picks}
