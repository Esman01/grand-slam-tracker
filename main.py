import os
import time
import requests
from datetime import datetime, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
SHEET_WEBHOOK_URL = os.environ["SHEET_WEBHOOK_URL"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))
ONLY_BASES_LOADED = os.getenv("ONLY_BASES_LOADED", "true").lower() == "true"

ACTIONABLE_ONLY = os.getenv("ACTIONABLE_ONLY", "true").lower() == "true"
ALLOW_FAST_LOCK_MARKETS = os.getenv("ALLOW_FAST_LOCK_MARKETS", "false").lower() == "true"

MIN_HIT_SCORE = int(os.getenv("MIN_HIT_SCORE", "82"))
MIN_RBI_SCORE = int(os.getenv("MIN_RBI_SCORE", "86"))
MIN_HR_SCORE = int(os.getenv("MIN_HR_SCORE", "88"))
MIN_K_SCORE = int(os.getenv("MIN_K_SCORE", "88"))
MIN_TOTAL_BASES_SCORE = int(os.getenv("MIN_TOTAL_BASES_SCORE", "85"))
MIN_XBH_SCORE = int(os.getenv("MIN_XBH_SCORE", "88"))
MIN_TEAM_SCORE_INNING = int(os.getenv("MIN_TEAM_SCORE_INNING", "88"))
MIN_MELTDOWN_SCORE = int(os.getenv("MIN_MELTDOWN_SCORE", "85"))
MIN_INNING_HR_SCORE = int(os.getenv("MIN_INNING_HR_SCORE", "90"))
MIN_LIVE_TEAM_TOTAL_SCORE = int(os.getenv("MIN_LIVE_TEAM_TOTAL_SCORE", "84"))
MIN_GAME_TOTAL_SCORE = int(os.getenv("MIN_GAME_TOTAL_SCORE", "87"))

FRESH_INJURY_DAYS = int(os.getenv("FRESH_INJURY_DAYS", "14"))

RECENT_INJURY_NAMES = [
    x.strip().lower()
    for x in os.getenv("RECENT_INJURY_NAMES", "").split(",")
    if x.strip()
]

sent_alerts = set()
player_stats_cache = {}
injury_cache = {}
last_update_id = None


def safe_float(value, default=0.0):
    try:
        if value in [None, "", ".---", "---"]:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value in [None, "", ".---", "---"]:
            return default
        return int(float(value))
    except Exception:
        return default


def clamp(value, low=0, high=100):
    return max(low, min(high, round(value)))


def grade(score):
    if score >= 94:
        return "🔥 ELITE"
    if score >= 88:
        return "✅ STRONG"
    if score >= 82:
        return "🟡 PLAYABLE"
    return "PASS"


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)


def get_sheet_subscribers():
    try:
        response = requests.get(SHEET_WEBHOOK_URL, timeout=10)
        data = response.json()
        return set(str(x) for x in data.get("subscribers", []))
    except Exception as e:
        print("Sheet subscriber error:", e, flush=True)
        return set()


def save_subscriber(chat_id, username="", first_name="", status="active"):
    payload = {
        "chat_id": str(chat_id),
        "username": username,
        "first_name": first_name,
        "status": status,
    }

    try:
        response = requests.post(SHEET_WEBHOOK_URL, json=payload, timeout=10)
        data = response.json()
        return data.get("ok") is True
    except Exception as e:
        print("Sheet save error:", e, flush=True)
        return False


def broadcast(msg):
    for chat_id in get_sheet_subscribers():
        try:
            send_telegram(chat_id, msg)
        except Exception as e:
            print(f"Send error to {chat_id}:", e, flush=True)


def subscription_message():
    return (
        "✅ Subscription Active\n\n"
        "You’ll receive actionable MLB live bet alerts.\n\n"
        "The bot prioritizes markets that are more likely to stay unlocked live:\n"
        "• Live Team Total Over\n"
        "• Game Total Over\n"
        "• Team To Score This Inning\n\n"
        "Fast-lock markets like RBI, Hit, HR, Total Bases, and Strikeout are filtered out by default unless enabled.\n\n"
        "Commands:\n"
        "/status - check status\n"
        "/stop - stop alerts\n"
        "/join - restart alerts"
    )


