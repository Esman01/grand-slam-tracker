import json
import os
import time
from datetime import datetime, timedelta

import requests


MLB_API_BASE = "https://statsapi.mlb.com/api"
TELEGRAM_API_BASE = "https://api.telegram.org"

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_WEBHOOK_URL = os.getenv("SHEET_WEBHOOK_URL")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))
ONLY_BASES_LOADED = os.getenv("ONLY_BASES_LOADED", "false").lower() == "true"

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
MAX_ALERTS_PER_HALF_INNING = int(os.getenv("MAX_ALERTS_PER_HALF_INNING", "1"))
ALERT_MEMORY_SECONDS = int(os.getenv("ALERT_MEMORY_SECONDS", "14400"))
MAX_ALERTS_PER_GAME = int(os.getenv("MAX_ALERTS_PER_GAME", "2"))
MAX_ALERTS_PER_TEAM_PER_GAME = int(os.getenv("MAX_ALERTS_PER_TEAM_PER_GAME", "1"))
MAX_ALERTS_PER_PLAYER_PER_GAME = int(os.getenv("MAX_ALERTS_PER_PLAYER_PER_GAME", "1"))
GLOBAL_ALERT_COOLDOWN_SECONDS = int(os.getenv("GLOBAL_ALERT_COOLDOWN_SECONDS", "600"))
PLAYER_SCORE_IMPROVEMENT = int(os.getenv("PLAYER_SCORE_IMPROVEMENT", "10"))

LOOKAHEAD_BATTERS = int(os.getenv("LOOKAHEAD_BATTERS", "4"))
MIN_TARGET_BATTERS_AWAY = int(os.getenv("MIN_TARGET_BATTERS_AWAY", "2"))
MAX_TARGET_BATTERS_AWAY = int(os.getenv("MAX_TARGET_BATTERS_AWAY", "4"))
PREFERRED_MARKET_DISTANCE = int(os.getenv("PREFERRED_MARKET_DISTANCE", "3"))

MIN_GET_READY_SCORE = int(os.getenv("MIN_GET_READY_SCORE", "90"))
MIN_MATCHUP_SCORE = int(os.getenv("MIN_MATCHUP_SCORE", "92"))
MIN_PRESSURE_SCORE = int(os.getenv("MIN_PRESSURE_SCORE", "90"))
MIN_PLAYER_MARKET_SCORE = int(os.getenv("MIN_PLAYER_MARKET_SCORE", "90"))
MIN_MATCHUP_MARKET_SCORE = int(os.getenv("MIN_MATCHUP_MARKET_SCORE", "92"))
MIN_ALERT_PRESSURE_SCORE = int(os.getenv("MIN_ALERT_PRESSURE_SCORE", "60"))
STRONG_PITCHER_PRESSURE_SCORE = int(os.getenv("STRONG_PITCHER_PRESSURE_SCORE", "75"))
MAX_MARKETS_PER_ALERT = int(os.getenv("MAX_MARKETS_PER_ALERT", "2"))
SECONDARY_MARKET_MAX_DROP = int(os.getenv("SECONDARY_MARKET_MAX_DROP", "4"))
MIN_MARKET_DISPLAY_SCORE = int(os.getenv("MIN_MARKET_DISPLAY_SCORE", "88"))
AUTO_MARKET_PENALTIES = os.getenv("AUTO_MARKET_PENALTIES", "true").lower() == "true"
MARKET_AVAILABILITY_MIN_SAMPLE = int(os.getenv("MARKET_AVAILABILITY_MIN_SAMPLE", "10"))
LOW_MARKET_AVAILABILITY_RATE = float(os.getenv("LOW_MARKET_AVAILABILITY_RATE", ".35"))
MARKET_PENALTY_POINTS = int(os.getenv("MARKET_PENALTY_POINTS", "8"))
SCORE_CALIBRATION_MIN_SAMPLE = int(os.getenv("SCORE_CALIBRATION_MIN_SAMPLE", "10"))
SCORE_CALIBRATION_MIN_WIN_RATE = float(os.getenv("SCORE_CALIBRATION_MIN_WIN_RATE", ".50"))
SCORE_CALIBRATION_PENALTY = int(os.getenv("SCORE_CALIBRATION_PENALTY", "5"))
MIN_PLAYER_OPS = float(os.getenv("MIN_PLAYER_OPS", ".750"))
MIN_PLAYER_SLG = float(os.getenv("MIN_PLAYER_SLG", ".400"))
MIN_PLAYER_PA = int(os.getenv("MIN_PLAYER_PA", "80"))
MIN_POWER_SLG_FOR_HR = float(os.getenv("MIN_POWER_SLG_FOR_HR", ".450"))
MIN_POWER_HR_RATE = float(os.getenv("MIN_POWER_HR_RATE", ".035"))
SEND_SILVER_ALERTS = os.getenv("SEND_SILVER_ALERTS", "false").lower() == "true"
SHOW_DEBUG = os.getenv("SHOW_DEBUG", "false").lower() == "true"
MARKET_ENABLED_HRR = os.getenv("MARKET_ENABLED_HRR", "true").lower() == "true"
MARKET_ENABLED_TOTAL_BASES = os.getenv("MARKET_ENABLED_TOTAL_BASES", "true").lower() == "true"
MARKET_ENABLED_HITS = os.getenv("MARKET_ENABLED_HITS", "true").lower() == "true"
MARKET_ENABLED_RBI = os.getenv("MARKET_ENABLED_RBI", "true").lower() == "true"
MARKET_ENABLED_HR = os.getenv("MARKET_ENABLED_HR", "true").lower() == "true"

FRESH_INJURY_DAYS = int(os.getenv("FRESH_INJURY_DAYS", "14"))
STATS_CACHE_SECONDS = int(os.getenv("STATS_CACHE_SECONDS", "900"))
INJURY_CACHE_SECONDS = int(os.getenv("INJURY_CACHE_SECONDS", "3600"))
TELEGRAM_OFFSET_FILE = os.getenv("TELEGRAM_OFFSET_FILE", ".telegram_offset")
RESULTS_FILE = os.getenv("RESULTS_FILE", "alert_results.json")
CANDIDATE_LOG_FILE = os.getenv("CANDIDATE_LOG_FILE", "candidate_log.json")
BET_HISTORY_FILE = os.getenv("BET_HISTORY_FILE", "bet_training.json")
RESULTS_RECAP_DAYS = int(os.getenv("RESULTS_RECAP_DAYS", "1"))
MAX_RECAP_ITEMS = int(os.getenv("MAX_RECAP_ITEMS", "5"))
MIN_TRAINING_BETS_PER_MARKET = int(os.getenv("MIN_TRAINING_BETS_PER_MARKET", "3"))
TRAINING_MARKET_PENALTY_POINTS = int(os.getenv("TRAINING_MARKET_PENALTY_POINTS", "6"))
TRAINING_BAD_ROI_THRESHOLD = float(os.getenv("TRAINING_BAD_ROI_THRESHOLD", "-.10"))

RECENT_INJURY_NAMES = [
    x.strip().lower()
    for x in os.getenv("RECENT_INJURY_NAMES", "").split(",")
    if x.strip()
]

sent_alerts = {}
game_alerts = {}
team_game_alerts = {}
player_game_alerts = {}
last_global_alert_time = 0
pending_settlements = {}
player_stats_cache = {}
injury_cache = {}
last_update_id = None

OUTCOME_COMMANDS = {
    "/win": "win",
    "/won": "win",
    "/loss": "loss",
    "/lost": "loss",
    "/push": "push",
    "/void": "push",
    "/nomarket": "no_market",
    "/no_market": "no_market",
    "/locked": "no_market",
    "/didntbet": "didnt_bet",
    "/didnt_bet": "didnt_bet",
}

CALLBACK_ACTIONS = {
    "win": "win",
    "loss": "loss",
    "push": "push",
    "nomarket": "no_market",
    "didntbet": "didnt_bet",
}

SETTLE_CHOICES = {
    "1": "win",
    "win": "win",
    "2": "loss",
    "loss": "loss",
    "3": "push",
    "push": "push",
    "void": "push",
    "4": "no_market",
    "nomarket": "no_market",
    "no_market": "no_market",
    "locked": "no_market",
    "5": "didnt_bet",
    "didntbet": "didnt_bet",
    "didnt_bet": "didnt_bet",
}


def validate_config():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not SHEET_WEBHOOK_URL:
        missing.append("SHEET_WEBHOOK_URL")
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )


def safe_float(value, default=0.0):
    try:
        if value in [None, "", ".---", "---"]:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if value in [None, "", ".---", "---"]:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp(value, low=0, high=100):
    return max(low, min(high, round(value)))


def normalize_score(raw_score):
    raw = safe_float(raw_score)
    if raw >= 112:
        return 95
    if raw >= 104:
        return 92 + ((raw - 104) / 8 * 3)
    if raw >= 92:
        return 86 + ((raw - 92) / 12 * 6)
    if raw >= 78:
        return 72 + ((raw - 78) / 14 * 14)
    return raw * 0.92


def display_score(score):
    return min(95, clamp(score))


def grade(score):
    shown = display_score(score)
    if shown >= 94:
        return "ELITE"
    if shown >= 90:
        return "STRONG"
    if shown >= 86:
        return "GOOD"
    return "WATCH"


def request_json(method, url, **kwargs):
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 10), **kwargs)
    response.raise_for_status()
    return response.json()


def cache_get(cache, key):
    entry = cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.time() >= expires_at:
        cache.pop(key, None)
        return None
    return value


def cache_set(cache, key, value, ttl_seconds):
    cache[key] = (time.time() + ttl_seconds, value)
    return value


def prune_sent_alerts(now=None):
    now = now or time.time()
    expired = [
        key
        for key, info in sent_alerts.items()
        if now - info.get("last_time", 0) > ALERT_MEMORY_SECONDS
    ]
    for key in expired:
        sent_alerts.pop(key, None)


def load_last_update_id():
    try:
        with open(TELEGRAM_OFFSET_FILE, "r", encoding="utf-8") as handle:
            return safe_int(handle.read().strip(), None)
    except FileNotFoundError:
        return None
    except OSError as exc:
        print("Telegram offset read error:", exc, flush=True)
        return None


def save_last_update_id(update_id):
    if update_id is None:
        return
    try:
        with open(TELEGRAM_OFFSET_FILE, "w", encoding="utf-8") as handle:
            handle.write(str(update_id))
    except OSError as exc:
        print("Telegram offset write error:", exc, flush=True)


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min


def parse_american_odds(value):
    if value in [None, ""]:
        return None
    text = str(value).strip().replace("−", "-")
    if not text:
        return None
    if text.startswith("+"):
        text = text[1:]
    try:
        odds = int(text)
    except ValueError:
        return None
    if -100 < odds < 100:
        return None
    return odds


def units_for_result(outcome, odds, stake=1.0):
    odds = parse_american_odds(odds)
    if outcome == "win":
        if odds is None:
            return stake
        if odds > 0:
            return stake * odds / 100
        return stake * 100 / abs(odds)
    if outcome == "loss":
        return -stake
    if outcome in ["push", "no_market", "didnt_bet"]:
        return 0
    return 0


def normalize_market_name(value):
    text = str(value or "").lower()
    compact = text.replace("+", " plus ")

    if "home run" in compact or "homer" in compact or " hr" in f" {compact}":
        return "Player Home Run"
    if "total bases" in compact:
        return "Player Total Bases"
    if "hits runs rbis" in compact or "hits plus runs plus rbis" in compact:
        return "Player H+R+RBI"
    if "h+r+rbi" in compact or "hrr" in compact:
        return "Player H+R+RBI"
    if "record a hit" in compact or " hit" in f" {compact}" or "hits" in compact:
        return "Player Hits"
    if "rbi" in compact:
        return "Player RBI"
    if "team total" in compact or "total runs" in compact or "over " in compact:
        return "Team Total Over"
    if "player hit" in compact or compact.strip() == "hits":
        return "Player Hits"
    return str(value or "UNKNOWN").strip() or "UNKNOWN"


