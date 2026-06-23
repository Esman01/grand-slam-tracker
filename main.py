import os
import time
import requests
from datetime import datetime, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
SHEET_WEBHOOK_URL = os.environ["SHEET_WEBHOOK_URL"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

MIN_HIT_SCORE = int(os.getenv("MIN_HIT_SCORE", "82"))
MIN_RBI_SCORE = int(os.getenv("MIN_RBI_SCORE", "86"))
MIN_HR_SCORE = int(os.getenv("MIN_HR_SCORE", "88"))
MIN_K_SCORE = int(os.getenv("MIN_K_SCORE", "88"))

FRESH_INJURY_DAYS = int(os.getenv("FRESH_INJURY_DAYS", "14"))

# Optional manual safety list:
# RECENT_INJURY_NAMES="Mike Trout,Aaron Judge"
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
    return "PLAYABLE"


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
        "You’ll receive strong MLB live bet alerts.\n\n"
        "The bot looks for:\n"
        "• Batter Hit spots\n"
        "• Batter RBI spots\n"
        "• Batter HR spots\n"
        "• Strikeout spots\n"
        "• Batter vs pitcher matchup edge\n"
        "• Bases loaded leverage\n"
        "• Recent injury risk\n\n"
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
    """
    Safety filter:
    - Skips player if manually listed in RECENT_INJURY_NAMES.
    - Tries MLB transactions endpoint for recent injury reinstatements.
    - If endpoint fails, does NOT block the player.
    """

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

        injury_words = [
            "injured list",
            "injury list",
            "il",
            "reinstated",
            "activated",
        ]

        for tx in transactions:
            desc = (
                tx.get("description", "")
                or tx.get("typeDesc", "")
                or tx.get("typeCode", "")
            ).lower()

            if "reinstated" in desc or "activated" in desc:
                if any(word in desc for word in injury_words):
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

    hit_rate = hits / max(at_bats, 1)
    hr_rate = hr / pa
    bb_rate = walks / pa
    k_rate = strikeouts / pa
    xbh_rate = (doubles + triples + hr) / max(at_bats, 1)
    rbi_rate = rbi / pa

    hit_score = 45 + (avg * 85) + (obp * 35) - (k_rate * 45)

    rbi_score = (
        45
        + (obp * 25)
        + (slg * 42)
        + (rbi_rate * 110)
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

    batter_k_risk = 40 + (k_rate * 120) - (bb_rate * 35) - (avg * 25)

    return {
        "hit_score": clamp(hit_score),
        "rbi_score": clamp(rbi_score),
        "hr_score": clamp(hr_score),
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
    strikeout_boost = 0

    if era <= 3.25:
        contact_suppression += 8
        rbi_suppression += 8
    elif era >= 5.00:
        contact_suppression -= 8
        rbi_suppression -= 8

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
        strikeout_boost += 20
    elif k9 >= 9:
        strikeout_boost += 12
    elif k9 <= 7:
        contact_suppression -= 7
        rbi_suppression -= 5
        strikeout_boost -= 8

    if hr9 <= 0.80:
        hr_suppression += 12
    elif hr9 >= 1.40:
        hr_suppression -= 14
    elif hr9 >= 1.10:
        hr_suppression -= 7

    if bb9 >= 4.0:
        rbi_suppression -= 10
    elif bb9 <= 2.0:
        rbi_suppression += 5

    if h9 >= 9.5:
        contact_suppression -= 8
    elif h9 <= 7.0:
        contact_suppression += 6

    return {
        "contact_suppression": contact_suppression,
        "rbi_suppression": rbi_suppression,
        "hr_suppression": hr_suppression,
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

    edge = {
        "hit": 0,
        "rbi": 0,
        "hr": 0,
        "k": 0,
    }

    if balls == 3 and strikes == 0:
        edge["hit"] += 5
        edge["rbi"] += 14
        edge["hr"] += 3
        edge["k"] -= 18

    elif balls == 3 and strikes == 1:
        edge["hit"] += 6
        edge["rbi"] += 12
        edge["hr"] += 5
        edge["k"] -= 10

    elif balls == 3 and strikes == 2:
        edge["hit"] += 2
        edge["rbi"] += 8
        edge["hr"] += 1
        edge["k"] += 8

    elif balls == 2 and strikes == 0:
        edge["hit"] += 6
        edge["rbi"] += 7
        edge["hr"] += 5
        edge["k"] -= 10

    elif balls == 2 and strikes == 1:
        edge["hit"] += 4
        edge["rbi"] += 5
        edge["hr"] += 3
        edge["k"] -= 2

    elif balls == 0 and strikes == 2:
        edge["hit"] -= 12
        edge["rbi"] -= 10
        edge["hr"] -= 8
        edge["k"] += 20

    elif balls == 1 and strikes == 2:
        edge["hit"] -= 8
        edge["rbi"] -= 7
        edge["hr"] -= 5
        edge["k"] += 15

    elif balls == 0 and strikes == 1:
        edge["hit"] -= 4
        edge["rbi"] -= 3
        edge["hr"] -= 2
        edge["k"] += 5

    return edge


def calculate_outs_edge(outs):
    outs = safe_int(outs)

    if outs == 0:
        return {"hit": 2, "rbi": 8, "hr": 1, "k": 0}
    if outs == 1:
        return {"hit": 1, "rbi": 5, "hr": 0, "k": 0}
    if outs == 2:
        return {"hit": 0, "rbi": -3, "hr": 1, "k": 1}

    return {"hit": 0, "rbi": 0, "hr": 0, "k": 0}


def calculate_scores(batter_stats, pitcher_stats, bvp, balls, strikes, outs, bases_loaded):
    batter = calculate_batter_profile(batter_stats)
    pitcher = calculate_pitcher_profile(pitcher_stats)
    count = calculate_count_edge(balls, strikes)
    outs_edge = calculate_outs_edge(outs)

    bases_rbi_boost = 10 if bases_loaded else 0

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
        + bases_rbi_boost
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

    return {
        "hit": clamp(hit_score),
        "rbi": clamp(rbi_score),
        "hr": clamp(hr_score),
        "k": clamp(k_score),
        "batter": batter,
        "pitcher": pitcher,
        "bvp": bvp,
    }


def choose_bets(batter_name, scores, bases_loaded):
    bets = []

    if scores["hit"] >= MIN_HIT_SCORE:
        bets.append({
            "type": "HIT",
            "player": batter_name,
            "score": scores["hit"],
            "bet": f"{batter_name} Hit"
        })

    if bases_loaded and scores["rbi"] >= MIN_RBI_SCORE:
        bets.append({
            "type": "RBI",
            "player": batter_name,
            "score": scores["rbi"],
            "bet": f"{batter_name} RBI"
        })

    if scores["hr"] >= MIN_HR_SCORE:
        bets.append({
            "type": "HOME RUN",
            "player": batter_name,
            "score": scores["hr"],
            "bet": f"{batter_name} Home Run"
        })

    if scores["k"] >= MIN_K_SCORE:
        bets.append({
            "type": "STRIKEOUT",
            "player": batter_name,
            "score": scores["k"],
            "bet": f"{batter_name} Strikeout"
        })

    bets.sort(key=lambda x: x["score"], reverse=True)
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
    batter = scores["batter"]

    secondary = ""

    if len(all_bets) > 1:
        secondary_bet = all_bets[1]
        secondary = (
            f"\nSecondary: {secondary_bet['bet']} "
            f"({secondary_bet['score']}/100 {grade(secondary_bet['score'])})\n"
        )

    situation = "Bases loaded" if bases_loaded else "Live matchup"

    return (
        f"🚨 BET ALERT\n\n"
        f"Bet: {bet['bet']}\n"
        f"Confidence: {bet['score']}/100 {grade(bet['score'])}\n"
        f"{secondary}\n"
        f"{offense_team} batting\n"
        f"{half} {inning} | {outs} outs | Count {balls}-{strikes}\n\n"
        f"Scores:\n"
        f"Hit: {scores['hit']}/100\n"
        f"RBI: {scores['rbi']}/100\n"
        f"HR: {scores['hr']}/100\n"
        f"K: {scores['k']}/100\n\n"
        f"Why:\n"
        f"• {situation}\n"
        f"• Batter AVG/OBP/SLG: {batter['avg']:.3f}/{batter['obp']:.3f}/{batter['slg']:.3f}\n"
        f"• Batter HR: {batter['hr']} | RBI: {batter['rbi']}\n"
        f"• {bvp['summary']}\n\n"
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

    # For now, only fire betting alerts during bases-loaded leverage.
    # Change this to False if you want every strong live matchup.
    if not bases_loaded:
        return

    inning = linescore.get("currentInningOrdinal", "?")
    half = linescore.get("inningHalf", "?")
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
        print(
            f"Skipping {batter_name}: fresh injury risk - {injury_reason}",
            flush=True
        )
        sent_alerts.add(alert_key)
        return

    batter_stats = get_player_season_stats(batter_id, "hitting")
    pitcher_stats = get_player_season_stats(pitcher_id, "pitching")
    bvp = get_batter_vs_pitcher_history(batter_id, pitcher_id)

    scores = calculate_scores(
        batter_stats=batter_stats,
        pitcher_stats=pitcher_stats,
        bvp=bvp,
        balls=balls,
        strikes=strikes,
        outs=outs,
        bases_loaded=bases_loaded,
    )

    bets = choose_bets(
        batter_name=batter_name,
        scores=scores,
        bases_loaded=bases_loaded,
    )

    print(
        f"{batter_name} | "
        f"HIT {scores['hit']} RBI {scores['rbi']} HR {scores['hr']} K {scores['k']} | "
        f"BETS {bets}",
        flush=True
    )

    if not bets:
        return

    best_bet = bets[0]

    msg = build_alert_message(
        bet=best_bet,
        all_bets=bets,
        offense_team=offense_team,
        half=half,
        inning=inning,
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
    broadcast("✅ MLB Betting Alert Bot is live.")

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
