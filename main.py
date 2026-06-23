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

LOOKAHEAD_BATTERS = int(os.getenv("LOOKAHEAD_BATTERS", "4"))
MIN_TARGET_BATTERS_AWAY = int(os.getenv("MIN_TARGET_BATTERS_AWAY", "2"))

MIN_GET_READY_SCORE = int(os.getenv("MIN_GET_READY_SCORE", "88"))
MIN_MATCHUP_SCORE = int(os.getenv("MIN_MATCHUP_SCORE", "90"))
MIN_PRESSURE_SCORE = int(os.getenv("MIN_PRESSURE_SCORE", "92"))

FRESH_INJURY_DAYS = int(os.getenv("FRESH_INJURY_DAYS", "14"))
STATS_CACHE_SECONDS = int(os.getenv("STATS_CACHE_SECONDS", "900"))
INJURY_CACHE_SECONDS = int(os.getenv("INJURY_CACHE_SECONDS", "3600"))
TELEGRAM_OFFSET_FILE = os.getenv("TELEGRAM_OFFSET_FILE", ".telegram_offset")
RESULTS_FILE = os.getenv("RESULTS_FILE", "alert_results.json")
RESULTS_RECAP_DAYS = int(os.getenv("RESULTS_RECAP_DAYS", "1"))
MAX_RECAP_ITEMS = int(os.getenv("MAX_RECAP_ITEMS", "5"))

RECENT_INJURY_NAMES = [
    x.strip().lower()
    for x in os.getenv("RECENT_INJURY_NAMES", "").split(",")
    if x.strip()
]

sent_alerts = {}
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


def record_alert_outcome(alert_id, outcome, reported_by):
    store = load_result_store()
    for alert in store.get("alerts", []):
        if str(alert.get("id")).lower() == str(alert_id).lower():
            alert["status"] = outcome
            alert["outcome_at"] = utc_now().isoformat()
            alert["reported_by"] = str(reported_by)
            save_result_store(store)
            post_sheet_event({
                "kind": "alert_result",
                "alert_id": alert["id"],
                "status": outcome,
                "outcome": outcome,
                "outcome_at": alert["outcome_at"],
                "reported_by": alert["reported_by"],
            })
            return alert
    return None


def summarize_results(days=1, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=days)
    summary = {
        "total": 0,
        "open": 0,
        "win": 0,
        "loss": 0,
        "push": 0,
        "no_market": 0,
        "by_type": {},
        "recent": [],
    }

    alerts = sorted(
        load_result_store().get("alerts", []),
        key=lambda item: parse_iso_datetime(item.get("sent_at")),
        reverse=True,
    )

    for alert in alerts:
        sent_at = parse_iso_datetime(alert.get("sent_at"))
        if sent_at < cutoff:
            continue

        status = alert.get("status", "open")
        alert_type = alert.get("alert_type", "UNKNOWN")
        summary["total"] += 1
        summary[status] = summary.get(status, 0) + 1
        summary["by_type"][alert_type] = summary["by_type"].get(alert_type, 0) + 1

        if len(summary["recent"]) < MAX_RECAP_ITEMS:
            summary["recent"].append(alert)

    return summary


def build_results_recap(days=RESULTS_RECAP_DAYS):
    summary = summarize_results(days)
    graded = summary["win"] + summary["loss"]
    win_rate = (summary["win"] / graded * 100) if graded else 0

    lines = [
        f"Results recap: last {days} day(s)",
        "",
        f"Tracked alerts: {summary['total']}",
        f"Record: {summary['win']}-{summary['loss']}-{summary['push']}",
        f"No market/locked: {summary['no_market']}",
        f"Still open: {summary['open']}",
        f"Win rate: {win_rate:.1f}%" if graded else "Win rate: not enough graded alerts",
    ]

    if summary["by_type"]:
        type_lines = [
            f"{alert_type}: {count}"
            for alert_type, count in sorted(summary["by_type"].items())
        ]
        lines.extend(["", "By alert type:", "\n".join(type_lines)])

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


def tracking_footer(alert_id):
    return (
        "\n\nTrack this alert:\n"
        f"ID: {alert_id}\n"
        f"Report: /win {alert_id} | /loss {alert_id} | /push {alert_id} | /nomarket {alert_id}"
    )


def send_telegram(chat_id, msg):
    url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage"
    data = request_json("post", url, data={"chat_id": chat_id, "text": msg})
    if data.get("ok") is not True:
        raise RuntimeError(f"Telegram send failed: {data}")
    return data


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


