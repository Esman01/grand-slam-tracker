import os
import time
import requests
from datetime import datetime, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
SHEET_WEBHOOK_URL = os.environ["SHEET_WEBHOOK_URL"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

ONLY_BASES_LOADED = os.getenv("ONLY_BASES_LOADED", "false").lower() == "true"
ACTIONABLE_ONLY = os.getenv("ACTIONABLE_ONLY", "true").lower() == "true"
ALLOW_FAST_LOCK_MARKETS = os.getenv("ALLOW_FAST_LOCK_MARKETS", "false").lower() == "true"

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "240"))
MAX_ALERTS_PER_HALF_INNING = int(os.getenv("MAX_ALERTS_PER_HALF_INNING", "1"))

MIN_GET_READY_SCORE = int(os.getenv("MIN_GET_READY_SCORE", "88"))
MIN_MATCHUP_SCORE = int(os.getenv("MIN_MATCHUP_SCORE", "90"))
MIN_PRESSURE_SCORE = int(os.getenv("MIN_PRESSURE_SCORE", "90"))
MIN_LIVE_BET_SCORE = int(os.getenv("MIN_LIVE_BET_SCORE", "92"))

FRESH_INJURY_DAYS = int(os.getenv("FRESH_INJURY_DAYS", "14"))

RECENT_INJURY_NAMES = [
    x.strip().lower()
    for x in os.getenv("RECENT_INJURY_NAMES", "").split(",")
    if x.strip()
]

sent_alerts = {}
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


def display_score(score):
    return min(95, clamp(score))