def check_telegram_messages():
    global last_update_id

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {}

    if last_update_id is not None:
        params["offset"] = last_update_id + 1

    try:
        data = requests.get(url, params=params, timeout=10).json()
    except Exception as e:
        print("Telegram update error:", e, flush=True)
        return

    for update in data.get("result", []):
        last_update_id = update.get("update_id", last_update_id)

        message = update.get("message", {})
        chat = message.get("chat", {})

        chat_id = chat.get("id")
        username = chat.get("username", "")
        first_name = chat.get("first_name", "")
        text = message.get("text", "")

        if not chat_id:
            continue

        if text.startswith("/start") or text.startswith("/join"):
            if save_subscriber(chat_id, username, first_name, "active"):
                send_telegram(chat_id, subscription_message())
            else:
                send_telegram(chat_id, "⚠️ Subscription failed. Send /join again.")

        elif text.startswith("/stop"):
            if save_subscriber(chat_id, username, first_name, "inactive"):
                send_telegram(chat_id, "❌ Alerts stopped.\n\nSend /join to restart.")
            else:
                send_telegram(chat_id, "⚠️ Stop failed. Send /stop again.")

        elif text.startswith("/status"):
            subscribers = get_sheet_subscribers()
            if str(chat_id) in subscribers:
                send_telegram(chat_id, "✅ Bot is online.\n\nSubscription Status: ACTIVE")
            else:
                send_telegram(chat_id, "⚠️ Bot is online, but you are NOT active.\n\nSend /join.")

        else:
            send_telegram(
                chat_id,
                "⚾ MLB Betting Alert Bot\n\n"
                "Send /join to activate alerts.\n"
                "Send /status to check status.\n"
                "Send /stop to stop alerts."
            )


def get_today_games():
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1"

    try:
        data = requests.get(url, timeout=10).json()
    except Exception as e:
        print("Schedule error:", e, flush=True)
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

    if cache_key in player_stats_cache:
        return player_stats_cache[cache_key]

    url = (
        f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        f"?hydrate=stats(group=[{group}],type=[season])"
    )

    try:
        data = requests.get(url, timeout=10).json()
        person = data.get("people", [{}])[0]
        stats_blocks = person.get("stats", [])

        if not stats_blocks:
            player_stats_cache[cache_key] = {}
            return {}

        splits = stats_blocks[0].get("splits", [])

        if not splits:
            player_stats_cache[cache_key] = {}
            return {}

        stats = splits[0].get("stat", {})
        player_stats_cache[cache_key] = stats
        return stats

    except Exception as e:
        print(f"Stats error {group} {player_id}:", e, flush=True)
        player_stats_cache[cache_key] = {}
        return {}


def recently_reinstated_from_injury(player_id, player_name):
    if not player_id:
        return False, "No player id"

    if player_name and player_name.lower() in RECENT_INJURY_NAMES:
        return True, "Manual recent injury list"

    cache_key = f"injury-{player_id}"

    if cache_key in injury_cache:
        return injury_cache[cache_key]

    end_date = datetime.now()
    start_date = end_date - timedelta(days=FRESH_INJURY_DAYS)

    url = (
        "https://statsapi.mlb.com/api/v1/transactions"
        f"?playerId={player_id}"
        f"&startDate={start_date.strftime('%Y-%m-%d')}"
        f"&endDate={end_date.strftime('%Y-%m-%d')}"
    )

    try:
        data = requests.get(url, timeout=10).json()
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
                injury_cache[cache_key] = result
                return result

        result = False, "No recent injury return found"
        injury_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"Injury check error {player_name}:", e, flush=True)
        result = False, "Injury check unavailable"
        injury_cache[cache_key] = result
        return result


