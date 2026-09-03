import pytest
from app.scraper.metrics import (
    normalize_team_name, team_matches, calculate_advanced_metrics,
    find_ace_player_from_stats, simulate_banpick
)

def test_team_matching_priority():
    # 1. Exact match
    assert team_matches("T1", "T1") is True
    # 2. Long token overlap
    assert team_matches("Paper Rex", "PRX Paper Rex") is True
    # 3. Short token word-boundary match (T1 vs T10 Esports should be False)
    assert team_matches("T1", "T10 Esports") is False
    assert team_matches("DRX", "DRX Vision Strikers") is True
    # 4. Common words should not cause false positive matches
    assert team_matches("Team A", "Team B") is False
    assert team_matches("Gen.G Esports", "T1 Esports") is False
    assert team_matches("DRX Gaming", "Paper Rex Gaming") is False

def test_calculate_advanced_metrics():
    maps_data = {
        "Ascent": {"played": 10, "w": 6, "l": 4},
        "Bind": {"played": 10, "w": 4, "l": 6}
    }
    metrics = calculate_advanced_metrics(maps_data, total_fk=120, total_fd=100, total_rounds=200)
    assert metrics["map_win_rate"] == 50.0
    assert metrics["pistol_win_rate"] is None
    assert metrics["fk_fd_diff"] == 20
    assert metrics["fk_fd_per_round"] == 0.1
    assert metrics["fk_fd_margin"] == 0.1
    assert metrics["total_played"] == 20
    assert metrics["total_wins"] == 10
    assert metrics["total_fk"] == 120
    assert metrics["total_fd"] == 100

    # With actual pistol data
    metrics_with_pistol = calculate_advanced_metrics(maps_data, 10, 10, 50, pistol_wins=8, pistol_total=10)
    assert metrics_with_pistol["pistol_win_rate"] == 80.0

def test_find_ace_player_from_stats():
    players = [
        {"name": "PlayerA", "rounds": 100, "weighted_acs": 25000.0, "kills": 90, "deaths": 60, "agents": {"jett": 100}},
        {"name": "PlayerB", "rounds": 100, "weighted_acs": 18000.0, "kills": 60, "deaths": 70, "agents": {"sova": 100}}
    ]
    ace = find_ace_player_from_stats(players)
    assert ace["nickname"] == "PlayerA"
    assert ace["acs"] == 250.0
    assert ace["kd_margin"] == 30
    assert ace["agents"] == ["Jett"]

def test_simulate_banpick():
    maps_a = {"Ascent": {"played": 10, "w": 8}, "Bind": {"played": 10, "w": 2}}
    maps_b = {"Ascent": {"played": 10, "w": 3}, "Bind": {"played": 10, "w": 7}}
    pool = ["Ascent", "Bind", "Haven"]
    res = simulate_banpick(maps_a, maps_b, pool)
    assert len(res["bans"]) == 2
    assert len(res["picks"]) == 1

def test_simulate_banpick_duplicate_pool():
    maps_a = {"Ascent": {"played": 10, "w": 8}, "Bind": {"played": 10, "w": 2}}
    maps_b = {"Ascent": {"played": 10, "w": 3}, "Bind": {"played": 10, "w": 7}}
    pool = ["Ascent", "Ascent", "Bind", "Bind", "Haven"]
    res = simulate_banpick(maps_a, maps_b, pool)
    # Ensure no map is banned or picked more than once
    all_maps = [b["map"] for b in res["bans"]] + [p["map"] for p in res["picks"]]
    assert len(all_maps) == len(set(all_maps))
