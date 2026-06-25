import importlib
import os
import tempfile
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

    def test_normalize_score_makes_95_rare(self):
        self.assertLess(main.normalize_score(100), 91)
        self.assertEqual(main.display_score(main.normalize_score(120)), 95)

    def test_score_player_target_caps_hr_without_power_profile(self):
        stats = {
            "avg": ".260",
            "obp": ".340",
            "slg": ".390",
            "ops": ".730",
            "homeRuns": "2",
            "rbi": "20",
            "doubles": "12",
            "triples": "0",
            "baseOnBalls": "20",
            "strikeOuts": "40",
            "atBats": "180",
            "plateAppearances": "210",
        }
        pitcher = {"weakness": 25, "reliable": True}
        target = {"id": 1, "name": "Test Hitter", "batters_away": 3}

        with patch.object(main, "get_player_season_stats", return_value=stats):
            score = main.score_player_target(
                target,
                pitcher,
                95,
                offense={"first": {}},
                inning=4,
                inning_pressure={"consecutive_reached": 2},
            )

        self.assertLessEqual(score["hr"], 88)
        self.assertFalse(score["power_profile"])

    def test_player_quality_gate_requires_ops_slg_and_pa(self):
        self.assertFalse(main.player_quality_gate({"ops": .740, "slg": .450, "pa": 200}))
        self.assertFalse(main.player_quality_gate({"ops": .800, "slg": .390, "pa": 200}))
        self.assertFalse(main.player_quality_gate({"ops": .800, "slg": .450, "pa": 20}))
        self.assertTrue(main.player_quality_gate({"ops": .800, "slg": .450, "pa": 200}))

    def test_american_odds_units_and_score_bands(self):
        self.assertEqual(main.parse_american_odds("+180"), 180)
        self.assertEqual(main.parse_american_odds("-110"), -110)
        self.assertAlmostEqual(main.units_for_result("win", "+180"), 1.8)
        self.assertAlmostEqual(main.units_for_result("win", "-200"), .5)
        self.assertEqual(main.units_for_result("loss", "-110"), -1)
        self.assertEqual(main.score_band(95), "95+")
        self.assertEqual(main.score_band(93), "92-94")
        self.assertEqual(main.score_band(90), "90-91")


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

    def test_global_throttle_requires_player_score_improvement(self):
        main.game_alerts.clear()
        main.team_game_alerts.clear()
        main.player_game_alerts.clear()
        with patch.object(main, "last_global_alert_time", 0):
            main.record_global_alert(1, "Team", 99, 90, now=1000)
            allowed, reason = main.global_throttle_allows(1, "Other Team", 99, 95, now=2000)
            self.assertFalse(allowed)
            self.assertEqual(reason, "player game alert cap")