def get_batter_vs_pitcher_history(batter_id, pitcher_id):
    if not batter_id or not pitcher_id:
        return {"score": 0, "summary": "No BvP data"}

    cache_key = f"bvp-{batter_id}-{pitcher_id}"

    if cache_key in player_stats_cache:
        return player_stats_cache[cache_key]

    url = (
        f"https://statsapi.mlb.com/api/v1/people/{batter_id}"
        f"?hydrate=stats(group=[hitting],type=[vsPlayer],opposingPlayerId={pitcher_id})"
    )

    try:
        data = requests.get(url, timeout=10).json()
        person = data.get("people", [{}])[0]
        stats_blocks = person.get("stats", [])

        if not stats_blocks:
            result = {"score": 0, "summary": "No BvP data"}
            player_stats_cache[cache_key] = result
            return result

        splits = stats_blocks[0].get("splits", [])

        if not splits:
            result = {"score": 0, "summary": "No BvP data"}
            player_stats_cache[cache_key] = result
            return result

        stat = splits[0].get("stat", {})

        at_bats = safe_int(stat.get("atBats"))
        hits = safe_int(stat.get("hits"))
        home_runs = safe_int(stat.get("homeRuns"))
        strikeouts = safe_int(stat.get("strikeOuts"))
        avg = safe_float(stat.get("avg"))
        ops = safe_float(stat.get("ops"))

        score = 0

        if at_bats < 6:
            result = {
                "score": 0,
                "summary": f"Tiny BvP sample: {hits}-{at_bats}, {home_runs} HR"
            }
            player_stats_cache[cache_key] = result
            return result

        if avg >= 0.350:
            score += 8
        elif avg >= 0.280:
            score += 4
        elif avg <= 0.180:
            score -= 8

        if ops >= 1.000:
            score += 8
        elif ops >= 0.850:
            score += 4
        elif ops <= 0.600:
            score -= 6

        if home_runs >= 2:
            score += 10
        elif home_runs == 1:
            score += 5

        if strikeouts >= max(3, at_bats * 0.35):
            score -= 6

        score = max(-15, min(18, score))

        result = {
            "score": score,
            "summary": f"BvP: {hits}-{at_bats}, {home_runs} HR, AVG {avg:.3f}, OPS {ops:.3f}"
        }

        player_stats_cache[cache_key] = result
        return result

    except Exception as e:
        print("BvP error:", e, flush=True)
        result = {"score": 0, "summary": "BvP unavailable"}
        player_stats_cache[cache_key] = result
        return result