def grade(score):
    shown = display_score(score)
    if shown >= 94:
        return "🔥 ELITE"
    if shown >= 90:
        return "✅ STRONG"
    if shown >= 86:
        return "🟡 GOOD"
    return "WATCH"


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
        "You’ll receive target-based MLB live betting alerts.\n\n"
        "Alert types:\n"
        "🚨 LIVE BET ALERT\n"
        "👀 GET READY ALERT\n"
        "🔥 MATCHUP ALERT\n"
        "⚠️ PRESSURE BUILDING\n\n"
        "Every player market will name the exact player to check.\n\n"
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

    hrr_score = (
        45
        + (avg * 55)
        + (obp * 35)
        + (slg * 25)
        + (bb_rate * 25)
        - (k_rate * 35)
    )

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

    return {
        "hit": clamp(hit_score),
        "hrr": clamp(hrr_score),
        "rbi": clamp(rbi_score),
        "hr": clamp(hr_score),
        "total_bases": clamp(total_bases_score),
        "xbh": clamp(xbh_score),
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
        "single", "double", "triple", "home_run", "walk",
        "hit_by_pitch", "field_error", "catcher_interf", "intent_walk"
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
        pressure += 8
    elif inn >= 8:
        pressure -= 7

    return clamp(pressure)


def get_batting_order(data):
    boxscore = data.get("liveData", {}).get("boxscore", {})
    linescore = data.get("liveData", {}).get("linescore", {})
    offense_team_id = linescore.get("offense", {}).get("team", {}).get("id")

    teams = boxscore.get("teams", {})

    for side in ["away", "home"]:
        team = teams.get(side, {})
        team_id = team.get("team", {}).get("id")

        if team_id != offense_team_id:
            continue

        batting_order_ids = team.get("battingOrder", [])
        players = team.get("players", {})

        ordered = []
        for pid in batting_order_ids:
            pdata = players.get(f"ID{pid}", {})
            person = pdata.get("person", {})
            ordered.append({
                "id": person.get("id"),
                "name": person.get("fullName", "Unknown"),
            })

        return ordered

    return []


def get_targets(data):
    linescore = data.get("liveData", {}).get("linescore", {})
    offense = linescore.get("offense", {})

    current = {
        "role": "At Bat",
        "id": offense.get("batter", {}).get("id"),
        "name": offense.get("batter", {}).get("fullName", "Unknown batter"),
    }

    on_deck = {
        "role": "On Deck",
        "id": offense.get("onDeck", {}).get("id"),
        "name": offense.get("onDeck", {}).get("fullName", "Unknown"),
    }

    in_hole = {
        "role": "In Hole",
        "id": offense.get("inHole", {}).get("id"),
        "name": offense.get("inHole", {}).get("fullName", "Unknown"),
    }

    return [current, on_deck, in_hole]


def score_player_target(target, pitcher, pressure_score, count_edge, role):
    stats = get_player_season_stats(target["id"], "hitting")
    profile = calculate_batter_profile(stats)

    role_boost = 0
    if role == "At Bat":
        role_boost = 2
    elif role == "On Deck":
        role_boost = 8
    elif role == "In Hole":
        role_boost = 5

    hit_market = clamp(profile["hit"] + pitcher["weakness"] * 0.55 + pressure_score * 0.20 + role_boost + count_edge)
    hrr_market = clamp(profile["hrr"] + pitcher["weakness"] * 0.55 + pressure_score * 0.25 + role_boost)
    rbi_market = clamp(profile["rbi"] + pitcher["weakness"] * 0.60 + pressure_score * 0.30 + role_boost)
    tb_market = clamp(profile["total_bases"] + pitcher["weakness"] * 0.55 + pressure_score * 0.20 + role_boost)
    hr_market = clamp(profile["hr"] + pitcher["weakness"] * 0.45 + pressure_score * 0.12 + role_boost)

    return {
        "target": target,
        "profile": profile,
        "hit": hit_market,
        "hrr": hrr_market,
        "rbi": rbi_market,
        "total_bases": tb_market,
        "hr": hr_market,
        "best_score": max(hit_market, hrr_market, rbi_market, tb_market, hr_market),
    }


def market_path(market, player_name=None, team_name=None):
    if market == "Player Hits":
        return "Live Player Props → Player Hits"
    if market == "Player H+R+RBI":
        return "Live Player Props → Player Hits+Runs+RBIs"
    if market == "Player RBI":
        return "Live Player Props → Player RBIs"
    if market == "Player Total Bases":
        return "Live Player Props → Player Total Bases"
    if market == "Player Home Run":
        return "Live Player Props → Player Home Runs"
    if market == "Team Total Over":
        return f"Hits and Runs → {team_name} Alt. Total Runs\nor Hits and Runs → Team Total Runs"
    if market == "Inning Total Runs":
        return "Innings → Inning Total Runs\nor Innings → All Innings O/U 0.5 Runs"
    if market == "Team To Score This Inning":
        return "Innings → Inning Total Runs\nor Live Specials → Team To Score This Inning"
    if market == "Game Total Over":
        return "Live SGP → Game Lines → Total → Over"
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


def build_get_ready_alert(team, target_score, pressure_score, game_spot, base_text, inning_pressure):
    target = target_score["target"]
    markets = top_player_markets(target_score)

    return (
        f"👀 GET READY ALERT\n\n"
        f"Target Player:\n"
        f"{target['name']} ({target['role']})\n\n"
        f"Markets To Check:\n"
        f"{build_market_lines(markets, team_name=team)}\n\n"
        f"Team Fallback:\n"
        f"{team} Team Total Over\n"
        f"Find it: {market_path('Team Total Over', team_name=team)}\n"
        f"Pressure Score: {display_score(pressure_score)}/100 {grade(pressure_score)}\n\n"
        f"Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        f"Why:\n"
        f"• Target is due up soon, so player props are more likely to still be open\n"
        f"• Pressure is building before the book fully locks markets\n"
        f"• This inning: {inning_pressure['hits']} hit(s), {inning_pressure['walks']} walk(s), "
        f"{inning_pressure['runs']} run(s), {inning_pressure['consecutive_reached']} straight reached"
    )


def build_matchup_alert(team, target_score, pitcher, game_spot):
    target = target_score["target"]
    markets = top_player_markets(target_score)

    return (
        f"🔥 MATCHUP ALERT\n\n"
        f"Target Player:\n"
        f"{target['name']} ({target['role']})\n\n"
        f"Markets To Check:\n"
        f"{build_market_lines(markets, team_name=team)}\n\n"
        f"Pitcher Weakness:\n"
        f"{pitcher['weakness']} model points\n"
        f"ERA/WHIP: {pitcher['era']:.2f}/{pitcher['whip']:.2f}\n"
        f"HR/9: {pitcher['hr9']:.2f} | BB/9: {pitcher['bb9']:.2f}\n\n"
        f"Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}"
    )


def build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure):
    return (
        f"⚠️ PRESSURE BUILDING\n\n"
        f"Target Team:\n"
        f"{team}\n\n"
        f"Markets To Check:\n"
        f"1. {team} Team Total Over\n"
        f"   Find it: {market_path('Team Total Over', team_name=team)}\n\n"
        f"2. Current Inning Total Runs Over\n"
        f"   Find it: {market_path('Inning Total Runs')}\n\n"
        f"3. Game Total Over\n"
        f"   Find it: {market_path('Game Total Over')}\n\n"
        f"Pressure Score: {display_score(pressure_score)}/100 {grade(pressure_score)}\n\n"
        f"Game Spot:\n"
        f"{team} batting\n"
        f"{game_spot}\n"
        f"{base_text}\n\n"
        f"Why:\n"
        f"• Pitcher/team pressure is rising\n"
        f"• Better to check broader markets before the obvious player props lock\n"
        f"• This inning: {inning_pressure['hits']} hit(s), {inning_pressure['walks']} walk(s), "
        f"{inning_pressure['runs']} run(s), {inning_pressure['consecutive_reached']} straight reached"
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

    targets = get_targets(data)

    scored_targets = []
    for target in targets:
        if not target["id"] or target["name"] == "Unknown":
            continue

        injured, injury_reason = recently_reinstated_from_injury(target["id"], target["name"])
        if injured:
            print(f"Skipping {target['name']}: injury risk - {injury_reason}", flush=True)
            continue

        scored = score_player_target(
            target=target,
            pitcher=pitcher,
            pressure_score=pressure_score,
            count_edge=calculate_count_edge(balls, strikes) if target["role"] == "At Bat" else 0,
            role=target["role"],
        )
        scored_targets.append(scored)

    if not scored_targets:
        return

    scored_targets.sort(key=lambda x: x["best_score"], reverse=True)
    best_target = scored_targets[0]

    game_spot = f"{half_display} {inning_display} | {outs} outs | Count {balls}-{strikes}"
    base_text = runners_summary(offense)

    alert_type = None
    alert_score = 0
    msg = None

    # Predictive alerts first: on-deck/in-hole before market lock.
    future_targets = [x for x in scored_targets if x["target"]["role"] in ["On Deck", "In Hole"]]
    future_targets.sort(key=lambda x: x["best_score"], reverse=True)

    if future_targets and future_targets[0]["best_score"] >= MIN_GET_READY_SCORE and pressure_score >= 70:
        target = future_targets[0]
        alert_type = "GET_READY"
        alert_score = target["best_score"]
        msg = build_get_ready_alert(team, target, pressure_score, game_spot, base_text, inning_pressure)

    elif best_target["best_score"] >= MIN_MATCHUP_SCORE and pressure_score >= 55:
        alert_type = "MATCHUP"
        alert_score = best_target["best_score"]
        msg = build_matchup_alert(team, best_target, pitcher, game_spot)

    elif pressure_score >= MIN_PRESSURE_SCORE:
        alert_type = "PRESSURE"
        alert_score = pressure_score
        msg = build_pressure_alert(team, pressure_score, game_spot, base_text, inning_pressure)

    if not msg:
        print(
            f"{team} {game_spot} | Pressure {pressure_score} | "
            f"Best {best_target['target']['name']} {best_target['best_score']} | no alert",
            flush=True
        )
        return

    spot_key = f"{game_pk}-{inning}-{half}-{team}-{alert_type}"

    if not should_send_alert(spot_key, alert_score):
        print(f"Skipping duplicate/cooldown: {spot_key}", flush=True)
        return

    print(
        f"Sending {alert_type}: {team} | {best_target['target']['name']} | "
        f"score {alert_score} | pressure {pressure_score}",
        flush=True
    )

    broadcast(msg)


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


def main():
    broadcast("✅ MLB Predictive Betting Alert Bot is live.")

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