class AlertQualityFilterTests(unittest.TestCase):
    def make_player_score(self):
        return {
            "target": {"name": "Test Hitter"},
            "hrr": 93,
            "hit": 92,
            "total_bases": 86,
            "rbi": 92,
            "hr": 94,
            "pressure_score": 80,
            "pitcher_weakness": 10,
            "power_profile": True,
            "elite_profile": True,
        }

    def test_top_player_markets_limits_count_and_filters_empty_base_hr_rbi(self):
        markets = main.top_player_markets(
            self.make_player_score(),
            min_score=90,
            max_markets=2,
            runners_on=False,
        )

        self.assertEqual([market[0] for market in markets], ["Player H+R+RBI", "Player Hits"])

    def test_rbi_requires_true_gem_score_even_with_runners(self):
        player_score = self.make_player_score()
        player_score["hrr"] = 89
        player_score["hit"] = 88
        player_score["rbi"] = 95

        markets = main.top_player_markets(
            player_score,
            min_score=90,
            max_markets=3,
            runners_on=True,
        )

        self.assertEqual(markets, [])

    def test_rbi_gem_can_pass_with_runners_pressure_and_matchup(self):
        player_score = self.make_player_score()
        player_score["hrr"] = 89
        player_score["hit"] = 88
        player_score["rbi"] = 97
        player_score["pressure_score"] = 86
        player_score["pitcher_weakness"] = 12

        markets = main.top_player_markets(
            player_score,
            min_score=90,
            max_markets=3,
            runners_on=True,
        )

        self.assertEqual([market[0] for market in markets], ["Player RBI"])

    def test_obvious_hr_gem_can_lead_when_matchup_is_screaming(self):
        player_score = self.make_player_score()
        player_score["total_bases"] = 94
        player_score["hr"] = 98
        player_score["power_profile"] = True
        player_score["elite_profile"] = True
        player_score["pitcher_weakness"] = 12

        markets = main.top_player_markets(
            player_score,
            min_score=90,
            max_markets=2,
            runners_on=True,
        )

        self.assertEqual(markets[0][0], "Player Home Run")

    def test_hr_is_suppressed_without_obvious_matchup_support(self):
        player_score = self.make_player_score()
        player_score["hr"] = 98
        player_score["pitcher_weakness"] = 2

        markets = main.top_player_markets(
            player_score,
            min_score=90,
            max_markets=3,
            runners_on=True,
        )

        self.assertNotIn("Player Home Run", [market[0] for market in markets])

    def test_disabled_market_is_removed_from_ranking(self):
        player_score = self.make_player_score()
        player_score["power_profile"] = True

        with patch.object(main, "MARKET_ENABLED_HRR", False):
            markets = main.top_player_markets(
                player_score,
                min_score=90,
                max_markets=2,
                runners_on=True,
            )

        self.assertNotIn("Player H+R+RBI", [market[0] for market in markets])

    def test_pitcher_context_requires_weakness_or_bases_loaded_pressure(self):
        strong_pitcher = {"weakness": -12}

        self.assertFalse(main.pitcher_context_allows_alert(strong_pitcher, 60, True))
        self.assertTrue(main.pitcher_context_allows_alert(strong_pitcher, 80, True))
        self.assertFalse(main.pitcher_context_allows_alert(strong_pitcher, 80, False))
        self.assertTrue(main.pitcher_context_allows_alert({"weakness": 4}, 40, False))

    def test_low_quality_timing_blocks_two_strike_two_out_spots(self):
        self.assertTrue(main.is_low_quality_timing(2, 2))
        self.assertFalse(main.is_low_quality_timing(1, 2))

    def test_cold_opening_context_blocks_empty_first_inning(self):
        self.assertTrue(main.cold_opening_context(1, {}, 69))
        self.assertFalse(main.cold_opening_context(1, {"first": {}}, 69))
        self.assertFalse(main.cold_opening_context(1, {}, 94))

    def test_alert_tier_sends_gold_but_not_watchlist(self):
        self.assertEqual(main.alert_tier(94, 80, "MATCHUP"), "GOLD")
        self.assertEqual(main.alert_tier(90, 70, "MATCHUP"), "SILVER")
        self.assertEqual(main.alert_tier(87, 70, "MATCHUP"), "WATCHLIST")
        self.assertTrue(main.tier_can_send("GOLD"))
        self.assertFalse(main.tier_can_send("WATCHLIST"))

    def test_early_explanation_names_current_on_deck_and_target(self):
        text = main.build_early_explanation(
            {"fullName": "Jose Altuve"},
            [
                {"name": "Christian Walker", "batters_away": 1},
                {"name": "Cam Smith", "batters_away": 2},
            ],
            {"name": "Cam Smith", "batters_away": 2},
        )

        self.assertIn("WHY THIS ALERT IS EARLY", text)
        self.assertIn("Current batter: Jose Altuve", text)
        self.assertIn("On deck: Christian Walker", text)