def calculate_batter_profile(stats):
    avg = safe_float(stats.get("avg"))
    obp = safe_float(stats.get("obp"))
    slg = safe_float(stats.get("slg"))
    ops = safe_float(stats.get("ops"))

    hr = safe_int(stats.get("homeRuns"))
    rbi = safe_int(stats.get("rbi"))
    hits = safe_int(stats.get("hits"))
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

    rbi_score = (
        45
        + (obp * 25)
        + (slg * 42)
        + ((rbi / pa) * 110)
        + (bb_rate * 25)
        - (k_rate * 30)
    )

    hr_score = (
        35
        + (hr_rate * 800)
        + (slg * 38)
        + (xbh_rate * 95)
        + (ops * 12)
        - (k_rate * 15)
    )

    total_bases_score = (
        42
        + (slg * 55)
        + (ops * 18)
        + (xbh_rate * 90)
        - (k_rate * 22)
    )

    xbh_score = (
        35
        + (slg * 45)
        + (xbh_rate * 140)
        + (hr_rate * 300)
        - (k_rate * 15)
    )

    batter_k_risk = 40 + (k_rate * 120) - (bb_rate * 35) - (avg * 25)

    return {
        "hit_score": clamp(hit_score),
        "rbi_score": clamp(rbi_score),
        "hr_score": clamp(hr_score),
        "total_bases_score": clamp(total_bases_score),
        "xbh_score": clamp(xbh_score),
        "batter_k_risk": clamp(batter_k_risk),
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "hr": hr,
        "rbi": rbi,
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

    contact_suppression = 0
    rbi_suppression = 0
    hr_suppression = 0
    tb_suppression = 0
    xbh_suppression = 0
    strikeout_boost = 0

    if era <= 3.25:
        contact_suppression += 8
        rbi_suppression += 8
        tb_suppression += 6
    elif era >= 5.00:
        contact_suppression -= 8
        rbi_suppression -= 8
        tb_suppression -= 8

    if whip <= 1.10:
        contact_suppression += 10
        rbi_suppression += 10
    elif whip >= 1.40:
        contact_suppression -= 10
        rbi_suppression -= 12

    if k9 >= 11:
        contact_suppression += 11
        rbi_suppression += 7
        hr_suppression += 4
        tb_suppression += 7
        strikeout_boost += 20
    elif k9 >= 9:
        strikeout_boost += 12
    elif k9 <= 7:
        contact_suppression -= 7
        rbi_suppression -= 5
        strikeout_boost -= 8

    if hr9 <= 0.80:
        hr_suppression += 12
        xbh_suppression += 8
    elif hr9 >= 1.40:
        hr_suppression -= 14
        xbh_suppression -= 10
    elif hr9 >= 1.10:
        hr_suppression -= 7
        xbh_suppression -= 5

    if bb9 >= 4.0:
        rbi_suppression -= 10
    elif bb9 <= 2.0:
        rbi_suppression += 5

    if h9 >= 9.5:
        contact_suppression -= 8
        tb_suppression -= 7
    elif h9 <= 7.0:
        contact_suppression += 6
        tb_suppression += 5

    return {
        "contact_suppression": contact_suppression,
        "rbi_suppression": rbi_suppression,
        "hr_suppression": hr_suppression,
        "tb_suppression": tb_suppression,
        "xbh_suppression": xbh_suppression,
        "strikeout_boost": strikeout_boost,
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

    edge = {"hit": 0, "rbi": 0, "hr": 0, "k": 0, "tb": 0, "xbh": 0}

    if balls == 3 and strikes == 0:
        edge.update({"hit": 5, "rbi": 14, "hr": 3, "k": -18, "tb": 4, "xbh": 2})
    elif balls == 3 and strikes == 1:
        edge.update({"hit": 6, "rbi": 12, "hr": 5, "k": -10, "tb": 5, "xbh": 4})
    elif balls == 3 and strikes == 2:
        edge.update({"hit": 2, "rbi": 8, "hr": 1, "k": 8, "tb": 1, "xbh": 0})
    elif balls == 2 and strikes == 0:
        edge.update({"hit": 6, "rbi": 7, "hr": 5, "k": -10, "tb": 5, "xbh": 4})
    elif balls == 2 and strikes == 1:
        edge.update({"hit": 4, "rbi": 5, "hr": 3, "k": -2, "tb": 3, "xbh": 2})
    elif balls == 0 and strikes == 2:
        edge.update({"hit": -12, "rbi": -10, "hr": -8, "k": 20, "tb": -10, "xbh": -8})
    elif balls == 1 and strikes == 2:
        edge.update({"hit": -8, "rbi": -7, "hr": -5, "k": 15, "tb": -6, "xbh": -5})
    elif balls == 0 and strikes == 1:
        edge.update({"hit": -4, "rbi": -3, "hr": -2, "k": 5, "tb": -3, "xbh": -2})

    return edge


def calculate_outs_edge(outs):
    outs = safe_int(outs)

    if outs == 0:
        return {"hit": 2, "rbi": 8, "hr": 1, "k": 0, "team": 10}
    if outs == 1:
        return {"hit": 1, "rbi": 5, "hr": 0, "k": 0, "team": 6}
    if outs == 2:
        return {"hit": 0, "rbi": -3, "hr": 1, "k": 1, "team": -6}

    return {"hit": 0, "rbi": 0, "hr": 0, "k": 0, "team": 0}


def event_is_runner_reached(event):
    event = (event or "").lower()
    return event in [
        "single", "double", "triple", "home_run", "walk",
        "hit_by_pitch", "field_error", "catcher_interf", "intent_walk"
    ]


def event_is_hit(event):
    event = (event or "").lower()
    return event in ["single", "double", "triple", "home_run"]


def event_is_walk(event):
    event = (event or "").lower()
    return event in ["walk", "intent_walk"]


def event_is_hr(event):
    return (event or "").lower() == "home_run"


def get_inning_pressure(data, inning, half):
    plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])

    hits = 0
    walks = 0
    hbp = 0
    runs = 0
    home_runs = 0
    consecutive_reached = 0
    max_consecutive_reached = 0
    strikeouts = 0

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
        if event_is_hr(event):
            home_runs += 1
        if event == "strikeout":
            strikeouts += 1

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
        "home_runs": home_runs,
        "strikeouts": strikeouts,
        "consecutive_reached": max_consecutive_reached,
    }