def broadcast(msg):
    subscribers = get_sheet_subscribers()
    print(f"Broadcasting to {len(subscribers)} subscriber(s)", flush=True)
    for chat_id in subscribers:
        try:
            send_telegram(chat_id, msg)
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
        "/pending - show open tracked alerts\n"
        "/win ID, /loss ID, /push ID, /nomarket ID - report an alert result\n"
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
    }
    return (
        f"Recorded {labels.get(outcome, outcome)} for {alert['id']}.\n\n"
        f"{build_results_recap()}"
    )


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

        message = update.get("message", {})
        chat = message.get("chat", {})

        chat_id = chat.get("id")
        username = chat.get("username", "")
        first_name = chat.get("first_name", "")
        text = message.get("text", "")
        command, args = parse_command(text)

        if not chat_id:
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

        elif command == "/pending":
            send_telegram(chat_id, build_pending_alerts())

        elif command in OUTCOME_COMMANDS:
            if not args:
                send_telegram(
                    chat_id,
                    "Send the alert ID too. Example: /win 0623-12345-6T-GR-67890",
                )
                continue

            outcome = OUTCOME_COMMANDS[command]
            alert = record_alert_outcome(args[0], outcome, chat_id)
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
                "Send /pending to see open alerts.\n"
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

    return {
        "weakness": weakness,
        "era": era,
        "whip": whip,
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
        })

    return targets


