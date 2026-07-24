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

if __name__ == '__main__':
    unittest.main()