def calculate_meltdown_score(pitcher, inning_pressure, bases_loaded, outs):
    score = 35

    if pitcher["whip"] >= 1.60:
        score += 18
    elif pitcher["whip"] >= 1.40:
        score += 12
    elif pitcher["whip"] <= 1.10:
        score -= 10

    if pitcher["bb9"] >= 4.5:
        score += 14
    elif pitcher["bb9"] >= 3.5:
        score += 8

    if pitcher["h9"] >= 10:
        score += 12
    elif pitcher["h9"] >= 9:
        score += 7

    score += inning_pressure["hits"] * 8
    score += inning_pressure["walks"] * 10
    score += inning_pressure["hbp"] * 8
    score += inning_pressure["runs"] * 5
    score += inning_pressure["consecutive_reached"] * 7

    if bases_loaded:
        score += 16

    if safe_int(outs) == 0:
        score += 8
    elif safe_int(outs) == 1:
        score += 4
    elif safe_int(outs) == 2:
        score -= 5

    return clamp(score)


def calculate_scores(batter_stats, pitcher_stats, bvp, balls, strikes, outs, bases_loaded, inning_pressure):
    batter = calculate_batter_profile(batter_stats)
    pitcher = calculate_pitcher_profile(pitcher_stats)
    count = calculate_count_edge(balls, strikes)
    outs_edge = calculate_outs_edge(outs)

    meltdown = calculate_meltdown_score(pitcher, inning_pressure, bases_loaded, outs)

    hit_score = (
        batter["hit_score"]
        - pitcher["contact_suppression"]
        + bvp["score"]
        + count["hit"]
        + outs_edge["hit"]
    )

    rbi_score = (
        batter["rbi_score"]
        - pitcher["rbi_suppression"]
        + bvp["score"]
        + count["rbi"]
        + outs_edge["rbi"]
        + (10 if bases_loaded else 0)
        + ((meltdown - 70) * 0.25 if meltdown > 70 else 0)
    )

    hr_score = (
        batter["hr_score"]
        - pitcher["hr_suppression"]
        + bvp["score"]
        + count["hr"]
        + outs_edge["hr"]
    )

    k_score = (
        batter["batter_k_risk"]
        + pitcher["strikeout_boost"]
        - bvp["score"]
        + count["k"]
        + outs_edge["k"]
    )

    total_bases_score = (
        batter["total_bases_score"]
        - pitcher["tb_suppression"]
        + bvp["score"]
        + count["tb"]
    )

    xbh_score = (
        batter["xbh_score"]
        - pitcher["xbh_suppression"]
        + bvp["score"]
        + count["xbh"]
    )

    team_score_inning = (
        45
        + meltdown * 0.45
        + outs_edge["team"]
        + (18 if bases_loaded else 0)
        + inning_pressure["hits"] * 5
        + inning_pressure["walks"] * 7
    )

    live_team_total_over = (
        48
        + meltdown * 0.42
        + inning_pressure["hits"] * 4
        + inning_pressure["walks"] * 5
        + (10 if bases_loaded else 0)
    )

    game_total_over = (
        50
        + meltdown * 0.30
        + inning_pressure["runs"] * 5
        + inning_pressure["hits"] * 3
        + inning_pressure["walks"] * 4
        + (7 if bases_loaded else 0)
    )

    inning_hr_score = (
        hr_score * 0.70
        + max(0, 75 - safe_int(outs) * 8) * 0.15
        + max(0, pitcher["hr9"] * 10) * 0.15
    )

    return {
        "hit": clamp(hit_score),
        "rbi": clamp(rbi_score),
        "hr": clamp(hr_score),
        "k": clamp(k_score),
        "total_bases": clamp(total_bases_score),
        "xbh": clamp(xbh_score),
        "team_score_inning": clamp(team_score_inning),
        "live_team_total_over": clamp(live_team_total_over),
        "game_total_over": clamp(game_total_over),
        "meltdown": clamp(meltdown),
        "inning_hr": clamp(inning_hr_score),
        "batter": batter,
        "pitcher": pitcher,
        "bvp": bvp,
        "inning_pressure": inning_pressure,
    }