def load_training_bets():
    return load_json_list(BET_HISTORY_FILE)


def save_training_bets(bets):
    save_json_list(BET_HISTORY_FILE, bets)


def record_training_bet(outcome, odds, stake=1.0, market="", note="", source="manual", placed_at=None):
    outcome = str(outcome or "").lower()
    if outcome not in ["win", "loss", "push", "no_market", "didnt_bet"]:
        return None

    parsed_odds = parse_american_odds(odds)
    stake_units = safe_float(stake, 1)
    bet = {
        "recorded_at": utc_now().isoformat(),
        "placed_at": placed_at or "",
        "source": source,
        "market": normalize_market_name(market),
        "raw_market": str(market or ""),
        "note": str(note or ""),
        "status": outcome,
        "odds": parsed_odds if parsed_odds is not None else "",
        "stake_units": stake_units,
        "profit_units": units_for_result(outcome, parsed_odds, stake_units),
    }
    bets = load_training_bets()
    bets.append(bet)
    if len(bets) > 3000:
        bets = bets[-3000:]
    save_training_bets(bets)
    return bet


def summarize_training_bets(days=30, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=days)
    summary = {
        "total": 0,
        "win": 0,
        "loss": 0,
        "push": 0,
        "no_market": 0,
        "didnt_bet": 0,
        "risked_units": 0,
        "profit_units": 0,
        "by_market": {},
    }

    for bet in load_training_bets():
        recorded_at = parse_iso_datetime(bet.get("recorded_at"))
        if recorded_at < cutoff:
            continue
        status = bet.get("status", "open")
        market = normalize_market_name(bet.get("market") or bet.get("raw_market"))
        summary["total"] += 1
        summary[status] = summary.get(status, 0) + 1
        item = summary["by_market"].setdefault(
            market,
            {
                "total": 0,
                "win": 0,
                "loss": 0,
                "push": 0,
                "no_market": 0,
                "didnt_bet": 0,
                "risked_units": 0,
                "profit_units": 0,
            },
        )
        item["total"] += 1
        if status in item:
            item[status] += 1
        if status in ["win", "loss"]:
            stake = safe_float(bet.get("stake_units"), 1)
            profit = safe_float(
                bet.get("profit_units"),
                units_for_result(status, bet.get("odds"), stake),
            )
            summary["risked_units"] += stake
            summary["profit_units"] += profit
            item["risked_units"] += stake
            item["profit_units"] += profit

    return summary


def training_market_penalty(market):
    if not AUTO_MARKET_PENALTIES or not market:
        return 0

    item = summarize_training_bets(days=30)["by_market"].get(normalize_market_name(market))
    if not item:
        return 0
    graded = item["win"] + item["loss"]
    if graded < MIN_TRAINING_BETS_PER_MARKET or item["risked_units"] <= 0:
        return 0

    roi = item["profit_units"] / item["risked_units"]
    if roi < TRAINING_BAD_ROI_THRESHOLD:
        return TRAINING_MARKET_PENALTY_POINTS
    return 0


def score_band(score):
    score = display_score(score)
    if score >= 95:
        return "95+"
    if score >= 92:
        return "92-94"
    if score >= 90:
        return "90-91"
    if score >= 85:
        return "85-89"
    return "Under 85"


def load_result_store():
    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"alerts": []}
    except (OSError, json.JSONDecodeError) as exc:
        print("Results store read error:", exc, flush=True)
        return {"alerts": []}

    if not isinstance(data, dict):
        return {"alerts": []}
    alerts = data.get("alerts", [])
    if not isinstance(alerts, list):
        alerts = []
    data["alerts"] = alerts
    return data


def save_result_store(store):
    temp_file = f"{RESULTS_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_file, RESULTS_FILE)
    except OSError as exc:
        print("Results store write error:", exc, flush=True)