class ResultTrackingTests(unittest.TestCase):
    def test_make_alert_id_is_stable_for_alert_context(self):
        now = main.datetime(2026, 6, 23, 12, 0, 0)

        alert_id = main.make_alert_id(12345, 6, "top", "GET_READY", 67890, now=now)

        self.assertEqual(alert_id, "0623-12345-6T-GR-67890")

    def test_record_alert_outcome_updates_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "status": "open",
                    })

                    alert = main.record_alert_outcome("alert-1", "win", "123")

                self.assertEqual(alert["status"], "win")
                self.assertEqual(alert["reported_by"], "123")

    def test_build_results_recap_includes_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            candidate_file = os.path.join(temp_dir, "candidates.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "CANDIDATE_LOG_FILE", candidate_file):
                    main.record_candidate({
                        "timestamp": main.utc_now().isoformat(),
                        "sent": False,
                        "skip_reason": "pressure below 60",
                    })
                    with patch.object(main, "post_sheet_event", return_value=True):
                        main.record_alert({
                            "id": "alert-1",
                            "sent_at": main.utc_now().isoformat(),
                            "alert_type": "MATCHUP",
                            "target": "Test Player",
                            "best_market": "Player Hits",
                            "score": 91,
                            "sent": True,
                            "status": "open",
                        })
                        main.record_alert_outcome("alert-1", "loss", "123")

                    recap = main.build_results_recap(days=1)

                self.assertIn("Record: 0-1-0", recap)
                self.assertIn("MATCHUP: 0.0% win", recap)
                self.assertIn("Player Hits", recap)
                self.assertIn("pressure below 60: 1", recap)

    def test_market_report_tracks_availability(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "MATCHUP",
                        "target": "Test Player",
                        "best_market": "Player RBI",
                        "score": 91,
                        "sent": True,
                        "batters_away": 3,
                        "inning": 5,
                        "status": "open",
                    })
                    main.record_alert_outcome("alert-1", "no_market", "123")

                report = main.build_market_report(days=1)

                self.assertIn("Player RBI", report)
                self.assertIn("Availability Rate: 0.0%", report)
                self.assertIn("3: 0.0% available", report)
                self.assertIn("5: 0.0% available", report)

    def test_settlement_reply_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "best_market": "Player Hits",
                        "status": "open",
                    })

                    main.pending_settlements["123"] = "alert-1"
                    response = main.handle_settlement_reply("123", "1 +180")

                self.assertIn("Recorded win", response)
                self.assertNotIn("123", main.pending_settlements)

                alert = main.find_alert("alert-1")
                self.assertEqual(alert["odds"], 180)
                self.assertAlmostEqual(alert["profit_units"], 1.8)

    def test_tracking_footer_uses_buttons_instead_of_command_spam(self):
        footer = main.tracking_footer("alert-1")

        self.assertIn("ID: alert-1", footer)
        self.assertIn("Tap a button", footer)
        self.assertNotIn("/win alert-1", footer)
        self.assertNotIn("/details alert-1", footer)

    def test_alert_reply_markup_carries_alert_id(self):
        markup = main.alert_reply_markup("alert-1")

        buttons = [
            button
            for row in markup["inline_keyboard"]
            for button in row
        ]
        callback_data = [button["callback_data"] for button in buttons]

        self.assertIn("result|win|alert-1", callback_data)
        self.assertIn("result|nomarket|alert-1", callback_data)
        self.assertIn("details|alert-1", callback_data)

    def test_callback_result_records_without_typed_alert_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "best_market": "Player Hits",
                        "status": "open",
                    })

                    update = {
                        "callback_query": {
                            "id": "callback-1",
                            "data": "result|nomarket|alert-1",
                            "from": {"id": 123},
                            "message": {"chat": {"id": 456}},
                        }
                    }
                    with patch.object(main, "answer_callback_query") as answer:
                        with patch.object(main, "send_telegram") as send:
                            handled = main.handle_callback_query(update)

                self.assertTrue(handled)
                answer.assert_called()
                send.assert_called()
                alert = main.find_alert("alert-1")
                self.assertEqual(alert["status"], "no_market")
                self.assertEqual(alert["reported_by"], "123")

    def test_market_penalty_reduces_low_availability_market(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    for idx in range(main.MARKET_AVAILABILITY_MIN_SAMPLE):
                        alert_id = f"alert-{idx}"
                        main.record_alert({
                            "id": alert_id,
                            "sent_at": main.utc_now().isoformat(),
                            "alert_type": "MATCHUP",
                            "target": "Test Player",
                            "best_market": "Player RBI",
                            "score": 91,
                            "sent": True,
                            "status": "open",
                        })
                        main.record_alert_outcome(alert_id, "no_market", "123")

                self.assertGreater(main.market_performance_penalty("Player RBI"), 0)

    def test_record_alert_posts_sheet_telemetry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True) as post:
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "status": "open",
                    })

                    payload = post.call_args.args[0]
                    self.assertEqual(payload["kind"], "alert")
                    self.assertEqual(payload["alert_id"], "alert-1")

    def test_record_alert_outcome_posts_sheet_telemetry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True) as post:
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "status": "open",
                    })
                    post.reset_mock()

                    main.record_alert_outcome("alert-1", "win", "123")

                    payload = post.call_args.args[0]
                    self.assertEqual(payload["kind"], "alert_result")
                    self.assertEqual(payload["alert_id"], "alert-1")
                    self.assertEqual(payload["status"], "win")

    def test_build_alert_details_reads_hidden_breakdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "best_market": "Player Hits",
                        "score": 95,
                        "pressure_score": 69,
                        "player_avg": .300,
                        "player_obp": .360,
                        "player_slg": .443,
                        "player_ops": .803,
                        "player_pa": 120,
                        "pitcher": "Test Pitcher",
                        "pitcher_weakness": 26,
                        "timing_boost": 10,
                        "status": "open",
                    })

                details = main.build_alert_details("alert-1")

                self.assertIn("Debug Breakdown", details)
                self.assertIn("AVG: 0.300", details)
                self.assertIn("Pitcher Weakness: 26", details)

    def test_recap_includes_roi_score_bands_and_lineup_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_file = os.path.join(temp_dir, "results.json")
            with patch.object(main, "RESULTS_FILE", result_file):
                with patch.object(main, "post_sheet_event", return_value=True):
                    main.record_alert({
                        "id": "alert-1",
                        "sent_at": main.utc_now().isoformat(),
                        "alert_type": "GET_READY",
                        "target": "Test Player",
                        "best_market": "Player Hits",
                        "score": 95,
                        "lineup_position": 3,
                        "sent": True,
                        "status": "open",
                    })
                    main.record_alert_outcome("alert-1", "win", "123", odds="+180")

                recap = main.build_results_recap(days=1)

                self.assertIn("Units: +1.80", recap)
                self.assertIn("ROI: 180.0%", recap)
                self.assertIn("95+: 1-0-0", recap)
                self.assertIn("#3: 100.0% win", recap)

    def test_training_bet_normalizes_market_and_reports_roi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bet_file = os.path.join(temp_dir, "bets.json")
            with patch.object(main, "BET_HISTORY_FILE", bet_file):
                bet = main.record_training_bet(
                    "win",
                    "+340",
                    stake=1,
                    market="Sam Antonacci to record 2+ hits",
                    note="screenshot",
                )
                report = main.build_training_report(days=1)

                self.assertEqual(bet["market"], "Player Hits")
                self.assertAlmostEqual(bet["profit_units"], 3.4)
                self.assertIn("Player Hits", report)
                self.assertIn("ROI: 340.0%", report)

    def test_training_market_penalty_uses_negative_roi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bet_file = os.path.join(temp_dir, "bets.json")
            with patch.object(main, "BET_HISTORY_FILE", bet_file):
                with patch.object(main, "MIN_TRAINING_BETS_PER_MARKET", 2):
                    main.record_training_bet(
                        "loss",
                        "+600",
                        stake=1,
                        market="to hit a home run",
                        matched_alert_id="alert-1",
                    )
                    main.record_training_bet(
                        "loss",
                        "+1100",
                        stake=1,
                        market="home run",
                        matched_alert_id="alert-2",
                    )

                    self.assertEqual(
                        main.training_market_penalty("Player Home Run"),
                        main.TRAINING_MARKET_PENALTY_POINTS,
                    )

    def test_unmatched_training_bets_do_not_penalize_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bet_file = os.path.join(temp_dir, "bets.json")
            with patch.object(main, "BET_HISTORY_FILE", bet_file):
                with patch.object(main, "MIN_TRAINING_BETS_PER_MARKET", 2):
                    main.record_training_bet("loss", "+600", stake=1, market="to hit a home run")
                    main.record_training_bet("loss", "+1100", stake=1, market="home run")

                    self.assertEqual(main.training_market_penalty("Player Home Run"), 0)

    def test_trainbet_parser_accepts_note_separator(self):
        parsed = main.parse_trainbet_args(
            ["win", "+340", "1", "Player", "Hits", "|", "Sam", "Antonacci"]
        )

        self.assertEqual(parsed, ("win", "+340", "1", "Player Hits", "Sam Antonacci"))


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