def sportsbook_name(bet_type):
    names = {
        "LIVE TEAM TOTAL OVER": "Live Team Total Over / Team Total Runs Over",
        "GAME TOTAL OVER": "Live Game Total Over / Total Runs Over",
        "TEAM SCORE THIS INNING": "Team To Score This Inning / Team Runs This Inning",
        "PITCHER MELTDOWN": "Live Team Total Over / Game Total Over",
        "HIT": "Player To Record A Hit / To Get A Hit",
        "RBI": "Player To Record An RBI / Player RBI",
        "HOME RUN": "Player To Hit A Home Run / Batter Home Run",
        "STRIKEOUT": "Batter Strikeout / PA Result: Strikeout",
        "TOTAL BASES": "Player Total Bases / Over 1.5 Total Bases",
        "EXTRA BASE HIT": "Player To Record An Extra Base Hit",
        "1+ HR THIS INNING": "1+ Home Run This Inning / Home Run In Inning",
    }
    return names.get(bet_type, bet_type)


def lock_risk(bet_type):
    risks = {
        "GAME TOTAL OVER": 10,
        "LIVE TEAM TOTAL OVER": 15,
        "PITCHER MELTDOWN": 20,
        "TEAM SCORE THIS INNING": 55,
        "1+ HR THIS INNING": 65,
        "TOTAL BASES": 75,
        "EXTRA BASE HIT": 78,
        "HIT": 80,
        "RBI": 82,
        "HOME RUN": 85,
        "STRIKEOUT": 90,
    }
    return risks.get(bet_type, 70)


def is_actionable_market(bet_type):
    if not ACTIONABLE_ONLY:
        return True

    if bet_type in ["GAME TOTAL OVER", "LIVE TEAM TOTAL OVER", "PITCHER MELTDOWN"]:
        return True

    if bet_type == "TEAM SCORE THIS INNING":
        return True

    if ALLOW_FAST_LOCK_MARKETS:
        return True

    return False


def choose_bets(batter_name, offense_team, scores, bases_loaded):
    bets = []

    if scores["live_team_total_over"] >= MIN_LIVE_TEAM_TOTAL_SCORE:
        bets.append({
            "type": "LIVE TEAM TOTAL OVER",
            "player": offense_team,
            "score": scores["live_team_total_over"],
            "bet": f"{offense_team} Live Team Total Over",
            "action_note": "Most likely to stay open compared to current PA props."
        })

    if scores["game_total_over"] >= MIN_GAME_TOTAL_SCORE:
        bets.append({
            "type": "GAME TOTAL OVER",
            "player": "Game",
            "score": scores["game_total_over"],
            "bet": "Live Game Total Over",
            "action_note": "Usually one of the most available live markets."
        })

    if scores["meltdown"] >= MIN_MELTDOWN_SCORE:
        bets.append({
            "type": "PITCHER MELTDOWN",
            "player": offense_team,
            "score": scores["meltdown"],
            "bet": f"{offense_team} Live Team Total Over",
            "action_note": "Pitcher is unraveling. Use team total or game total if inning market is locked."
        })

    if scores["team_score_inning"] >= MIN_TEAM_SCORE_INNING:
        bets.append({
            "type": "TEAM SCORE THIS INNING",
            "player": offense_team,
            "score": scores["team_score_inning"],
            "bet": f"{offense_team} To Score This Inning",
            "action_note": "Try first, but this often locks in high-leverage spots. If locked, use Live Team Total Over."
        })

    if bases_loaded and scores["rbi"] >= MIN_RBI_SCORE:
        bets.append({
            "type": "RBI",
            "player": batter_name,
            "score": scores["rbi"],
            "bet": f"{batter_name} RBI",
            "action_note": "Fast-lock market. Usually only playable if the book still has it open before/during PA."
        })

    if scores["hit"] >= MIN_HIT_SCORE:
        bets.append({
            "type": "HIT",
            "player": batter_name,
            "score": scores["hit"],
            "bet": f"{batter_name} Hit",
            "action_note": "Fast-lock market. Often unavailable once the batter is already up."
        })

    if scores["total_bases"] >= MIN_TOTAL_BASES_SCORE:
        bets.append({
            "type": "TOTAL BASES",
            "player": batter_name,
            "score": scores["total_bases"],
            "bet": f"{batter_name} Over Total Bases",
            "action_note": "Fast-lock player prop. More likely open before the PA starts."
        })

    if scores["xbh"] >= MIN_XBH_SCORE:
        bets.append({
            "type": "EXTRA BASE HIT",
            "player": batter_name,
            "score": scores["xbh"],
            "bet": f"{batter_name} Extra Base Hit",
            "action_note": "Fast-lock player prop. Often unavailable mid-PA."
        })

    if scores["hr"] >= MIN_HR_SCORE:
        bets.append({
            "type": "HOME RUN",
            "player": batter_name,
            "score": scores["hr"],
            "bet": f"{batter_name} Home Run",
            "action_note": "Fast-lock lottery market. If locked, look for 1+ HR inning or team total."
        })

    if scores["inning_hr"] >= MIN_INNING_HR_SCORE:
        bets.append({
            "type": "1+ HR THIS INNING",
            "player": offense_team,
            "score": scores["inning_hr"],
            "bet": "1+ Home Run This Inning",
            "action_note": "Often locks during live PA. Use only if visible."
        })

    if scores["k"] >= MIN_K_SCORE:
        bets.append({
            "type": "STRIKEOUT",
            "player": batter_name,
            "score": scores["k"],
            "bet": f"{batter_name} Strikeout",
            "action_note": "Fastest-lock market. Usually not actionable unless posted before pitch."
        })

    bets = [b for b in bets if is_actionable_market(b["type"])]

    bets.sort(key=lambda x: (lock_risk(x["type"]), -x["score"]))
    return bets[:2]