def load_json_list(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{path} read error:", exc, flush=True)
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return data["candidates"]
    return []


def save_json_list(path, items):
    temp_file = f"{path}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as handle:
            json.dump(items, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_file, path)
    except OSError as exc:
        print(f"{path} write error:", exc, flush=True)


def record_candidate(candidate):
    candidates = load_json_list(CANDIDATE_LOG_FILE)
    candidates.append(candidate)
    if len(candidates) > 2000:
        candidates = candidates[-2000:]
    save_json_list(CANDIDATE_LOG_FILE, candidates)


def post_sheet_event(payload):
    try:
        data = request_json("post", SHEET_WEBHOOK_URL, json=payload)
    except Exception as exc:
        print("Sheet telemetry error:", exc, flush=True)
        return False

    if data.get("ok") is not True:
        print("Sheet telemetry rejected:", data, flush=True)
        return False

    return True


def make_alert_id(game_pk, inning, half, alert_type, target_id, now=None):
    now = now or utc_now()
    half_code = str(half or "?")[:1].upper()
    type_code = "".join(part[:1] for part in str(alert_type).split("_"))[:3]
    return f"{now.strftime('%m%d')}-{game_pk}-{inning}{half_code}-{type_code}-{target_id}"


def record_alert(alert):
    store = load_result_store()
    alerts = store.setdefault("alerts", [])
    existing = next((item for item in alerts if item.get("id") == alert.get("id")), None)

    if existing:
        existing.update({
            key: value
            for key, value in alert.items()
            if key not in {"status", "outcome_at", "reported_by"}
        })
    else:
        alert.setdefault("status", "open")
        alerts.append(alert)

    save_result_store(store)
    payload = dict(alert)
    payload["kind"] = "alert"
    payload["alert_id"] = payload.get("id")
    post_sheet_event(payload)


def record_alert_outcome(alert_id, outcome, reported_by, odds=None):
    store = load_result_store()
    for alert in store.get("alerts", []):
        if str(alert.get("id")).lower() == str(alert_id).lower():
            alert["status"] = outcome
            alert["outcome_at"] = utc_now().isoformat()
            alert["reported_by"] = str(reported_by)
            parsed_odds = parse_american_odds(odds)
            if parsed_odds is not None:
                alert["odds"] = parsed_odds
            alert["stake_units"] = 1
            alert["profit_units"] = units_for_result(outcome, alert.get("odds"))
            save_result_store(store)
            post_sheet_event({
                "kind": "alert_result",
                "alert_id": alert["id"],
                "status": outcome,
                "outcome": outcome,
                "outcome_at": alert["outcome_at"],
                "reported_by": alert["reported_by"],
                "odds": alert.get("odds", ""),
                "profit_units": alert.get("profit_units", 0),
            })
            return alert
    return None


def settlement_prompt(alert_id):
    alert = find_alert(alert_id)
    if not alert:
        return f"I couldn't find alert ID {alert_id}.\n\n{build_pending_alerts()}"

    return (
        f"Settle {alert_id}\n\n"
        f"{alert.get('target', alert.get('team', 'Alert'))}\n"
        f"{alert.get('best_market', 'Market')}\n\n"
        "Did you bet it?\n\n"
        "1. Win\n"
        "2. Loss\n"
        "3. Push\n"
        "4. No Market\n"
        "5. Didn't Bet\n\n"
        "Reply with 1, 2, 3, 4, or 5.\n"
        "You can include odds too, like: 1 +180"
    )


def handle_settlement_reply(chat_id, text):
    alert_id = pending_settlements.get(str(chat_id))
    if not alert_id:
        return None

    parts = (text or "").strip().split()
    choice = SETTLE_CHOICES.get(parts[0].lower() if parts else "")
    odds = parse_american_odds(parts[1]) if len(parts) > 1 else None
    if not choice:
        return (
            "Reply with 1, 2, 3, 4, or 5.\n\n"
            "1. Win\n2. Loss\n3. Push\n4. No Market\n5. Didn't Bet"
        )

    pending_settlements.pop(str(chat_id), None)
    alert = record_alert_outcome(alert_id, choice, chat_id, odds=odds)
    if not alert:
        return f"I couldn't find alert ID {alert_id}.\n\n{build_pending_alerts()}"
    return outcome_response(alert, choice)


def summarize_results(days=1, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=days)
    summary = {
        "total": 0,
        "sent": 0,
        "open": 0,
        "win": 0,
        "loss": 0,
        "push": 0,
        "no_market": 0,
        "didnt_bet": 0,
        "by_type": {},
        "by_market": {},
        "by_lineup_position": {},
        "skipped_reasons": {},
        "winner_scores": [],
        "loser_scores": [],
        "profit_units": 0,
        "risked_units": 0,
        "odds_values": [],
        "by_score_band": {},
        "recent": [],
    }

    alerts = [
        alert
        for alert in load_result_store().get("alerts", [])
        if alert.get("sent", True) is True
    ]
    alerts = sorted(
        alerts,
        key=lambda item: parse_iso_datetime(item.get("sent_at")),
        reverse=True,
    )

    for alert in alerts:
        sent_at = parse_iso_datetime(alert.get("sent_at"))
        if sent_at < cutoff:
            continue

        status = alert.get("status", "open")
        alert_type = alert.get("alert_type", "UNKNOWN")
        market = alert.get("best_market") or (
            alert.get("markets", ["UNKNOWN"])[0] if alert.get("markets") else "UNKNOWN"
        )
        summary["total"] += 1
        summary["sent"] += 1
        summary[status] = summary.get(status, 0) + 1
        type_summary = summary["by_type"].setdefault(
            alert_type,
            {"total": 0, "win": 0, "loss": 0, "push": 0, "no_market": 0, "didnt_bet": 0},
        )
        type_summary["total"] += 1
        if status in type_summary:
            type_summary[status] += 1
        market_summary = summary["by_market"].setdefault(
            market,
            {"total": 0, "win": 0, "loss": 0, "push": 0, "no_market": 0, "didnt_bet": 0},
        )
        market_summary["total"] += 1
        if status in market_summary:
            market_summary[status] += 1
        if status == "win":
            summary["winner_scores"].append(safe_float(alert.get("score")))
        if status == "loss":
            summary["loser_scores"].append(safe_float(alert.get("score")))
        if status in ["win", "loss"]:
            summary["risked_units"] += safe_float(alert.get("stake_units"), 1)
            summary["profit_units"] += safe_float(
                alert.get("profit_units"),
                units_for_result(status, alert.get("odds")),
            )
            odds = parse_american_odds(alert.get("odds"))
            if odds is not None:
                summary["odds_values"].append(odds)

        band = score_band(alert.get("score"))
        band_summary = summary["by_score_band"].setdefault(
            band,
            {"total": 0, "win": 0, "loss": 0, "push": 0, "no_market": 0, "didnt_bet": 0},
        )
        band_summary["total"] += 1
        if status in band_summary:
            band_summary[status] += 1

        lineup_position = alert.get("lineup_position")
        if lineup_position:
            lineup_key = f"#{safe_int(lineup_position)}"
            lineup_summary = summary["by_lineup_position"].setdefault(
                lineup_key,
                {"total": 0, "win": 0, "loss": 0, "push": 0, "no_market": 0, "didnt_bet": 0},
            )
            lineup_summary["total"] += 1
            if status in lineup_summary:
                lineup_summary[status] += 1

        if len(summary["recent"]) < MAX_RECAP_ITEMS:
            summary["recent"].append(alert)

    for candidate in load_json_list(CANDIDATE_LOG_FILE):
        timestamp = parse_iso_datetime(candidate.get("timestamp"))
        if timestamp < cutoff or candidate.get("sent") is True:
            continue
        reason = candidate.get("skip_reason") or "unknown"
        summary["skipped_reasons"][reason] = summary["skipped_reasons"].get(reason, 0) + 1

    return summary


def build_market_stats(days=RESULTS_RECAP_DAYS, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=days)
    stats = {}

    for alert in load_result_store().get("alerts", []):
        if alert.get("sent", True) is not True:
            continue
        sent_at = parse_iso_datetime(alert.get("sent_at"))
        if sent_at < cutoff:
            continue

        market = alert.get("best_market") or (
            alert.get("markets", ["UNKNOWN"])[0] if alert.get("markets") else "UNKNOWN"
        )
        status = alert.get("status", "open")
        item = stats.setdefault(
            market,
            {
                "sent": 0,
                "available": 0,
                "win": 0,
                "loss": 0,
                "push": 0,
                "no_market": 0,
                "didnt_bet": 0,
                "by_distance": {},
                "by_inning": {},
            },
        )
        item["sent"] += 1
        if status != "no_market":
            item["available"] += 1
        if status in item:
            item[status] += 1
        distance = str(alert.get("batters_away", "unknown"))
        distance_item = item["by_distance"].setdefault(distance, {"sent": 0, "available": 0})
        distance_item["sent"] += 1
        if status != "no_market":
            distance_item["available"] += 1

        inning = str(alert.get("inning", "unknown"))
        inning_item = item["by_inning"].setdefault(inning, {"sent": 0, "available": 0})
        inning_item["sent"] += 1
        if status != "no_market":
            inning_item["available"] += 1

    return stats


def build_market_report(days=RESULTS_RECAP_DAYS):
    stats = build_market_stats(days)
    if not stats:
        return f"Market report: last {days} day(s)\n\nNo sent alerts yet."

    lines = [f"Market report: last {days} day(s)"]
    for market, item in sorted(stats.items(), key=lambda value: value[1]["sent"], reverse=True):
        availability = (item["available"] / item["sent"] * 100) if item["sent"] else 0
        graded = item["win"] + item["loss"]
        win_rate = (item["win"] / graded * 100) if graded else 0
        lines.extend([
            "",
            market,
            f"Sent: {item['sent']}",
            f"Available: {item['available']}",
            f"Availability Rate: {availability:.1f}%",
            f"Win Rate: {win_rate:.1f}%" if graded else "Win Rate: not enough graded alerts",
            f"No Market: {item['no_market']}",
        ])
        if item["by_distance"]:
            lines.append("By batters away:")
            for distance, dist_item in sorted(item["by_distance"].items()):
                rate = (dist_item["available"] / dist_item["sent"] * 100) if dist_item["sent"] else 0
                lines.append(f"{distance}: {rate:.1f}% available ({dist_item['sent']} sent)")
        if item["by_inning"]:
            lines.append("By inning:")
            for inning, inning_item in sorted(item["by_inning"].items(), key=lambda row: safe_int(row[0], 99)):
                rate = (inning_item["available"] / inning_item["sent"] * 100) if inning_item["sent"] else 0
                lines.append(f"{inning}: {rate:.1f}% available ({inning_item['sent']} sent)")
    return "\n".join(lines)


def build_training_report(days=30):
    summary = summarize_training_bets(days)
    if not summary["total"]:
        return (
            f"Training bets: last {days} day(s)\n\n"
            "No training bets logged yet.\n\n"
            "Example:\n"
            "/trainbet win +340 1 Player Hits | Sam Antonacci 2+ hits"
        )

    graded = summary["win"] + summary["loss"]
    win_rate = (summary["win"] / graded * 100) if graded else 0
    roi = (
        summary["profit_units"] / summary["risked_units"] * 100
        if summary["risked_units"]
        else 0
    )

    lines = [
        f"Training bets: last {days} day(s)",
        "",
        f"Logged: {summary['total']}",
        f"Record: {summary['win']}-{summary['loss']}-{summary['push']}",
        f"No market: {summary['no_market']}",
        f"Win rate: {win_rate:.1f}%" if graded else "Win rate: not enough graded bets",
        f"Units: {summary['profit_units']:+.2f}",
        f"ROI: {roi:.1f}%" if summary["risked_units"] else "ROI: not enough odds/results",
    ]

    if summary["by_market"]:
        lines.extend(["", "By market:"])
        for market, item in sorted(
            summary["by_market"].items(),
            key=lambda row: row[1]["total"],
            reverse=True,
        ):
            market_graded = item["win"] + item["loss"]
            market_win_rate = (item["win"] / market_graded * 100) if market_graded else 0
            market_roi = (
                item["profit_units"] / item["risked_units"] * 100
                if item["risked_units"]
                else 0
            )
            penalty = training_market_penalty(market)
            line = f"{market}: {item['win']}-{item['loss']}-{item['push']}"
            if market_graded:
                line += f" | {market_win_rate:.1f}% win | {market_roi:+.1f}% ROI"
            if penalty:
                line += f" | penalty -{penalty}"
            lines.append(line)

    return "\n".join(lines)


def parse_trainbet_args(args):
    if len(args) < 4:
        return None

    outcome = SETTLE_CHOICES.get(args[0].lower())
    odds = args[1]
    stake = args[2]
    rest = " ".join(args[3:])
    market, _, note = rest.partition("|")
    return outcome, odds, stake, market.strip(), note.strip()


def market_performance_penalty(market):
    if not AUTO_MARKET_PENALTIES or not market:
        return 0

    penalty = training_market_penalty(market)
    stats = build_market_stats(days=30)
    item = stats.get(market)
    if not item or item["sent"] < MARKET_AVAILABILITY_MIN_SAMPLE:
        return penalty

    availability = item["available"] / item["sent"] if item["sent"] else 1
    if availability < LOW_MARKET_AVAILABILITY_RATE:
        penalty = max(penalty, MARKET_PENALTY_POINTS)

    graded = item["win"] + item["loss"]
    if graded >= MARKET_AVAILABILITY_MIN_SAMPLE:
        win_rate = item["win"] / graded
        if win_rate < SCORE_CALIBRATION_MIN_WIN_RATE:
            penalty = max(penalty, max(3, MARKET_PENALTY_POINTS // 2))

    return penalty


def score_calibration_penalty(score):
    if safe_float(score) < 90:
        return 0

    high_score_alerts = []
    for alert in load_result_store().get("alerts", []):
        if safe_float(alert.get("score")) >= 90 and alert.get("status") in ["win", "loss"]:
            high_score_alerts.append(alert)

    if len(high_score_alerts) < SCORE_CALIBRATION_MIN_SAMPLE:
        return 0

    wins = sum(1 for alert in high_score_alerts if alert.get("status") == "win")
    win_rate = wins / len(high_score_alerts)
    if win_rate < SCORE_CALIBRATION_MIN_WIN_RATE:
        return SCORE_CALIBRATION_PENALTY
    return 0


def calibrated_market_score(market, score):
    adjusted = safe_float(score)
    adjusted -= market_performance_penalty(market)
    adjusted -= score_calibration_penalty(adjusted)
    return max(0, adjusted)


def build_results_recap(days=RESULTS_RECAP_DAYS):
    summary = summarize_results(days)
    graded = summary["win"] + summary["loss"]
    win_rate = (summary["win"] / graded * 100) if graded else 0
    roi = (summary["profit_units"] / summary["risked_units"] * 100) if summary["risked_units"] else 0
    avg_odds = (
        sum(summary["odds_values"]) / len(summary["odds_values"])
        if summary["odds_values"]
        else 0
    )

    lines = [
        f"Results recap: last {days} day(s)",
        "",
        f"Sent alerts: {summary['sent']}",
        f"Record: {summary['win']}-{summary['loss']}-{summary['push']}",
        f"No market/locked: {summary['no_market']}",
        f"Didn't bet: {summary['didnt_bet']}",
        f"Still open: {summary['open']}",
        f"Win rate: {win_rate:.1f}%" if graded else "Win rate: not enough graded alerts",
        f"Units: {summary['profit_units']:+.2f}",
        f"ROI: {roi:.1f}%" if summary["risked_units"] else "ROI: not enough odds/results",
        f"Average odds: {avg_odds:+.0f}" if summary["odds_values"] else "Average odds: n/a",
    ]

    if summary["by_type"]:
        type_lines = []
        for alert_type, info in sorted(summary["by_type"].items()):
            type_graded = info["win"] + info["loss"]
            type_win_rate = (info["win"] / type_graded * 100) if type_graded else 0
            if type_graded:
                type_lines.append(f"{alert_type}: {type_win_rate:.1f}% win ({info['total']} sent)")
            else:
                type_lines.append(f"{alert_type}: no graded bets ({info['total']} sent)")
        lines.extend(["", "By alert type:", "\n".join(type_lines)])

    if summary["by_market"]:
        market_lines = []
        for market, info in sorted(summary["by_market"].items()):
            market_graded = info["win"] + info["loss"]
            market_win_rate = (info["win"] / market_graded * 100) if market_graded else 0
            nomarket_rate = (info["no_market"] / info["total"] * 100) if info["total"] else 0
            availability_rate = 100 - nomarket_rate
            if market_graded:
                market_lines.append(
                    f"{market}: {market_win_rate:.1f}% win | {availability_rate:.1f}% available"
                )
            else:
                market_lines.append(f"{market}: no graded bets | {availability_rate:.1f}% available")
        lines.extend(["", "By market:", "\n".join(market_lines)])

    if summary["by_score_band"]:
        band_order = ["95+", "92-94", "90-91", "85-89", "Under 85"]
        band_lines = []
        for band in band_order:
            info = summary["by_score_band"].get(band)
            if not info:
                continue
            band_lines.append(
                f"{band}: {info['win']}-{info['loss']}-{info['push']} "
                f"({info['total']} sent)"
            )
        if band_lines:
            lines.extend(["", "Confidence calibration:", "\n".join(band_lines)])

    if summary["by_lineup_position"]:
        lineup_lines = []
        for position, info in sorted(
            summary["by_lineup_position"].items(),
            key=lambda row: safe_int(row[0].replace("#", ""), 99),
        ):
            graded_position = info["win"] + info["loss"]
            position_win_rate = (info["win"] / graded_position * 100) if graded_position else 0
            if graded_position:
                lineup_lines.append(
                    f"{position}: {position_win_rate:.1f}% win ({info['total']} sent)"
                )
            else:
                lineup_lines.append(f"{position}: no graded bets ({info['total']} sent)")
        lines.extend(["", "By lineup position:", "\n".join(lineup_lines)])

    if summary["skipped_reasons"]:
        skipped_lines = [
            f"{reason}: {count}"
            for reason, count in sorted(
                summary["skipped_reasons"].items(),
                key=lambda item: item[1],
                reverse=True,
            )[:5]
        ]
        lines.extend(["", "Top skipped reasons:", "\n".join(skipped_lines)])

    if summary["winner_scores"] or summary["loser_scores"]:
        avg_win = (
            sum(summary["winner_scores"]) / len(summary["winner_scores"])
            if summary["winner_scores"]
            else 0
        )
        avg_loss = (
            sum(summary["loser_scores"]) / len(summary["loser_scores"])
            if summary["loser_scores"]
            else 0
        )
        lines.extend([
            "",
            f"Avg score winners: {avg_win:.1f}" if avg_win else "Avg score winners: n/a",
            f"Avg score losers: {avg_loss:.1f}" if avg_loss else "Avg score losers: n/a",
        ])

    if summary["recent"]:
        recent_lines = [
            f"{alert['id']} | {alert.get('status', 'open')} | "
            f"{alert.get('alert_type', 'UNKNOWN')} | {alert.get('target', alert.get('team', 'Unknown'))}"
            for alert in summary["recent"]
        ]
        lines.extend(["", "Recent:", "\n".join(recent_lines)])

    return "\n".join(lines)


def build_pending_alerts(limit=MAX_RECAP_ITEMS):
    alerts = [
        alert
        for alert in load_result_store().get("alerts", [])
        if alert.get("status", "open") == "open"
        and alert.get("sent", True) is True
    ]
    alerts.sort(key=lambda item: parse_iso_datetime(item.get("sent_at")), reverse=True)

    if not alerts:
        return "No open tracked alerts."

    lines = ["Open tracked alerts:"]
    for alert in alerts[:limit]:
        lines.append(
            f"{alert['id']} | {alert.get('alert_type', 'UNKNOWN')} | "
            f"{alert.get('target', alert.get('team', 'Unknown'))} | "
            f"Score {alert.get('score', '?')}"
        )
    lines.append("")
    lines.append("Report with /win ID, /loss ID, /push ID, or /nomarket ID.")
    return "\n".join(lines)


def find_alert(alert_id):
    for alert in load_result_store().get("alerts", []):
        if str(alert.get("id")).lower() == str(alert_id).lower():
            return alert
    return None


def build_alert_details(alert_id):
    alert = find_alert(alert_id)
    if not alert:
        return f"I couldn't find alert ID {alert_id}.\n\n{build_pending_alerts()}"

    lines = [
        "Debug Breakdown",
        f"ID: {alert.get('id')}",
        f"Alert Type: {alert.get('alert_type', 'UNKNOWN')}",
        f"Tier: {alert.get('tier', 'n/a')}",
        f"Best Market: {alert.get('best_market', 'n/a')}",
        f"Final Score: {alert.get('score', 'n/a')}",
        f"Odds: {alert.get('odds', 'n/a')}",
        f"Profit Units: {safe_float(alert.get('profit_units')):+.2f}",
        f"Pressure: {alert.get('pressure_score', 'n/a')}",
        f"Market Confidence: {alert.get('market_confidence', 'n/a')}",
        f"Availability Risk: {alert.get('market_availability_risk', 'n/a')}",
        "",
        f"AVG: {safe_float(alert.get('player_avg')):.3f}",
        f"OBP: {safe_float(alert.get('player_obp')):.3f}",
        f"SLG: {safe_float(alert.get('player_slg')):.3f}",
        f"OPS: {safe_float(alert.get('player_ops')):.3f}",
        f"PA: {safe_int(alert.get('player_pa'))}",
        "",
        f"Pitcher: {alert.get('pitcher', 'n/a')}",
        f"Pitcher Weakness: {alert.get('pitcher_weakness', 'n/a')}",
        f"Pitcher ERA/WHIP/IP: {alert.get('pitcher_era', 'n/a')}/"
        f"{alert.get('pitcher_whip', 'n/a')}/{alert.get('pitcher_ip', 'n/a')}",
        f"Timing Boost: {alert.get('timing_boost', 'n/a')}",
        f"Game Spot: {alert.get('game_spot', 'n/a')}",
        f"Bases: {alert.get('base_state', 'n/a')}",
        f"Why: {alert.get('passed_reason', 'n/a')}",
        "",
        alert.get("early_explanation", ""),
    ]
    return "\n".join(lines)


def tracking_footer(alert_id):
    return (
        f"\nID: {alert_id}\n"
        "Tap a button below to report or view details."
    )


def alert_reply_markup(alert_id):
    return {
        "inline_keyboard": [
            [
                {"text": "Win", "callback_data": f"result|win|{alert_id}"},
                {"text": "Loss", "callback_data": f"result|loss|{alert_id}"},
            ],
            [
                {"text": "Push", "callback_data": f"result|push|{alert_id}"},
                {"text": "No Market", "callback_data": f"result|nomarket|{alert_id}"},
            ],
            [
                {"text": "Details", "callback_data": f"details|{alert_id}"},
            ],
        ]
    }


def send_telegram(chat_id, msg, reply_markup=None):
    url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    data = request_json("post", url, data=payload)
    if data.get("ok") is not True:
        raise RuntimeError(f"Telegram send failed: {data}")
    return data


def answer_callback_query(callback_query_id, text=None):
    url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        return request_json("post", url, data=payload)
    except Exception as exc:
        print("Telegram callback answer error:", exc, flush=True)
        return None


def get_sheet_subscribers():
    try:
        data = request_json("get", SHEET_WEBHOOK_URL)
        return set(str(x) for x in data.get("subscribers", []))
    except Exception as exc:
        print("Sheet subscriber error:", exc, flush=True)
        return set()


def save_subscriber(chat_id, username="", first_name="", status="active"):
    payload = {
        "chat_id": str(chat_id),
        "username": username,
        "first_name": first_name,
        "status": status,
    }

    try:
        data = request_json("post", SHEET_WEBHOOK_URL, json=payload)
        return data.get("ok") is True
    except Exception as exc:
        print("Sheet save error:", exc, flush=True)
        return False


def broadcast(msg, reply_markup=None):
    subscribers = get_sheet_subscribers()
    print(f"Broadcasting to {len(subscribers)} subscriber(s)", flush=True)
    for chat_id in subscribers:
        try:
            send_telegram(chat_id, msg, reply_markup=reply_markup)
        except Exception as exc:
            print(f"Send error to {chat_id}:", exc, flush=True)


def subscription_message():
    return (
        "Subscription Active\n\n"
        "You'll receive predictive MLB live betting alerts.\n\n"
        "The bot looks 2-4 batters ahead using the live batting order so you "
        "have more time before markets lock.\n\n"
        "Commands:\n"
        "/status - check status\n"
        "/recap - show recent alert results\n"
        "/markets - show market availability\n"
        "/training - show settled bet training ROI\n"
        "/pending - show open tracked alerts\n"
        "/details ID - show alert breakdown\n"
        "Use the buttons under each alert to report results.\n"
        "/stop - stop alerts\n"
        "/join - restart alerts"
    )


def parse_command(text):
    parts = (text or "").strip().split()
    if not parts:
        return "", []
    command = parts[0].split("@", 1)[0].lower()
    return command, parts[1:]


def outcome_response(alert, outcome):
    labels = {
        "win": "win",
        "loss": "loss",
        "push": "push/void",
        "no_market": "no market/locked",
        "didnt_bet": "didn't bet",
    }
    return (
        f"Recorded {labels.get(outcome, outcome)} for {alert['id']}.\n\n"
        f"{build_results_recap()}"
    )


def handle_callback_query(update):
    callback = update.get("callback_query")
    if not callback:
        return False

    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = callback.get("from", {}).get("id", chat_id)
    data = callback.get("data", "")

    if not chat_id or not data:
        if callback_id:
            answer_callback_query(callback_id, "Could not read that button.")
        return True

    parts = data.split("|", 2)

    if len(parts) == 2 and parts[0] == "details":
        alert_id = parts[1]
        answer_callback_query(callback_id, "Opening details.")
        send_telegram(chat_id, build_alert_details(alert_id))
        return True

    if len(parts) == 3 and parts[0] == "result":
        action = parts[1]
        alert_id = parts[2]
        outcome = CALLBACK_ACTIONS.get(action)
        if not outcome:
            answer_callback_query(callback_id, "Unknown report button.")
            return True

        alert = record_alert_outcome(alert_id, outcome, user_id)
        if alert:
            answer_callback_query(callback_id, "Result recorded.")
            send_telegram(chat_id, outcome_response(alert, outcome))
        else:
            answer_callback_query(callback_id, "Alert not found.")
            send_telegram(chat_id, f"I couldn't find alert ID {alert_id}.\n\n{build_pending_alerts()}")
        return True

    answer_callback_query(callback_id, "Unknown button.")
    return True


def check_telegram_messages():
    global last_update_id

    url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/getUpdates"
    params = {}

    if last_update_id is not None:
        params["offset"] = last_update_id + 1

    try:
        data = request_json("get", url, params=params)
    except Exception as exc:
        print("Telegram update error:", exc, flush=True)
        return

    for update in data.get("result", []):
        last_update_id = update.get("update_id", last_update_id)
        save_last_update_id(last_update_id)

        if handle_callback_query(update):
            continue

        message = update.get("message", {})
        chat = message.get("chat", {})

        chat_id = chat.get("id")
        username = chat.get("username", "")
        first_name = chat.get("first_name", "")
        text = message.get("text", "")
        command, args = parse_command(text)

        if not chat_id:
            continue

        settlement_response = handle_settlement_reply(chat_id, text)
        if settlement_response and not command.startswith("/"):
            send_telegram(chat_id, settlement_response)
            continue

        if command in ["/start", "/join"]:
            if save_subscriber(chat_id, username, first_name, "active"):
                send_telegram(chat_id, subscription_message())
            else:
                send_telegram(chat_id, "Subscription failed. Send /join again.")

        elif command == "/stop":
            if save_subscriber(chat_id, username, first_name, "inactive"):
                send_telegram(chat_id, "Alerts stopped.\n\nSend /join to restart.")
            else:
                send_telegram(chat_id, "Stop failed. Send /stop again.")

        elif command == "/status":
            subscribers = get_sheet_subscribers()
            if str(chat_id) in subscribers:
                send_telegram(chat_id, "Bot is online.\n\nSubscription Status: ACTIVE")
            else:
                send_telegram(
                    chat_id,
                    "Bot is online, but you are NOT active.\n\nSend /join.",
                )

        elif command in ["/recap", "/results"]:
            send_telegram(chat_id, build_results_recap())

        elif command == "/markets":
            send_telegram(chat_id, build_market_report())

        elif command in ["/training", "/trainreport"]:
            send_telegram(chat_id, build_training_report())

        elif command == "/trainbet":
            parsed = parse_trainbet_args(args)
            if not parsed or not parsed[0]:
                send_telegram(
                    chat_id,
                    "Send result, odds, stake, and market.\n\n"
                    "Example:\n"
                    "/trainbet win +340 1 Player Hits | Sam Antonacci 2+ hits",
                )
                continue
            outcome, odds, stake, market, note = parsed
            bet = record_training_bet(
                outcome,
                odds,
                stake=stake,
                market=market,
                note=note,
                source=f"telegram:{chat_id}",
            )
            if not bet:
                send_telegram(chat_id, "I couldn't log that training bet. Check the format.")
                continue
            send_telegram(
                chat_id,
                "Training bet logged.\n\n"
                f"{bet['market']}\n"
                f"Result: {bet['status']}\n"
                f"Odds: {bet['odds']}\n"
                f"Units: {safe_float(bet['profit_units']):+.2f}\n\n"
                f"{build_training_report()}",
            )

        elif command == "/pending":
            send_telegram(chat_id, build_pending_alerts())

        elif command == "/details":
            if not args:
                send_telegram(
                    chat_id,
                    "Send the alert ID too. Example: /details 0624-823850-1T-GR-673962",
                )
                continue
            send_telegram(chat_id, build_alert_details(args[0]))

        elif command == "/settle":
            if not args:
                send_telegram(
                    chat_id,
                    "Send the alert ID too. Example: /settle 0624-823850-1T-GR-673962",
                )
                continue
            pending_settlements[str(chat_id)] = args[0]
            send_telegram(chat_id, settlement_prompt(args[0]))

        elif command in OUTCOME_COMMANDS:
            if not args:
                send_telegram(
                    chat_id,
                    "Send the alert ID too. Example: /win 0623-12345-6T-GR-67890",
                )
                continue

            outcome = OUTCOME_COMMANDS[command]
            odds = args[1] if len(args) > 1 else None
            alert = record_alert_outcome(args[0], outcome, chat_id, odds=odds)
            if alert:
                send_telegram(chat_id, outcome_response(alert, outcome))
            else:
                send_telegram(
                    chat_id,
                    f"I couldn't find alert ID {args[0]}.\n\n{build_pending_alerts()}",
                )

        else:
            send_telegram(
                chat_id,
                "MLB Betting Alert Bot\n\n"
                "Send /join to activate alerts.\n"
                "Send /status to check status.\n"
                "Send /recap to see results.\n"
                "Send /markets to see market availability.\n"
                "Send /training to see settled bet training ROI.\n"
                "Send /pending to see open alerts.\n"
                "Send /details ID to see alert breakdown.\n"
                "Send /settle ID to quickly report a result.\n"
                "Send /stop to stop alerts.",
            )


def get_today_games(today=None):
    today = today or datetime.now()
    date_text = today.strftime("%Y-%m-%d")
    url = f"{MLB_API_BASE}/v1/schedule?sportId=1&date={date_text}"

    try:
        data = request_json("get", url)
    except Exception as exc:
        print("Schedule error:", exc, flush=True)
        return []

    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            status = game.get("status", {}).get("abstractGameState")
            if status == "Live":
                games.append(game.get("gamePk"))

    return games


def get_player_season_stats(player_id, group):
    if not player_id:
        return {}

    cache_key = f"{group}-{player_id}"
    cached = cache_get(player_stats_cache, cache_key)
    if cached is not None:
        return cached

    url = (
        f"{MLB_API_BASE}/v1/people/{player_id}"
        f"?hydrate=stats(group=[{group}],type=[season])"
    )

    try:
        data = request_json("get", url)
        person = data.get("people", [{}])[0]
        stats_blocks = person.get("stats", [])

        if not stats_blocks:
            return cache_set(player_stats_cache, cache_key, {}, STATS_CACHE_SECONDS)

        splits = stats_blocks[0].get("splits", [])

        if not splits:
            return cache_set(player_stats_cache, cache_key, {}, STATS_CACHE_SECONDS)

        stats = splits[0].get("stat", {})
        return cache_set(player_stats_cache, cache_key, stats, STATS_CACHE_SECONDS)

    except Exception as exc:
        print(f"Stats error {group} {player_id}:", exc, flush=True)
        return cache_set(player_stats_cache, cache_key, {}, 60)


def recently_reinstated_from_injury(player_id, player_name):
    if not player_id:
        return False, "No player id"

    if player_name and player_name.lower() in RECENT_INJURY_NAMES:
        return True, "Manual recent injury list"

    cache_key = f"injury-{player_id}"
    cached = cache_get(injury_cache, cache_key)
    if cached is not None:
        return cached

    end_date = datetime.now()
    start_date = end_date - timedelta(days=FRESH_INJURY_DAYS)

    url = (
        f"{MLB_API_BASE}/v1/transactions"
        f"?playerId={player_id}"
        f"&startDate={start_date.strftime('%Y-%m-%d')}"
        f"&endDate={end_date.strftime('%Y-%m-%d')}"
    )

    try:
        data = request_json("get", url)
        transactions = data.get("transactions", [])

        for tx in transactions:
            desc = (
                tx.get("description", "")
                or tx.get("typeDesc", "")
                or tx.get("typeCode", "")
            ).lower()

            if ("reinstated" in desc or "activated" in desc) and (
                "injured" in desc or "injury" in desc or " il" in desc
            ):
                result = True, desc[:120]
                return cache_set(injury_cache, cache_key, result, INJURY_CACHE_SECONDS)

        result = False, "No recent injury return found"
        return cache_set(injury_cache, cache_key, result, INJURY_CACHE_SECONDS)

    except Exception as exc:
        print(f"Injury check error {player_name}:", exc, flush=True)
        result = False, "Injury check unavailable"
        return cache_set(injury_cache, cache_key, result, 300)


def calculate_batter_profile(stats):
    avg = safe_float(stats.get("avg"))
    obp = safe_float(stats.get("obp"))
    slg = safe_float(stats.get("slg"))
    ops = safe_float(stats.get("ops"))

    hr = safe_int(stats.get("homeRuns"))
    rbi = safe_int(stats.get("rbi"))
    doubles = safe_int(stats.get("doubles"))
    triples = safe_int(stats.get("triples"))
    walks = safe_int(stats.get("baseOnBalls"))
    strikeouts = safe_int(stats.get("strikeOuts"))
    at_bats = safe_int(stats.get("atBats"))
    plate_appearances = safe_int(stats.get("plateAppearances"))

    if plate_appearances <= 0:
        plate_appearances = at_bats + walks

    pa = max(plate_appearances, 1)

    hr_rate = hr / pa
    bb_rate = walks / pa
    k_rate = strikeouts / pa
    xbh_rate = (doubles + triples + hr) / max(at_bats, 1)

    hit_score = 45 + (avg * 85) + (obp * 35) - (k_rate * 45)
    hrr_score = 45 + (avg * 55) + (obp * 35) + (slg * 25) + (bb_rate * 25) - (k_rate * 35)
    rbi_score = 45 + (obp * 25) + (slg * 42) + ((rbi / pa) * 110) + (bb_rate * 25) - (k_rate * 30)
    total_bases_score = 42 + (slg * 55) + (ops * 18) + (xbh_rate * 90) - (k_rate * 22)
    hr_score = 35 + (hr_rate * 800) + (slg * 38) + (xbh_rate * 95) + (ops * 12) - (k_rate * 15)

    return {
        "hit": clamp(hit_score),
        "hrr": clamp(hrr_score),
        "rbi": clamp(rbi_score),
        "total_bases": clamp(total_bases_score),
        "hr": clamp(hr_score),
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "hr_count": hr,
        "rbi_count": rbi,
        "hr_rate": hr_rate,
        "xbh_rate": xbh_rate,
        "k_rate": k_rate,
        "bb_rate": bb_rate,
        "pa": pa,
    }


def calculate_pitcher_profile(stats):
    era = safe_float(stats.get("era"))
    whip = safe_float(stats.get("whip"))
    home_runs = safe_int(stats.get("homeRuns"))
    walks = safe_int(stats.get("baseOnBalls"))
    strikeouts = safe_int(stats.get("strikeOuts"))
    innings = safe_float(stats.get("inningsPitched"))
    hits = safe_int(stats.get("hits"))

    ip = max(innings, 1.0)
    reliable = innings >= 15 and not (era == 0 and whip == 0)
    hr9 = home_runs * 9 / ip
    bb9 = walks * 9 / ip
    k9 = strikeouts * 9 / ip
    h9 = hits * 9 / ip

    weakness = 0

    if era >= 5.00:
        weakness += 12
    elif era >= 4.25:
        weakness += 7
    elif era <= 3.25:
        weakness -= 10

    if whip >= 1.50:
        weakness += 15
    elif whip >= 1.35:
        weakness += 9
    elif whip <= 1.10:
        weakness -= 10

    if bb9 >= 4.0:
        weakness += 10
    elif bb9 <= 2.0:
        weakness -= 5

    if h9 >= 9.5:
        weakness += 9
    elif h9 <= 7.0:
        weakness -= 6

    if hr9 >= 1.40:
        weakness += 9
    elif hr9 <= 0.80:
        weakness -= 7

    if not reliable:
        weakness -= 8

    return {
        "weakness": weakness,
        "era": era,
        "whip": whip,
        "ip": innings,
        "reliable": reliable,
        "hr9": hr9,
        "bb9": bb9,
        "k9": k9,
        "h9": h9,
    }


def calculate_count_edge(balls, strikes):
    balls = safe_int(balls)
    strikes = safe_int(strikes)

    if balls >= 3 and strikes <= 1:
        return 8
    if balls == 3 and strikes == 2:
        return 3
    if balls == 2 and strikes == 0:
        return 7
    if strikes == 2 and balls <= 1:
        return -8
    return 0


def calculate_outs_edge(outs):
    outs = safe_int(outs)

    if outs == 0:
        return 8
    if outs == 1:
        return 5
    if outs == 2:
        return -5
    return 0


def event_is_runner_reached(event):
    event = (event or "").lower()
    return event in [
        "single",
        "double",
        "triple",
        "home_run",
        "walk",
        "hit_by_pitch",
        "field_error",
        "catcher_interf",
        "intent_walk",
    ]


def event_is_hit(event):
    return (event or "").lower() in ["single", "double", "triple", "home_run"]


def event_is_walk(event):
    return (event or "").lower() in ["walk", "intent_walk"]


def get_inning_pressure(data, inning, half):
    plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])

    hits = 0
    walks = 0
    hbp = 0
    runs = 0
    consecutive_reached = 0
    max_consecutive_reached = 0

    for play in plays:
        about = play.get("about", {})
        result = play.get("result", {})

        if safe_int(about.get("inning")) != safe_int(inning):
            continue

        if about.get("halfInning", "").lower() != str(half).lower():
            continue

        event = result.get("eventType", "")
        rbi = safe_int(result.get("rbi"))

        if event_is_hit(event):
            hits += 1
        if event_is_walk(event):
            walks += 1
        if event == "hit_by_pitch":
            hbp += 1

        runs += rbi

        if event_is_runner_reached(event):
            consecutive_reached += 1
            max_consecutive_reached = max(max_consecutive_reached, consecutive_reached)
        else:
            consecutive_reached = 0

    return {
        "hits": hits,
        "walks": walks,
        "hbp": hbp,
        "runs": runs,
        "consecutive_reached": max_consecutive_reached,
    }


def runners_summary(offense):
    bases = []
    if "first" in offense:
        bases.append("1st")
    if "second" in offense:
        bases.append("2nd")
    if "third" in offense:
        bases.append("3rd")

    if len(bases) == 3:
        return "Bases loaded"
    if not bases:
        return "Bases empty"
    return "Runner on " + "/".join(bases)


def runner_score(offense):
    score = 0

    if "first" in offense:
        score += 3
    if "second" in offense:
        score += 8
    if "third" in offense:
        score += 10

    if "first" in offense and "second" in offense and "third" in offense:
        score += 12

    return score


def calculate_pressure_score(offense, pitcher, inning_pressure, outs, inning):
    pressure = 35
    pressure += runner_score(offense)
    pressure += pitcher["weakness"]
    pressure += inning_pressure["hits"] * 6
    pressure += inning_pressure["walks"] * 8
    pressure += inning_pressure["hbp"] * 8
    pressure += inning_pressure["consecutive_reached"] * 7
    pressure += calculate_outs_edge(outs)

    inn = safe_int(inning)

    if 2 <= inn <= 6:
        pressure += 10
    elif inn == 7:
        pressure += 2
    elif inn >= 8:
        pressure -= 10

    return clamp(pressure)


def get_current_pitcher(data):
    live_data = data.get("liveData", {})
    plays = live_data.get("plays", {})
    matchup_pitcher = (
        plays.get("currentPlay", {})
        .get("matchup", {})
        .get("pitcher", {})
    )
    if matchup_pitcher.get("id"):
        return {
            "id": matchup_pitcher.get("id"),
            "name": matchup_pitcher.get("fullName", "Unknown pitcher"),
        }

    defense_pitcher = live_data.get("linescore", {}).get("defense", {}).get("pitcher", {})
    if defense_pitcher.get("id"):
        return {
            "id": defense_pitcher.get("id"),
            "name": defense_pitcher.get("fullName", "Unknown pitcher"),
        }

    boxscore = live_data.get("boxscore", {})
    defense_team_id = live_data.get("linescore", {}).get("defense", {}).get("team", {}).get("id")

    for side in ["away", "home"]:
        team = boxscore.get("teams", {}).get(side, {})
        if defense_team_id and team.get("team", {}).get("id") != defense_team_id:
            continue
        for player_data in team.get("players", {}).values():
            position = player_data.get("position", {}).get("abbreviation", "")
            if position == "P":
                person = player_data.get("person", {})
                return {
                    "id": person.get("id"),
                    "name": person.get("fullName", "Unknown pitcher"),
                }

    return {"id": None, "name": "Unknown pitcher"}


def get_batting_order_targets(data, lookahead=4):
    boxscore = data.get("liveData", {}).get("boxscore", {})
    linescore = data.get("liveData", {}).get("linescore", {})
    offense = linescore.get("offense", {})
    current_batter_id = offense.get("batter", {}).get("id")
    offense_team_id = offense.get("team", {}).get("id")

    teams = boxscore.get("teams", {})

    batting_order = []
    players = {}

    for side in ["away", "home"]:
        team = teams.get(side, {})
        team_id = team.get("team", {}).get("id")

        if team_id == offense_team_id:
            batting_order = team.get("battingOrder", [])
            players = team.get("players", {})
            break

    if not batting_order or not current_batter_id:
        return []

    order_ids = [safe_int(x) for x in batting_order]

    try:
        current_index = order_ids.index(safe_int(current_batter_id))
    except ValueError:
        return []

    targets = []

    for offset in range(1, lookahead + 1):
        idx = (current_index + offset) % len(order_ids)
        pid = order_ids[idx]
        pdata = players.get(f"ID{pid}", {})
        person = pdata.get("person", {})

        if offset == 1:
            role = "On Deck"
        elif offset == 2:
            role = "2 Batters Away"
        elif offset == 3:
            role = "3 Batters Away"
        else:
            role = f"{offset} Batters Away"

        targets.append({
            "id": person.get("id", pid),
            "name": person.get("fullName", "Unknown"),
            "role": role,
            "batters_away": offset,
            "lineup_position": idx + 1,
        })

    return targets


def player_quality_gate(profile):
    return (
        profile["ops"] >= MIN_PLAYER_OPS
        and profile["slg"] >= MIN_PLAYER_SLG
        and profile["pa"] >= MIN_PLAYER_PA
    )


def has_power_profile(profile):
    return profile["slg"] >= MIN_POWER_SLG_FOR_HR or profile["hr_rate"] >= MIN_POWER_HR_RATE


def has_elite_player_profile(profile):
    return (
        profile["ops"] >= .850
        or profile["slg"] >= .500
        or profile["avg"] >= .290
        or has_power_profile(profile)
    )


def runners_likely_for_target(offense, inning_pressure):
    return has_runners_on(offense) or inning_pressure.get("consecutive_reached", 0) >= 2


def apply_score_context(raw_score, profile, pitcher, pressure_score, offense, inning):
    score = safe_float(raw_score)

    if pitcher["weakness"] < 0:
        score += pitcher["weakness"] * 0.65
    if not has_runners_on(offense):
        score -= 5
    if pressure_score < 60:
        score -= 8
    if profile["ops"] < MIN_PLAYER_OPS:
        score -= 7
    if profile["slg"] < MIN_PLAYER_SLG:
        score -= 7
    if safe_int(inning) == 1 and not has_runners_on(offense):
        score -= 6
    if not pitcher.get("reliable", True):
        score -= 8

    return normalize_score(score)


def score_player_target(target, pitcher, pressure_score, offense=None, inning=0, inning_pressure=None):
    offense = offense or {}
    inning_pressure = inning_pressure or {}
    stats = get_player_season_stats(target["id"], "hitting")
    profile = calculate_batter_profile(stats)

    away = safe_int(target.get("batters_away", 1))

    timing_boost = 0
    if away == PREFERRED_MARKET_DISTANCE:
        timing_boost = 10
    elif away == 2:
        timing_boost = 6
    elif away == 4:
        timing_boost = 5
    elif away == 1:
        timing_boost = -10

    raw_hit = profile["hit"] + pitcher["weakness"] * 0.45 + pressure_score * 0.14 + timing_boost
    raw_hrr = profile["hrr"] + pitcher["weakness"] * 0.45 + pressure_score * 0.18 + timing_boost
    raw_rbi = profile["rbi"] + pitcher["weakness"] * 0.50 + pressure_score * 0.20 + timing_boost
    raw_tb = profile["total_bases"] + pitcher["weakness"] * 0.45 + pressure_score * 0.14 + timing_boost
    raw_hr = profile["hr"] + pitcher["weakness"] * 0.35 + pressure_score * 0.08 + timing_boost

    hit_market = apply_score_context(raw_hit, profile, pitcher, pressure_score, offense, inning)
    hrr_market = apply_score_context(raw_hrr, profile, pitcher, pressure_score, offense, inning)
    rbi_market = apply_score_context(raw_rbi, profile, pitcher, pressure_score, offense, inning)
    tb_market = apply_score_context(raw_tb, profile, pitcher, pressure_score, offense, inning)
    hr_market = apply_score_context(raw_hr, profile, pitcher, pressure_score, offense, inning)

    if not has_power_profile(profile):
        hr_market = min(hr_market, 88)
    if not runners_likely_for_target(offense, inning_pressure):
        rbi_market = min(rbi_market, 88)

    return {
        "target": target,
        "profile": profile,
        "timing_boost": timing_boost,
        "quality_gate": player_quality_gate(profile),
        "power_profile": has_power_profile(profile),
        "elite_profile": has_elite_player_profile(profile),
        "hit": hit_market,
        "hrr": hrr_market,
        "rbi": rbi_market,
        "total_bases": tb_market,
        "hr": hr_market,
        "best_score": max(hit_market, hrr_market, rbi_market, tb_market, hr_market),
    }


def market_path(market, team_name=None):
    if market == "Player Hits":
        return "Live Player Props -> Player Hits"
    if market == "Player H+R+RBI":
        return "Live Player Props -> Player Hits+Runs+RBIs"
    if market == "Player RBI":
        return "Live Player Props -> Player RBIs"
    if market == "Player Total Bases":
        return "Live Player Props -> Player Total Bases"
    if market == "Player Home Run":
        return "Live Player Props -> Player Home Runs"
    if market == "Team Total Over":
        return f"Hits and Runs -> {team_name} Alt. Total Runs\nor Hits and Runs -> Team Total Runs"
    if market == "Inning Total Runs":
        return "Innings -> Inning Total Runs\nor Innings -> All Innings O/U 0.5 Runs"
    if market == "Game Total Over":
        return "Live SGP -> Game Lines -> Total -> Over"
    return "Check Live Player Props, Hits and Runs, or Innings"


def has_runners_on(offense):
    return any(base in offense for base in ["first", "second", "third"])


def top_player_markets(
    player_score,
    min_score=MIN_PLAYER_MARKET_SCORE,
    max_markets=MAX_MARKETS_PER_ALERT,
    runners_on=True,
):
    name = player_score["target"]["name"]

    markets = [
        ("Player H+R+RBI", player_score["hrr"], f"{name} Hits+Runs+RBIs"),
        ("Player Total Bases", player_score["total_bases"], f"{name} Total Bases Over"),
        ("Player Hits", player_score["hit"], f"{name} 1+ Hit"),
        ("Player RBI", player_score["rbi"], f"{name} RBI"),
        ("Player Home Run", player_score["hr"], f"{name} Home Run"),
    ]
    enabled = {
        "Player H+R+RBI": MARKET_ENABLED_HRR,
        "Player Total Bases": MARKET_ENABLED_TOTAL_BASES,
        "Player Hits": MARKET_ENABLED_HITS,
        "Player RBI": MARKET_ENABLED_RBI,
        "Player Home Run": MARKET_ENABLED_HR,
    }
    markets = [
        (market, score, label)
        for market, score, label in markets
        if enabled.get(market, True)
    ]
    markets = [
        (market, calibrated_market_score(market, score), label)
        for market, score, label in markets
    ]

    filtered = []
    best_score = max((score for _, score, _ in markets), default=0)

    for market, score, label in markets:
        if score < max(min_score, MIN_MARKET_DISPLAY_SCORE):
            continue
        if market in ["Player RBI", "Player Home Run"] and not runners_on:
            continue
        if market == "Player Home Run":
            if score < 94 or not player_score.get("power_profile"):
                continue
        if best_score - score > SECONDARY_MARKET_MAX_DROP:
            continue
        filtered.append((market, score, label))
        if len(filtered) >= max_markets:
            break

    return filtered


def best_qualified_market_score(player_score, min_score=MIN_PLAYER_MARKET_SCORE, runners_on=True):
    markets = top_player_markets(
        player_score,
        min_score=min_score,
        max_markets=1,
        runners_on=runners_on,
    )
    if not markets:
        return 0
    return markets[0][1]


def is_low_quality_timing(outs, strikes):
    return safe_int(outs) >= 2 and safe_int(strikes) >= 2


def pitcher_context_allows_alert(pitcher, pressure_score, bases_loaded):
    if pitcher["weakness"] > 0:
        return True
    if bases_loaded and pressure_score >= STRONG_PITCHER_PRESSURE_SCORE:
        return True
    return False


def cold_opening_context(inning, offense, pressure_score):
    return safe_int(inning) == 1 and not has_runners_on(offense) and pressure_score < 94


def alert_tier(score, pressure_score, alert_type):
    score = display_score(score)
    pressure_score = display_score(pressure_score)
    if alert_type == "LIVE_BET" or score >= 94 or pressure_score >= 94:
        return "GOLD"
    if alert_type == "PRESSURE" and pressure_score >= MIN_PRESSURE_SCORE:
        return "GOLD"
    if score >= 92 and pressure_score >= 75:
        return "GOLD"
    if score >= 90:
        return "SILVER"
    return "WATCHLIST"


def market_confidence(score):
    shown = display_score(score)
    if shown >= 94:
        return "Elite"
    if shown >= 92:
        return "High"
    if shown >= 90:
        return "Medium"
    return "Watchlist"


def market_availability_risk(alert_type, batters_away, market):
    batters_away = safe_int(batters_away)
    if alert_type in ["PRESSURE", "LIVE_BET"]:
        return "Low"
    if batters_away >= PREFERRED_MARKET_DISTANCE and market in ["Player H+R+RBI", "Player Total Bases", "Player Hits"]:
        return "Low"
    if batters_away >= 2:
        return "Medium"
    return "High"


def tier_can_send(tier):
    return tier == "GOLD" or (tier == "SILVER" and SEND_SILVER_ALERTS)


def global_throttle_allows(game_pk, team, player_id, score, now=None):
    global last_global_alert_time

    now = now or time.time()
    game_key = str(game_pk)
    team_key = f"{game_pk}:{team}"
    player_key = f"{game_pk}:{player_id}"

    if last_global_alert_time and now - last_global_alert_time < GLOBAL_ALERT_COOLDOWN_SECONDS:
        return False, "global cooldown"

    if game_alerts.get(game_key, 0) >= MAX_ALERTS_PER_GAME:
        return False, "game alert cap"
    if team_game_alerts.get(team_key, 0) >= MAX_ALERTS_PER_TEAM_PER_GAME:
        return False, "team game alert cap"

    player_info = player_game_alerts.get(player_key)
    if player_info:
        if player_info["count"] >= MAX_ALERTS_PER_PLAYER_PER_GAME:
            if score < player_info["best_score"] + PLAYER_SCORE_IMPROVEMENT:
                return False, "player game alert cap"
        elif score < player_info["best_score"] + PLAYER_SCORE_IMPROVEMENT:
            return False, "player score did not improve enough"

    return True, ""


def record_global_alert(game_pk, team, player_id, score, now=None):
    global last_global_alert_time

    now = now or time.time()
    game_key = str(game_pk)
    team_key = f"{game_pk}:{team}"
    player_key = f"{game_pk}:{player_id}"

    last_global_alert_time = now
    game_alerts[game_key] = game_alerts.get(game_key, 0) + 1
    team_game_alerts[team_key] = team_game_alerts.get(team_key, 0) + 1
    player_info = player_game_alerts.setdefault(player_key, {"count": 0, "best_score": 0})
    player_info["count"] += 1
    player_info["best_score"] = max(player_info["best_score"], score)


def build_market_lines(markets, team_name=None):
    lines = []

    for idx, (market, score, label) in enumerate(markets, start=1):
        lines.append(
            f"{idx}. {label}\n"
            f"   Market: {market}\n"
            f"   Find it: {market_path(market, team_name=team_name)}\n"
            f"   Score: {display_score(score)}/100 {grade(score)}"
        )

    return "\n\n".join(lines)


def build_short_market_line(prefix, market, team_name=None):
    market_name, score, label = market
    return (
        f"{prefix}: {label}\n"
        f"Market Confidence: {market_confidence(score)} ({display_score(score)}/100)\n"
        f"Find it: {market_path(market_name, team_name=team_name)}"
    )


def should_send_alert(key, score):
    now = time.time()
    prune_sent_alerts(now)
    info = sent_alerts.get(key)

    if not info:
        sent_alerts[key] = {
            "count": 1,
            "last_time": now,
            "best_score": score,
        }
        return True

    if info["count"] >= MAX_ALERTS_PER_HALF_INNING:
        return False

    if now - info["last_time"] < ALERT_COOLDOWN_SECONDS:
        return False

    if score < info["best_score"] + 5:
        return False

    info["count"] += 1
    info["last_time"] = now
    info["best_score"] = score
    return True


def format_score_debug(player_score, pitcher, pressure_score):
    profile = player_score["profile"]
    return (
        f"Debug: player avg/obp/slg {profile['avg']:.3f}/"
        f"{profile['obp']:.3f}/{profile['slg']:.3f}; "
        f"pitcher weakness {pitcher['weakness']}; "
        f"pressure {pressure_score}; "
        f"timing boost {player_score['timing_boost']}"
    )


def build_candidate_record(
    game_pk,
    alert_type,
    team,
    player_score,
    market,
    score,
    tier,
    sent,
    skip_reason,
    inning,
    outs,
    base_text,
    pitcher_obj,
    pitcher,
):
    profile = player_score.get("profile", {})
    target = player_score.get("target", {})
    market_name = market[0] if market else ""
    return {
        "timestamp": utc_now().isoformat(),
        "game_pk": game_pk,
        "alert_type": alert_type,
        "player": target.get("name", ""),
        "player_id": target.get("id", ""),
        "team": team,
        "market": market_name,
        "score": display_score(score),
        "pressure": player_score.get("pressure_score", ""),
        "tier": tier,
        "sent": bool(sent),
        "skip_reason": skip_reason,
        "inning": inning,
        "outs": outs,
        "bases": base_text,
        "bases_loaded": base_text == "Bases loaded",
        "batters_away": target.get("batters_away", ""),
        "lineup_position": target.get("lineup_position", ""),
        "pitcher": pitcher_obj.get("name", ""),
        "pitcher_id": pitcher_obj.get("id", ""),
        "pitcher_era": pitcher.get("era"),
        "pitcher_whip": pitcher.get("whip"),
        "pitcher_ip": pitcher.get("ip"),
        "player_avg": profile.get("avg"),
        "player_obp": profile.get("obp"),
        "player_slg": profile.get("slg"),
        "player_ops": profile.get("ops"),
        "player_pa": profile.get("pa"),
        "result": "pending",
    }


def build_pass_reasons(player_score, pitcher, pressure_score, base_text):
    profile = player_score.get("profile", {})
    reasons = [
        f"{profile.get('avg', 0):.3f} AVG",
        "Timing window open",
        "Props likely still available",
    ]
    if pitcher.get("weakness", 0) >= 5:
        reasons.insert(1, "Favorable pitcher matchup")
    elif pressure_score >= 75:
        reasons.insert(1, f"Pressure building with {base_text.lower()}")
    if player_score.get("quality_gate"):
        reasons.append("Player quality gate passed")
    return reasons[:4]


def build_early_explanation(current_batter, targets, target):
    current_name = current_batter.get("fullName") or current_batter.get("name") or "Current batter"
    on_deck = next((item for item in targets if item.get("batters_away") == 1), None)
    on_deck_name = on_deck.get("name") if on_deck else "Unknown"
    return (
        "WHY THIS ALERT IS EARLY\n"
        f"{target['name']}\n"
        f"{target['batters_away']} batters away\n\n"
        f"Current batter: {current_name}\n"
        f"On deck: {on_deck_name}\n"
        f"Target: {target['name']}\n\n"
        "Markets usually disappear when the batter is on deck.\n"
        "This alert fired early to preserve market availability."
    )


def build_get_ready_alert(
    team,
    target_score,
    pressure_score,
    game_spot,
    base_text,
    inning_pressure,
    pitcher,
    runners_on=True,
):
    target = target_score["target"]
    markets = top_player_markets(
        target_score,
        min_score=MIN_PLAYER_MARKET_SCORE,
        runners_on=runners_on,
    )
    best_market = markets[0]
    backup_market = markets[1] if len(markets) > 1 and display_score(markets[1][1]) >= MIN_MARKET_DISPLAY_SCORE else None
    tier = target_score.get("tier", "GOLD")
    target_title = f"{target['name']}\n{target['role']}"
    reasons = target_score.get("passed_reasons", [
        "Player profile cleared filters",
        "Favorable timing window",
        "Props likely still available",
    ])
    reason_lines = "\n".join(f"- {reason}" for reason in reasons[:4])

    message = (
        "GET READY ALERT\n\n"
        f"{target_title}\n\n"
        "BEST BET\n"
        f"{best_market[2]}\n"
        f"{display_score(best_market[1])}/100 {grade(best_market[1])}\n"
        f"Find:\n{market_path(best_market[0], team_name=team)}\n"
    )
    if backup_market:
        message += (
            "\nBACKUP\n"
            f"{backup_market[2]}\n"
            f"{display_score(backup_market[1])}/100 {grade(backup_market[1])}\n"
        )

    return message + (
        "\nGame:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Why It Passed:\n"
        f"{reason_lines}\n"
        f"Tier: {tier}\n\n"
        f"{target_score.get('early_explanation', '')}"
    )


def build_matchup_alert(
    team,
    target_score,
    pitcher,
    game_spot,
    base_text,
    pressure_score,
    runners_on=True,
):
    target = target_score["target"]
    markets = top_player_markets(
        target_score,
        min_score=MIN_MATCHUP_MARKET_SCORE,
        runners_on=runners_on,
    )
    best_market = markets[0]
    backup_market = markets[1] if len(markets) > 1 and display_score(markets[1][1]) >= MIN_MARKET_DISPLAY_SCORE else None
    tier = target_score.get("tier", "GOLD")
    target_title = f"{target['name']}\n{target['role']}"
    reasons = target_score.get("passed_reasons", [
        "Player passed quality gates",
        "Best market cleared elite matchup threshold",
        "Pitcher or player profile supports the edge",
    ])
    reason_lines = "\n".join(f"- {reason}" for reason in reasons[:4])

    message = (
        "MATCHUP ALERT\n\n"
        f"{target_title}\n\n"
        "BEST BET\n"
        f"{best_market[2]}\n"
        f"{display_score(best_market[1])}/100 {grade(best_market[1])}\n"
        f"Find:\n{market_path(best_market[0], team_name=team)}\n"
    )
    if backup_market:
        message += (
            "\nBACKUP\n"
            f"{backup_market[2]}\n"
            f"{display_score(backup_market[1])}/100 {grade(backup_market[1])}\n"
        )

    return message + (
        "\nGame:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Why It Passed:\n"
        f"{reason_lines}\n"
        f"Tier: {tier}\n\n"
        f"{target_score.get('early_explanation', '')}"
    )


def build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure, best_targets):
    return (
        "PRESSURE BUILDING\n\n"
        f"{team}\n\n"
        "BEST BET\n"
        f"{team} Team Total Over\n"
        f"{display_score(pressure_score)}/100 {grade(pressure_score)}\n"
        f"Find:\n{market_path('Team Total Over', team_name=team)}\n\n"
        "Game:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Why It Passed:\n"
        "- Team pressure is rising\n"
        "- Team markets are more likely available than one-pitch props\n"
        f"- This inning: {inning_pressure['hits']} hit(s), {inning_pressure['walks']} walk(s), "
        f"{inning_pressure['runs']} run(s), {inning_pressure['consecutive_reached']} straight reached\n"
        "Tier: GOLD"
    )


