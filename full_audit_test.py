import scraper
import server
import unittest
import json
import time
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

class FullSystemAuditTest(unittest.TestCase):
    def test_clean_text_and_safecasts(self):
        self.assertEqual(scraper.clean_text("  hello   world \n\t "), "hello world")
        self.assertEqual(scraper.safe_int("123"), 123)
        self.assertEqual(scraper.safe_int("abc-45"), -45)
        self.assertEqual(scraper.safe_int(None, 99), 99)
        self.assertEqual(scraper.safe_float("12.34"), 12.34)
        self.assertEqual(scraper.safe_float(None, 0.0), 0.0)

    def test_team_normalization_and_matching(self):
        n1 = scraper._normalize_team_name("T1")
        n2 = scraper._normalize_team_name("T10 Esports")
        self.assertFalse(scraper._team_matches(n1, n2))

        n3 = scraper._normalize_team_name("Paper Rex")
        n4 = scraper._normalize_team_name("PRX Paper Rex")
        self.assertTrue(scraper._team_matches(n3, n4))

    def test_get_matches(self):
        print("\n--- Auditing get_matches ---")
        matches = scraper.get_matches()
        self.assertIsInstance(matches, list)
        if matches:
            first = matches[0]
            self.assertIn("id", first)
            self.assertIn("url", first)
            self.assertIn("team_a", first)
            self.assertIn("team_b", first)
            self.assertIn("tier", first)
            print(f"Scraped {len(matches)} matches successfully. Sample: {first['team_a']} vs {first['team_b']} ({first['tier']})")

    def test_match_details_and_events(self):
        print("\n--- Auditing match_details & event_map_pool ---")
        matches = scraper.get_matches()
        if matches:
            sample_match = matches[0]
            details = scraper.get_match_details(sample_match["url"])
            self.assertIn("team_a_id", details)
            self.assertIn("team_b_id", details)
            print(f"Match Details: Team A ID={details['team_a_id']}, Team B ID={details['team_b_id']}, Event ID={details.get('event_id')}")

            if details.get("event_id"):
                pool = scraper.get_event_map_pool(details["event_id"])
                self.assertIsInstance(pool, list)
                print(f"Event Map Pool: {pool}")

    def test_empty_or_invalid_scraping_resilience(self):
        print("\n--- Auditing Error Resilience on Invalid IDs ---")
        self.assertEqual(scraper.get_event_map_pool(""), [])
        self.assertEqual(scraper.get_team_events(""), [])
        self.assertEqual(scraper.get_team_roster(""), [])
        self.assertEqual(scraper.get_team_form(""), [])
        self.assertEqual(scraper.get_team_maps_stats(""), {})
        self.assertEqual(scraper.get_player_stats(""), {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}})

        # Invalid match URL
        res = scraper.get_live_score("https://www.vlr.gg/000000/invalid-match-url")
        self.assertIn("status", res)
        self.assertIn("maps", res)

    def test_known_maps_no_agent_names(self):
        print("\n--- Auditing ALL_KNOWN_MAPS ---")
        self.assertNotIn("Gekko", scraper.ALL_KNOWN_MAPS)
        self.assertNotIn("Tejo", scraper.ALL_KNOWN_MAPS)
        self.assertIn("Ascent", scraper.ALL_KNOWN_MAPS)
        self.assertIn("Bind", scraper.ALL_KNOWN_MAPS)

    def test_unified_advanced_metrics_schema(self):
        print("\n--- Auditing Advanced Metrics Schema ---")
        empty_metrics = scraper.get_team_advanced_metrics("")
        expected_keys = {
            "map_win_rate", "pistol_win_rate", "fk_fd_margin", "fk_fd_diff",
            "fk_fd_per_round", "total_played", "total_wins", "total_fk",
            "total_fd", "top_compositions"
        }
        self.assertEqual(set(empty_metrics.keys()), expected_keys)

    def test_map_stats_aggregation(self):
        print("\n--- Auditing Map Stats Multi-Event Aggregation ---")
        from unittest.mock import patch
        sample_ev1 = {
            "Ascent": {"played": 7, "w": 5, "l": 2, "atk_won": 40, "atk_total": 70, "def_won": 45, "def_total": 75},
            "Bind": {"played": 4, "w": 2, "l": 2, "atk_won": 20, "atk_total": 40, "def_won": 20, "def_total": 40}
        }
        sample_ev2 = {
            "Ascent": {"played": 7, "w": 3, "l": 4, "atk_won": 35, "atk_total": 70, "def_won": 35, "def_total": 70},
            "Split": {"played": 3, "w": 1, "l": 2, "atk_won": 15, "atk_total": 30, "def_won": 15, "def_total": 30}
        }

        def mock_get_single_page(team_id, event_id=None):
            if event_id == "ev1":
                return sample_ev1
            if event_id == "ev2":
                return sample_ev2
            return {}

        with patch("app.scraper.vlr.get_single_team_stats_page", side_effect=mock_get_single_page):
            aggregated = scraper.get_team_maps_stats("878", ["ev1", "ev2"])
            self.assertEqual(aggregated["Ascent"]["played"], 14)
            self.assertEqual(aggregated["Ascent"]["w"], 8)
            self.assertEqual(aggregated["Ascent"]["l"], 6)
            self.assertEqual(aggregated["Bind"]["played"], 4)
            self.assertEqual(aggregated["Split"]["played"], 3)

if __name__ == '__main__':
    unittest.main()