def get_current_pitcher(data):
    boxscore = data.get("liveData", {}).get("boxscore", {})
    teams = boxscore.get("teams", {})

    for side in ["away", "home"]:
        players = teams.get(side, {}).get("players", {})

        for _, player_data in players.items():
            position = player_data.get("position", {}).get("abbreviation", "")
            if position == "P":
                person = player_data.get("person", {})
                return {
                    "id": person.get("id"),
                    "name": person.get("fullName", "Unknown pitcher"),
                }

    return {"id": None, "name": "Unknown pitcher"}


def get_current_count(data):
    current_play = data.get("liveData", {}).get("plays", {}).get("currentPlay", {})
    count = current_play.get("count", {})

    return {
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
    }


def build_alert_message(
    bet,
    all_bets,
    offense_team,
    half,
    inning,
    outs,
    balls,
    strikes,
    away_team,
    home_team,
    away_runs,
    home_runs,
    scores,
    bases_loaded,
):
    bvp = scores["bvp"]
    pressure = scores["inning_pressure"]

    secondary = ""

    if len(all_bets) > 1:
        second = all_bets[1]
        secondary = (
            f"\nBackup Bet: {second['bet']}\n"
            f"Sportsbook Name: {sportsbook_name(second['type'])}\n"
            f"Confidence: {second['score']}/100 {grade(second['score'])}\n"
            f"Lock Risk: {lock_risk(second['type'])}/100\n"
        )

    situation = "Bases loaded" if bases_loaded else "Live pressure spot"

    return (
        f"🚨 ACTIONABLE BET ALERT\n\n"
        f"Bet: {bet['bet']}\n"
        f"Sportsbook Name: {sportsbook_name(bet['type'])}\n"
        f"Confidence: {bet['score']}/100 {grade(bet['score'])}\n"
        f"Lock Risk: {lock_risk(bet['type'])}/100\n"
        f"Action: {bet['action_note']}\n"
        f"{secondary}\n"
        f"Game Spot:\n"
        f"{offense_team} batting\n"
        f"{half} {inning} | {outs} outs | Count {balls}-{strikes}\n\n"
        f"Best Scores:\n"
        f"Live Team Total: {scores['live_team_total_over']}/100\n"
        f"Game Total: {scores['game_total_over']}/100\n"
        f"Team Scores Inning: {scores['team_score_inning']}/100\n"
        f"Meltdown: {scores['meltdown']}/100\n\n"
        f"Fast-Lock Scores:\n"
        f"RBI: {scores['rbi']}/100 | Hit: {scores['hit']}/100 | HR: {scores['hr']}/100\n"
        f"TB: {scores['total_bases']}/100 | XBH: {scores['xbh']}/100 | K: {scores['k']}/100\n\n"
        f"Why:\n"
        f"• {situation}\n"
        f"• {bvp['summary']}\n"
        f"• This inning: {pressure['hits']} hits, {pressure['walks']} walks, "
        f"{pressure['runs']} runs, {pressure['consecutive_reached']} straight reached\n\n"
        f"Score:\n"
        f"{away_team}: {away_runs}\n"
        f"{home_team}: {home_runs}\n\n"
        f"Time: {datetime.now().strftime('%I:%M:%S %p')}"
    )