def check_game(game_pk):
    url = f"{MLB_API_BASE}/v1.1/game/{game_pk}/feed/live"

    try:
        data = request_json("get", url)
    except Exception as exc:
        print(f"Game feed error {game_pk}:", exc, flush=True)
        return

    linescore = data.get("liveData", {}).get("linescore", {})
    offense = linescore.get("offense", {})

    if not offense:
        return

    inning = linescore.get("currentInning", "?")
    inning_display = linescore.get("currentInningOrdinal", "?")
    half = linescore.get("inningHalf", "?").lower()
    half_display = linescore.get("inningHalf", "?")
    outs = linescore.get("outs", "?")

    bases_loaded = "first" in offense and "second" in offense and "third" in offense
    runners_on = has_runners_on(offense)

    if ONLY_BASES_LOADED and not bases_loaded:
        return

    count = data.get("liveData", {}).get("plays", {}).get("currentPlay", {}).get("count", {})
    balls = safe_int(count.get("balls"))
    strikes = safe_int(count.get("strikes"))

    team = offense.get("team", {}).get("name", "Unknown team")

    pitcher_obj = get_current_pitcher(data)
    pitcher_stats = get_player_season_stats(pitcher_obj["id"], "pitching")
    pitcher = calculate_pitcher_profile(pitcher_stats)

    inning_pressure = get_inning_pressure(data, inning, half)
    pressure_score = calculate_pressure_score(offense, pitcher, inning_pressure, outs, inning)

    targets = get_batting_order_targets(data, LOOKAHEAD_BATTERS)

    scored_targets = []

    for target in targets:
        if not target["id"] or target["name"] == "Unknown":
            continue

        injured, injury_reason = recently_reinstated_from_injury(target["id"], target["name"])
        if injured:
            print(f"Skipping {target['name']}: injury risk - {injury_reason}", flush=True)
            continue

        player_score = score_player_target(
            target=target,
            pitcher=pitcher,
            pressure_score=pressure_score,
            offense=offense,
            inning=inning,
            inning_pressure=inning_pressure,
        )
        player_score["pressure_score"] = display_score(pressure_score)
        player_score["qualified_score"] = best_qualified_market_score(
            player_score,
            min_score=MIN_PLAYER_MARKET_SCORE,
            runners_on=runners_on,
        )
        player_score["matchup_qualified_score"] = best_qualified_market_score(
            player_score,
            min_score=MIN_MATCHUP_MARKET_SCORE,
            runners_on=runners_on,
        )
        scored_targets.append(player_score)

    if not scored_targets:
        return

    scored_targets.sort(key=lambda x: x["best_score"], reverse=True)

    early_targets = [
        target
        for target in scored_targets
        if safe_int(target["target"]["batters_away"]) >= MIN_TARGET_BATTERS_AWAY
        and safe_int(target["target"]["batters_away"]) <= MAX_TARGET_BATTERS_AWAY
    ]

    if not early_targets:
        print(f"{team}: no early targets available", flush=True)
        return

    early_targets.sort(key=lambda x: (x["qualified_score"], x["best_score"]), reverse=True)
    best_target = early_targets[0]

    game_spot = f"{half_display} {inning_display} | {outs} outs | Count {balls}-{strikes}"
    base_text = runners_summary(offense)

    for lower_target in early_targets[1:]:
        lower_markets = top_player_markets(
            lower_target,
            min_score=MIN_PLAYER_MARKET_SCORE,
            runners_on=runners_on,
        )
        lower_market = lower_markets[0] if lower_markets else None
        lower_score = lower_market[1] if lower_market else lower_target["best_score"]
        record_candidate(build_candidate_record(
            game_pk,
            "CANDIDATE",
            team,
            lower_target,
            lower_market,
            lower_score,
            alert_tier(lower_score, pressure_score, "MATCHUP"),
            False,
            "lower ranked candidate",
            inning,
            outs,
            base_text,
            pitcher_obj,
            pitcher,
        ))

    msg = None
    alert_type = None
    alert_score = 0
    alert_market = None
    alert_tier_value = "WATCHLIST"

    skip_reason = None

    if is_low_quality_timing(outs, strikes):
        skip_reason = "two strikes with two outs"
    elif cold_opening_context(inning, offense, pressure_score):
        skip_reason = "first inning bases empty"

    for target_score in early_targets:
        markets = top_player_markets(
            target_score,
            min_score=MIN_PLAYER_MARKET_SCORE,
            runners_on=runners_on,
        )
        candidate_market = markets[0] if markets else None
        candidate_score = candidate_market[1] if candidate_market else target_score["best_score"]
        candidate_tier = alert_tier(candidate_score, pressure_score, "MATCHUP")
        reason = skip_reason

        if not reason and not markets:
            reason = "no market cleared display threshold"
        if not reason and pressure_score < MIN_ALERT_PRESSURE_SCORE:
            reason = f"pressure below {MIN_ALERT_PRESSURE_SCORE}"
        if not reason and not pitcher_context_allows_alert(pitcher, pressure_score, bases_loaded):
            reason = "pitcher is not weak enough without bases-loaded pressure"

        if reason:
            record_candidate(build_candidate_record(
                game_pk,
                "MATCHUP",
                team,
                target_score,
                candidate_market,
                candidate_score,
                candidate_tier,
                False,
                reason,
                inning,
                outs,
                base_text,
                pitcher_obj,
                pitcher,
            ))

    player_markets = top_player_markets(
        best_target,
        min_score=MIN_PLAYER_MARKET_SCORE,
        runners_on=runners_on,
    )
    matchup_markets = top_player_markets(
        best_target,
        min_score=MIN_MATCHUP_MARKET_SCORE,
        runners_on=runners_on,
    )
    player_context_ok = (
        pressure_score >= MIN_ALERT_PRESSURE_SCORE
        and pitcher_context_allows_alert(pitcher, pressure_score, bases_loaded)
        and not cold_opening_context(inning, offense, pressure_score)
    )

    if not skip_reason and pressure_score >= 94 and player_context_ok and player_markets:
        alert_type = "LIVE_BET"
        alert_market = player_markets[0]
        alert_score = max(pressure_score, alert_market[1])
        alert_tier_value = "GOLD"
        best_target["tier"] = alert_tier_value
        best_target["passed_reasons"] = build_pass_reasons(best_target, pitcher, pressure_score, base_text)
        best_target["early_explanation"] = build_early_explanation(offense.get("batter", {}), targets, best_target["target"])
        msg = build_get_ready_alert(
            team,
            best_target,
            pressure_score,
            game_spot,
            base_text,
            inning_pressure,
            pitcher,
            runners_on=runners_on,
        ).replace("GET READY ALERT", "LIVE BET ALERT", 1)

    elif (
        not skip_reason
        and player_context_ok
        and best_target["qualified_score"] >= MIN_GET_READY_SCORE
        and pressure_score >= 75
        and (runners_on or inning_pressure["consecutive_reached"] >= 2)
        and player_markets
    ):
        alert_type = "GET_READY"
        alert_market = player_markets[0]
        alert_score = alert_market[1]
        alert_tier_value = alert_tier(alert_score, pressure_score, alert_type)
        best_target["tier"] = alert_tier_value
        best_target["passed_reasons"] = build_pass_reasons(best_target, pitcher, pressure_score, base_text)
        best_target["early_explanation"] = build_early_explanation(offense.get("batter", {}), targets, best_target["target"])
        msg = build_get_ready_alert(
            team,
            best_target,
            pressure_score,
            game_spot,
            base_text,
            inning_pressure,
            pitcher,
            runners_on=runners_on,
        )

    elif (
        not skip_reason
        and player_context_ok
        and best_target["matchup_qualified_score"] >= MIN_MATCHUP_SCORE
        and best_target["quality_gate"]
        and (pitcher["weakness"] >= 5 or best_target["elite_profile"])
        and matchup_markets
    ):
        alert_type = "MATCHUP"
        alert_market = matchup_markets[0]
        alert_score = alert_market[1]
        alert_tier_value = alert_tier(alert_score, pressure_score, alert_type)
        best_target["tier"] = alert_tier_value
        best_target["passed_reasons"] = build_pass_reasons(best_target, pitcher, pressure_score, base_text)
        best_target["early_explanation"] = build_early_explanation(offense.get("batter", {}), targets, best_target["target"])
        msg = build_matchup_alert(
            team,
            best_target,
            pitcher,
            game_spot,
            base_text,
            pressure_score,
            runners_on=runners_on,
        )

    elif not skip_reason and pressure_score >= MIN_PRESSURE_SCORE:
        alert_type = "PRESSURE"
        alert_score = pressure_score
        alert_market = ("Team Total Over", pressure_score, f"{team} Team Total Over")
        alert_tier_value = alert_tier(alert_score, pressure_score, alert_type)
        msg = build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure, early_targets)

    if not msg:
        reason = skip_reason or "alert rules not strong enough"
        record_candidate(build_candidate_record(
            game_pk,
            "CANDIDATE",
            team,
            best_target,
            alert_market,
            best_target.get("qualified_score", 0),
            alert_tier_value,
            False,
            reason,
            inning,
            outs,
            base_text,
            pitcher_obj,
            pitcher,
        ))
        print(
            f"{team} {game_spot} | Pitcher {pitcher_obj['name']} | "
            f"Pressure {pressure_score} | Best early target "
            f"{best_target['target']['name']} {best_target['target']['role']} "
            f"{best_target['qualified_score']} | skipped: {reason}",
            flush=True,
        )
        return

    if not tier_can_send(alert_tier_value):
        record_candidate(build_candidate_record(
            game_pk,
            alert_type,
            team,
            best_target,
            alert_market,
            alert_score,
            alert_tier_value,
            False,
            f"{alert_tier_value.lower()} alerts disabled",
            inning,
            outs,
            base_text,
            pitcher_obj,
            pitcher,
        ))
        print(f"Skipping {alert_type}: {alert_tier_value} alerts disabled", flush=True)
        return

    spot_key = f"{game_pk}-{inning}-{half}-{team}-{alert_type}-{best_target['target']['id']}"

    allowed, throttle_reason = global_throttle_allows(
        game_pk,
        team,
        best_target["target"]["id"],
        alert_score,
    )
    if not allowed:
        record_candidate(build_candidate_record(
            game_pk,
            alert_type,
            team,
            best_target,
            alert_market,
            alert_score,
            alert_tier_value,
            False,
            throttle_reason,
            inning,
            outs,
            base_text,
            pitcher_obj,
            pitcher,
        ))
        print(f"Skipping {alert_type}: {throttle_reason}", flush=True)
        return

    if not should_send_alert(spot_key, alert_score):
        record_candidate(build_candidate_record(
            game_pk,
            alert_type,
            team,
            best_target,
            alert_market,
            alert_score,
            alert_tier_value,
            False,
            "half-inning cooldown",
            inning,
            outs,
            base_text,
            pitcher_obj,
            pitcher,
        ))
        print(f"Skipping duplicate/cooldown: {spot_key}", flush=True)
        return

    alert_id = make_alert_id(
        game_pk,
        inning,
        half,
        alert_type,
        best_target["target"]["id"],
    )
    record_alert({
        "id": alert_id,
        "sent_at": utc_now().isoformat(),
        "game_pk": game_pk,
        "team": team,
        "alert_type": alert_type,
        "target": best_target["target"]["name"],
        "target_role": best_target["target"]["role"],
        "target_id": best_target["target"]["id"],
        "batters_away": best_target["target"].get("batters_away"),
        "lineup_position": best_target["target"].get("lineup_position"),
        "inning": inning,
        "outs": outs,
        "score": display_score(alert_score),
        "tier": alert_tier_value,
        "sent": True,
        "best_market": alert_market[0] if alert_market else "",
        "market_confidence": market_confidence(alert_score),
        "market_availability_risk": market_availability_risk(
            alert_type,
            best_target["target"]["batters_away"],
            alert_market[0] if alert_market else "",
        ),
        "passed_reason": "; ".join(best_target.get("passed_reasons", [])),
        "early_explanation": best_target.get("early_explanation", ""),
        "pressure_score": display_score(pressure_score),
        "game_spot": game_spot,
        "base_state": base_text,
        "pitcher": pitcher_obj.get("name", ""),
        "pitcher_id": pitcher_obj.get("id", ""),
        "pitcher_weakness": pitcher.get("weakness"),
        "pitcher_era": pitcher.get("era"),
        "pitcher_whip": pitcher.get("whip"),
        "pitcher_ip": pitcher.get("ip"),
        "player_avg": best_target["profile"].get("avg"),
        "player_obp": best_target["profile"].get("obp"),
        "player_slg": best_target["profile"].get("slg"),
        "player_ops": best_target["profile"].get("ops"),
        "player_pa": best_target["profile"].get("pa"),
        "timing_boost": best_target.get("timing_boost"),
        "markets": [
            alert_market[2] if alert_market else ""
        ],
        "status": "open",
    })
    record_candidate(build_candidate_record(
        game_pk,
        alert_type,
        team,
        best_target,
        alert_market,
        alert_score,
        alert_tier_value,
        True,
        "",
        inning,
        outs,
        base_text,
        pitcher_obj,
        pitcher,
    ))
    record_global_alert(game_pk, team, best_target["target"]["id"], alert_score)
    msg = f"{msg}{tracking_footer(alert_id)}"

    print(
        f"Sending {alert_type}: {team} | Pitcher {pitcher_obj['name']} | "
        f"{best_target['target']['name']} ({best_target['target']['role']}) | "
        f"score {alert_score} | pressure {pressure_score} | alert {alert_id}",
        flush=True,
    )

    broadcast(msg, reply_markup=alert_reply_markup(alert_id))


def main():
    global last_update_id

    validate_config()
    last_update_id = load_last_update_id()

    broadcast("MLB Predictive Betting Alert Bot is live.")

    while True:
        try:
            check_telegram_messages()

            games = get_today_games()
            print(f"Checking {len(games)} live games...", flush=True)

            for game_pk in games:
                if game_pk:
                    check_game(game_pk)

        except Exception as exc:
            print("Main loop error:", exc, flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
