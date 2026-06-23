import importlib
import time
import unittest
from unittest.mock import patch


main = importlib.import_module("main")


class ScoringTests(unittest.TestCase):
    def test_calculate_pitcher_profile_penalizes_weak_pitcher(self):
        profile = main.calculate_pitcher_profile({
            "era": "5.25",
            "whip": "1.60",
            "homeRuns": "20",
            "baseOnBalls": "50",
            "strikeOuts": "80",
            "inningsPitched": "100.0",
            "hits": "115",
        })

        self.assertGreater(profile["weakness"], 30)

    def test_runner_score_rewards_scoring_position(self):
        self.assertEqual(main.runner_score({}), 0)
        self.assertEqual(main.runner_score({"second": {}}), 8)
        self.assertEqual(
            main.runner_score({"first": {}, "second": {}, "third": {}}),
            33,
        )


class CacheTests(unittest.TestCase):
    def test_cache_get_expires_old_entry(self):
        cache = {"a": (time.time() - 1, 123)}

        self.assertIsNone(main.cache_get(cache, "a"))
        self.assertNotIn("a", cache)

    def test_prune_sent_alerts_removes_old_entries(self):
        main.sent_alerts.clear()
        main.sent_alerts["old"] = {"last_time": time.time() - main.ALERT_MEMORY_SECONDS - 1}
        main.sent_alerts["fresh"] = {"last_time": time.time()}

        main.prune_sent_alerts()

        self.assertNotIn("old", main.sent_alerts)
        self.assertIn("fresh", main.sent_alerts)


class AlertThrottleTests(unittest.TestCase):
    def setUp(self):
        main.sent_alerts.clear()

    def test_should_send_alert_suppresses_duplicate(self):
        self.assertTrue(main.should_send_alert("spot", 90))
        self.assertFalse(main.should_send_alert("spot", 91))


class LiveFeedParsingTests(unittest.TestCase):
    def test_get_current_pitcher_prefers_current_play_matchup(self):
        data = {
            "liveData": {
                "plays": {
                    "currentPlay": {
                        "matchup": {
                            "pitcher": {"id": 10, "fullName": "Actual Pitcher"}
                        }
                    }
                },
                "linescore": {
                    "defense": {
                        "pitcher": {"id": 20, "fullName": "Fallback Pitcher"}
                    }
                },
            }
        }

        self.assertEqual(
            main.get_current_pitcher(data),
            {"id": 10, "name": "Actual Pitcher"},
        )

    def test_get_current_pitcher_uses_linescore_defense_fallback(self):
        data = {
            "liveData": {
                "plays": {"currentPlay": {"matchup": {}}},
                "linescore": {
                    "defense": {
                        "pitcher": {"id": 20, "fullName": "Fallback Pitcher"}
                    }
                },
            }
        }

        self.assertEqual(
            main.get_current_pitcher(data),
            {"id": 20, "name": "Fallback Pitcher"},
        )

    def test_get_batting_order_targets_looks_ahead_from_current_batter(self):
        data = {
            "liveData": {
                "linescore": {
                    "offense": {
                        "batter": {"id": 2},
                        "team": {"id": 99},
                    }
                },
                "boxscore": {
                    "teams": {
                        "away": {
                            "team": {"id": 99},
                            "battingOrder": [1, 2, 3, 4],
                            "players": {
                                "ID3": {"person": {"id": 3, "fullName": "Third"}},
                                "ID4": {"person": {"id": 4, "fullName": "Fourth"}},
                            },
                        },
                        "home": {"team": {"id": 100}},
                    }
                },
            }
        }

        targets = main.get_batting_order_targets(data, lookahead=2)

        self.assertEqual([target["id"] for target in targets], [3, 4])
        self.assertEqual(targets[0]["role"], "On Deck")


class NetworkWrapperTests(unittest.TestCase):
    def test_send_telegram_raises_on_api_failure(self):
        with patch.object(main, "BOT_TOKEN", "token"):
            with patch.object(main, "request_json", return_value={"ok": False}):
                with self.assertRaises(RuntimeError):
                    main.send_telegram("123", "hello")


if __name__ == "__main__":
    unittest.main()