def check_game(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

    try:
        data = requests.get(url, timeout=10).json()
    except Exception as e:
        print(f"Game feed error {game_pk}:", e, flush=True)
        return

    linescore = data.get("liveData", {}).get("linescore", {})
    offense = linescore.get("offense", {})

    bases_loaded = (
        "first" in offense
        and "second" in offense
        and "third" in offense
    )

    if ONLY_BASES_LOADED and not bases_loaded:
        return

    inning = linescore.get("currentInning", "?")
    inning_display = linescore.get("currentInningOrdinal", "?")
    half = linescore.get("inningHalf", "?").lower()
    half_display = linescore.get("inningHalf", "?")
    outs = linescore.get("outs", "?")

    teams = data.get("gameData", {}).get("teams", {})
    away_team = teams.get("away", {}).get("name", "Away")
    home_team = teams.get("home", {}).get("name", "Home")

    away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0)
    home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0)

    offense_team = offense.get("team", {}).get("name", "Unknown team")

    batter_obj = offense.get("batter", {})
    batter_id = batter_obj.get("id")
    batter_name = batter_obj.get("fullName", "Unknown batter")

    pitcher_obj = get_current_pitcher(data)
    pitcher_id = pitcher_obj.get("id")

    count = get_current_count(data)
    balls = count["balls"]
    strikes = count["strikes"]

    alert_key = f"{game_pk}-{inning}-{half}-{batter_id}-{outs}-{balls}-{strikes}"

    if alert_key in sent_alerts:
        return

    injured, injury_reason = recently_reinstated_from_injury(batter_id, batter_name)

    if injured:
        print(f"Skipping {batter_name}: fresh injury risk - {injury_reason}", flush=True)
        sent_alerts.add(alert_key)
        return

    batter_stats = get_player_season_stats(batter_id, "hitting")
    pitcher_stats = get_player_season_stats(pitcher_id, "pitching")
    bvp = get_batter_vs_pitcher_history(batter_id, pitcher_id)
    inning_pressure = get_inning_pressure(data, inning, half)

    scores = calculate_scores(
        batter_stats=batter_stats,
        pitcher_stats=pitcher_stats,
        bvp=bvp,
        balls=balls,
        strikes=strikes,
        outs=outs,
        bases_loaded=bases_loaded,
        inning_pressure=inning_pressure,
    )

    bets = choose_bets(
        batter_name=batter_name,
        offense_team=offense_team,
        scores=scores,
        bases_loaded=bases_loaded,
    )

    print(
        f"{batter_name} | "
        f"LIVE_TEAM {scores['live_team_total_over']} GAME_TOTAL {scores['game_total_over']} "
        f"TEAM_INNING {scores['team_score_inning']} MELT {scores['meltdown']} "
        f"RBI {scores['rbi']} HIT {scores['hit']} HR {scores['hr']} | "
        f"BETS {bets}",
        flush=True
    )

    if not bets:
        sent_alerts.add(alert_key)
        return

    msg = build_alert_message(
        bet=bets[0],
        all_bets=bets,
        offense_team=offense_team,
        half=half_display,
        inning=inning_display,
        outs=outs,
        balls=balls,
        strikes=strikes,
        away_team=away_team,
        home_team=home_team,
        away_runs=away_runs,
        home_runs=home_runs,
        scores=scores,
        bases_loaded=bases_loaded,
    )

    broadcast(msg)
    sent_alerts.add(alert_key)


def main():
    broadcast("✅ MLB Actionable Betting Alert Bot is live.")

    while True:
        try:
            check_telegram_messages()

            games = get_today_games()
            print(f"Checking {len(games)} live games...", flush=True)

            for game_pk in games:
                if game_pk:
                    check_game(game_pk)

        except Exception as e:
            print("Main loop error:", e, flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