def score_player_target(target, pitcher, pressure_score):
    stats = get_player_season_stats(target["id"], "hitting")
    profile = calculate_batter_profile(stats)

    away = safe_int(target.get("batters_away", 1))

    timing_boost = 0
    if away == 2:
        timing_boost = 10
    elif away == 3:
        timing_boost = 8
    elif away == 4:
        timing_boost = 5
    elif away == 1:
        timing_boost = -4

    hit_market = clamp(profile["hit"] + pitcher["weakness"] * 0.55 + pressure_score * 0.18 + timing_boost)
    hrr_market = clamp(profile["hrr"] + pitcher["weakness"] * 0.55 + pressure_score * 0.23 + timing_boost)
    rbi_market = clamp(profile["rbi"] + pitcher["weakness"] * 0.60 + pressure_score * 0.24 + timing_boost)
    tb_market = clamp(profile["total_bases"] + pitcher["weakness"] * 0.55 + pressure_score * 0.18 + timing_boost)
    hr_market = clamp(profile["hr"] + pitcher["weakness"] * 0.45 + pressure_score * 0.10 + timing_boost)

    return {
        "target": target,
        "profile": profile,
        "timing_boost": timing_boost,
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


def top_player_markets(player_score):
    name = player_score["target"]["name"]

    markets = [
        ("Player H+R+RBI", player_score["hrr"], f"{name} Hits+Runs+RBIs"),
        ("Player Hits", player_score["hit"], f"{name} 1+ Hit"),
        ("Player Total Bases", player_score["total_bases"], f"{name} Total Bases Over"),
        ("Player RBI", player_score["rbi"], f"{name} RBI"),
        ("Player Home Run", player_score["hr"], f"{name} Home Run"),
    ]

    markets.sort(key=lambda x: x[1], reverse=True)
    return markets[:3]


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


def build_get_ready_alert(team, target_score, pressure_score, game_spot, base_text, inning_pressure, pitcher):
    target = target_score["target"]
    markets = top_player_markets(target_score)

    return (
        "GET READY ALERT\n\n"
        "Target Player:\n"
        f"{target['name']} ({target['role']})\n\n"
        "Markets To Check Now:\n"
        f"{build_market_lines(markets, team_name=team)}\n\n"
        "Team Fallback:\n"
        f"{team} Team Total Over\n"
        f"Find it: {market_path('Team Total Over', team_name=team)}\n"
        f"Pressure Score: {display_score(pressure_score)}/100 {grade(pressure_score)}\n\n"
        "Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Why:\n"
        f"- Target is {target['batters_away']} batters away, so props are more likely open\n"
        "- Pressure is building before the market fully locks\n"
        f"- This inning: {inning_pressure['hits']} hit(s), {inning_pressure['walks']} walk(s), "
        f"{inning_pressure['runs']} run(s), {inning_pressure['consecutive_reached']} straight reached\n"
        f"- {format_score_debug(target_score, pitcher, pressure_score)}"
    )


def build_matchup_alert(team, target_score, pitcher, game_spot, base_text, pressure_score):
    target = target_score["target"]
    markets = top_player_markets(target_score)

    return (
        "MATCHUP ALERT\n\n"
        "Target Player:\n"
        f"{target['name']} ({target['role']})\n\n"
        "Markets To Check:\n"
        f"{build_market_lines(markets, team_name=team)}\n\n"
        "Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Pitcher Weakness:\n"
        f"{pitcher['weakness']} model points\n"
        f"ERA/WHIP: {pitcher['era']:.2f}/{pitcher['whip']:.2f}\n"
        f"HR/9: {pitcher['hr9']:.2f} | BB/9: {pitcher['bb9']:.2f}\n"
        f"{format_score_debug(target_score, pitcher, pressure_score)}"
    )


def build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure, best_targets):
    target_lines = []

    for target in best_targets[:3]:
        target_lines.append(
            f"- {target['target']['name']} ({target['target']['role']}) - "
            f"Best score {display_score(target['best_score'])}/100"
        )

    return (
        "PRESSURE BUILDING\n\n"
        "Target Team:\n"
        f"{team}\n\n"
        "Markets To Check:\n"
        f"1. {team} Team Total Over\n"
        f"   Find it: {market_path('Team Total Over', team_name=team)}\n\n"
        "2. Current Inning Total Runs Over\n"
        f"   Find it: {market_path('Inning Total Runs')}\n\n"
        "3. Game Total Over\n"
        f"   Find it: {market_path('Game Total Over')}\n\n"
        "Potential Player Targets:\n"
        f"{chr(10).join(target_lines)}\n\n"
        f"Pressure Score: {display_score(pressure_score)}/100 {grade(pressure_score)}\n\n"
        "Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        "Why:\n"
        "- Pitcher/team pressure is rising\n"
        "- We are looking ahead in the batting order before props lock\n"
        f"- This inning: {inning_pressure['hits']} hit(s), {inning_pressure['walks']} walk(s), "
        f"{inning_pressure['runs']} run(s), {inning_pressure['consecutive_reached']} straight reached"
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

        scored_targets.append(
            score_player_target(
                target=target,
                pitcher=pitcher,
                pressure_score=pressure_score,
            )
        )

    if not scored_targets:
        return

    scored_targets.sort(key=lambda x: x["best_score"], reverse=True)

    early_targets = [
        target
        for target in scored_targets
        if safe_int(target["target"]["batters_away"]) >= MIN_TARGET_BATTERS_AWAY
    ]

    if not early_targets:
        print(f"{team}: no early targets available", flush=True)
        return

    early_targets.sort(key=lambda x: x["best_score"], reverse=True)
    best_target = early_targets[0]

    game_spot = f"{half_display} {inning_display} | {outs} outs | Count {balls}-{strikes}"
    base_text = runners_summary(offense)

    msg = None
    alert_type = None
    alert_score = 0

    if best_target["best_score"] >= MIN_GET_READY_SCORE and pressure_score >= 65:
        alert_type = "GET_READY"
        alert_score = best_target["best_score"]
        msg = build_get_ready_alert(
            team, best_target, pressure_score, game_spot, base_text, inning_pressure, pitcher
        )

    elif best_target["best_score"] >= MIN_MATCHUP_SCORE:
        alert_type = "MATCHUP"
        alert_score = best_target["best_score"]
        msg = build_matchup_alert(team, best_target, pitcher, game_spot, base_text, pressure_score)

    elif pressure_score >= MIN_PRESSURE_SCORE:
        alert_type = "PRESSURE"
        alert_score = pressure_score
        msg = build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure, early_targets)

    if not msg:
        print(
            f"{team} {game_spot} | Pitcher {pitcher_obj['name']} | "
            f"Pressure {pressure_score} | Best early target "
            f"{best_target['target']['name']} {best_target['target']['role']} "
            f"{best_target['best_score']} | {format_score_debug(best_target, pitcher, pressure_score)} | no alert",
            flush=True,
        )
        return

    spot_key = f"{game_pk}-{inning}-{half}-{team}-{alert_type}-{best_target['target']['id']}"

    if not should_send_alert(spot_key, alert_score):
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
        "score": display_score(alert_score),
        "pressure_score": display_score(pressure_score),
        "game_spot": game_spot,
        "base_state": base_text,
        "markets": [
            label
            for _, _, label in top_player_markets(best_target)
        ],
        "status": "open",
    })
    msg = f"{msg}{tracking_footer(alert_id)}"

    print(
        f"Sending {alert_type}: {team} | Pitcher {pitcher_obj['name']} | "
        f"{best_target['target']['name']} ({best_target['target']['role']}) | "
        f"score {alert_score} | pressure {pressure_score} | alert {alert_id}",
        flush=True,
    )

    broadcast(msg)


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
