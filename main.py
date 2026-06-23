import os
import time
import requests
from datetime import datetime

BOT_TOKEN = os.environ["BOT_TOKEN"]
SHEET_WEBHOOK_URL = os.environ["SHEET_WEBHOOK_URL"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

# Final alert thresholds
MIN_FINAL_HIT_SCORE = int(os.getenv("MIN_FINAL_HIT_SCORE", "72"))
MIN_FINAL_RBI_SCORE = int(os.getenv("MIN_FINAL_RBI_SCORE", "75"))
MIN_FINAL_HR_SCORE = int(os.getenv("MIN_FINAL_HR_SCORE", "78"))

SEND_WEAK_BASES_LOADED_ALERTS = os.getenv("SEND_WEAK_BASES_LOADED_ALERTS", "false").lower() == "true"

sent_alerts = set()
active_loaded_spots = set()
player_stats_cache = {}
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


def american_label(score):
    if score >= 88:
        return "🔥 ELITE"
    if score >= 78:
        return "✅ STRONG"
    if score >= 68:
        return "🟡 DECENT"
    if score >= 55:
        return "⚪ LIGHT"
    return "❌ PASS"


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
        print("Sheet save response:", response.text, flush=True)
        data = response.json()
        return data.get("ok") is True
    except Exception as e:
        print("Sheet save error:", e, flush=True)
        return False


def broadcast(msg):
    subscribers = get_sheet_subscribers()

    for chat_id in subscribers:
        try:
            send_telegram(chat_id, msg)
        except Exception as e:
            print(f"Send error to {chat_id}:", e, flush=True)


def subscription_message():
    return (
        "✅ Subscription Active\n\n"
        "You’ll receive live MLB bases-loaded matchup alerts.\n\n"
        "The bot checks:\n"
        "• Batter strength\n"
        "• Pitcher weakness/strength\n"
        "• Batter-vs-pitcher history\n"
        "• Platoon advantage\n"
        "• Count, outs, and game situation\n\n"
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
                send_telegram(
                    chat_id,
                    "✅ MLB Matchup Alert Bot is online.\n\n"
                    "Subscription Status: ACTIVE\n\n"
                    "You’ll get alerts when a bases-loaded batter has a strong matchup edge."
                )
            else:
                send_telegram(
                    chat_id,
                    "⚠️ Bot is online, but you are NOT active.\n\n"
                    "Send /join to activate alerts."
                )

        else:
            send_telegram(
                chat_id,
                "⚾ MLB Matchup Alert Bot\n\n"
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
    """
    group: hitting or pitching
    Uses MLB StatsAPI season stats.
    """
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


def get_batter_vs_pitcher_history(batter_id, pitcher_id):
    """
    MLB StatsAPI does not always expose easy clean BvP through this endpoint.
    So this function is intentionally conservative.

    If the endpoint returns usable vsPlayer data, it scores it.
    If not, it returns neutral.
    """
    if not batter_id or not pitcher_id:
        return {
            "score": 0,
            "summary": "No BvP data",
            "has_real_sample": False,
        }

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
            result = {"score": 0, "summary": "No BvP data", "has_real_sample": False}
            player_stats_cache[cache_key] = result
            return result

        splits = stats_blocks[0].get("splits", [])

        if not splits:
            result = {"score": 0, "summary": "No BvP data", "has_real_sample": False}
            player_stats_cache[cache_key] = result
            return result

        stat = splits[0].get("stat", {})

        at_bats = safe_int(stat.get("atBats"))
        hits = safe_int(stat.get("hits"))
        home_runs = safe_int(stat.get("homeRuns"))
        walks = safe_int(stat.get("baseOnBalls"))
        strikeouts = safe_int(stat.get("strikeOuts"))
        avg = safe_float(stat.get("avg"))
        ops = safe_float(stat.get("ops"))

        score = 0

        if at_bats < 6:
            summary = f"BvP tiny sample: {hits}-{at_bats}, {home_runs} HR"
            result = {"score": 0, "summary": summary, "has_real_sample": False}
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

        if walks >= 2:
            score += 3

        score = max(-15, min(18, score))

        summary = f"BvP: {hits}-{at_bats}, {home_runs} HR, AVG {avg:.3f}, OPS {ops:.3f}"

        result = {
            "score": score,
            "summary": summary,
            "has_real_sample": True,
        }

        player_stats_cache[cache_key] = result
        return result

    except Exception as e:
        print("BvP error:", e, flush=True)
        result = {"score": 0, "summary": "BvP unavailable", "has_real_sample": False}
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
    hit_rate = hits / max(at_bats, 1)
    bb_rate = walks / pa
    k_rate = strikeouts / pa
    xbh = doubles + triples + hr
    xbh_rate = xbh / max(at_bats, 1)
    rbi_rate = rbi / pa

    hit_score = 45
    hit_score += avg * 80
    hit_score += obp * 35
    hit_score -= k_rate * 45

    rbi_score = 45
    rbi_score += obp * 25
    rbi_score += slg * 40
    rbi_score += rbi_rate * 100
    rbi_score += bb_rate * 25
    rbi_score -= k_rate * 30

    hr_score = 35
    hr_score += hr_rate * 750
    hr_score += slg * 35
    hr_score += xbh_rate * 90
    hr_score += ops * 12
    hr_score -= k_rate * 15

    return {
        "hit_score": clamp(hit_score),
        "rbi_score": clamp(rbi_score),
        "hr_score": clamp(hr_score),
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "hr": hr,
        "rbi": rbi,
        "pa": pa,
        "hr_rate": hr_rate,
        "k_rate": k_rate,
        "bb_rate": bb_rate,
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

    # Good pitcher penalties
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

    if k9 >= 10:
        contact_suppression += 10
        rbi_suppression += 7
        hr_suppression += 4
    elif k9 <= 7:
        contact_suppression -= 7
        rbi_suppression -= 5

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

    hit_edge = 0
    rbi_edge = 0
    hr_edge = 0

    if balls == 3 and strikes == 0:
        hit_edge += 5
        rbi_edge += 14
        hr_edge += 3
    elif balls == 3 and strikes == 1:
        hit_edge += 6
        rbi_edge += 12
        hr_edge += 5
    elif balls == 3 and strikes == 2:
        hit_edge += 2
        rbi_edge += 8
        hr_edge += 1
    elif balls == 2 and strikes == 0:
        hit_edge += 6
        rbi_edge += 7
        hr_edge += 5
    elif balls == 2 and strikes == 1:
        hit_edge += 4
        rbi_edge += 5
        hr_edge += 3
    elif balls == 0 and strikes == 2:
        hit_edge -= 12
        rbi_edge -= 10
        hr_edge -= 8
    elif balls == 1 and strikes == 2:
        hit_edge -= 8
        rbi_edge -= 7
        hr_edge -= 5
    elif balls == 0 and strikes == 1:
        hit_edge -= 4
        rbi_edge -= 3
        hr_edge -= 2

    return {
        "hit_edge": hit_edge,
        "rbi_edge": rbi_edge,
        "hr_edge": hr_edge,
    }


def calculate_outs_edge(outs):
    outs = safe_int(outs)

    if outs == 0:
        return {"hit": 2, "rbi": 8, "hr": 1, "label": "0 outs boosts RBI paths"}
    if outs == 1:
        return {"hit": 1, "rbi": 5, "hr": 0, "label": "1 out still allows sac-fly RBI"}
    if outs == 2:
        return {"hit": 0, "rbi": -3, "hr": 1, "label": "2 outs removes sac-fly RBI"}
    return {"hit": 0, "rbi": 0, "hr": 0, "label": "Outs unknown"}


def calculate_matchup_scores(batter_stats, pitcher_stats, bvp, balls, strikes, outs):
    batter = calculate_batter_profile(batter_stats)
    pitcher = calculate_pitcher_profile(pitcher_stats)
    count_edge = calculate_count_edge(balls, strikes)
    outs_edge = calculate_outs_edge(outs)

    # This is the actual edge logic:
    # batter ability - pitcher strength + BvP + live count + bases-loaded situation
    final_hit = (
        batter["hit_score"]
        - pitcher["contact_suppression"]
        + bvp["score"]
        + count_edge["hit_edge"]
        + outs_edge["hit"]
    )

    final_rbi = (
        batter["rbi_score"]
        - pitcher["rbi_suppression"]
        + bvp["score"]
        + count_edge["rbi_edge"]
        + outs_edge["rbi"]
        + 10  # bases-loaded RBI boost
    )

    final_hr = (
        batter["hr_score"]
        - pitcher["hr_suppression"]
        + bvp["score"]
        + count_edge["hr_edge"]
        + outs_edge["hr"]
    )

    return {
        "final_hit": clamp(final_hit),
        "final_rbi": clamp(final_rbi),
        "final_hr": clamp(final_hr),
        "batter": batter,
        "pitcher": pitcher,
        "bvp": bvp,
        "count_edge": count_edge,
        "outs_edge": outs_edge,
    }


def choose_best_angle(scores):
    hit = scores["final_hit"]
    rbi = scores["final_rbi"]
    hr = scores["final_hr"]

    qualified = []

    if hit >= MIN_FINAL_HIT_SCORE:
        qualified.append(("HIT", hit))

    if rbi >= MIN_FINAL_RBI_SCORE:
        qualified.append(("RBI", rbi))

    if hr >= MIN_FINAL_HR_SCORE:
        qualified.append(("HOME RUN", hr))

    if not qualified:
        return None, "PASS"

    qualified.sort(key=lambda x: x[1], reverse=True)

    best = qualified[0][0]

    if best == "RBI":
        return "RBI", "Put money on RBI if available. If not, look at Hit/Total Bases."
    if best == "HIT":
        return "HIT", "Put money on Hit if available. RBI is secondary."
    if best == "HOME RUN":
        return "HOME RUN", "HR is live. This is the grand slam lottery angle."

    return best, "Playable matchup."


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


def get_on_deck_batter(data):
    linescore = data.get("liveData", {}).get("linescore", {})
    offense = linescore.get("offense", {})
    on_deck = offense.get("onDeck", {})

    return {
        "id": on_deck.get("id"),
        "name": on_deck.get("fullName", "Unknown"),
    }


def get_current_play_count(data):
    current_play = data.get("liveData", {}).get("plays", {}).get("currentPlay", {})
    count = current_play.get("count", {})

    return {
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
    }


def build_bet_alert_message(
    offense_team,
    half,
    inning,
    outs,
    balls,
    strikes,
    batter_name,
    pitcher_name,
    away_team,
    home_team,
    away_runs,
    home_runs,
    scores,
    best_angle,
    recommendation,
    on_deck_name=None
):
    batter = scores["batter"]
    pitcher = scores["pitcher"]
    bvp = scores["bvp"]

    hit = scores["final_hit"]
    rbi = scores["final_rbi"]
    hr = scores["final_hr"]

    return (
        f"🚨 BET ALERT — PUT MONEY ON THIS PLAYER NOW\n\n"
        f"Best Angle: {best_angle}\n"
        f"{recommendation}\n\n"
        f"{offense_team} batting\n"
        f"{half} {inning} | {outs} outs | Count {balls}-{strikes}\n\n"
        f"Batter: {batter_name}\n"
        f"Pitcher: {pitcher_name}\n"
        f"On Deck: {on_deck_name or 'Unknown'}\n\n"
        f"Scores:\n"
        f"Hit: {hit}/100 {american_label(hit)}\n"
        f"RBI: {rbi}/100 {american_label(rbi)}\n"
        f"HR: {hr}/100 {american_label(hr)}\n\n"
        f"Why:\n"
        f"• Bases loaded\n"
        f"• Batter AVG/OBP/SLG: {batter['avg']:.3f}/{batter['obp']:.3f}/{batter['slg']:.3f}\n"
        f"• Batter HR: {batter['hr']} | RBI: {batter['rbi']}\n"
        f"• Pitcher ERA/WHIP: {pitcher['era']:.2f}/{pitcher['whip']:.2f}\n"
        f"• Pitcher HR/9: {pitcher['hr9']:.2f} | K/9: {pitcher['k9']:.2f} | BB/9: {pitcher['bb9']:.2f}\n"
        f"• {bvp['summary']}\n\n"
        f"Score:\n"
        f"{away_team}: {away_runs}\n"
        f"{home_team}: {home_runs}\n\n"
        f"Time: {datetime.now().strftime('%I:%M:%S %p')}"
    )


def build_watch_message(
    offense_team,
    half,
    inning,
    outs,
    balls,
    strikes,
    batter_name,
    pitcher_name,
    away_team,
    home_team,
    away_runs,
    home_runs,
    scores
):
    return (
        f"👀 BASES LOADED — WATCH ONLY\n\n"
        f"No strong bet edge yet.\n\n"
        f"{offense_team} batting\n"
        f"{half} {inning} | {outs} outs | Count {balls}-{strikes}\n\n"
        f"Batter: {batter_name}\n"
        f"Pitcher: {pitcher_name}\n\n"
        f"Scores:\n"
        f"Hit: {scores['final_hit']}/100\n"
        f"RBI: {scores['final_rbi']}/100\n"
        f"HR: {scores['final_hr']}/100\n\n"
        f"Score:\n"
        f"{away_team}: {away_runs}\n"
        f"{home_team}: {home_runs}"
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
        "first" in offense and
        "second" in offense and
        "third" in offense
    )

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
    pitcher_name = pitcher_obj.get("name")

    on_deck = get_on_deck_batter(data)
    on_deck_name = on_deck.get("name")

    count = get_current_play_count(data)
    balls = count["balls"]
    strikes = count["strikes"]

    spot_key = f"{game_pk}-{inning}-{half}"
    batter_spot_key = f"{game_pk}-{inning}-{half}-{batter_id}-{outs}-{balls}-{strikes}"

    if not bases_loaded:
        active_loaded_spots.discard(spot_key)
        return

    if batter_spot_key in sent_alerts:
        return

    batter_stats = get_player_season_stats(batter_id, "hitting")
    pitcher_stats = get_player_season_stats(pitcher_id, "pitching")
    bvp = get_batter_vs_pitcher_history(batter_id, pitcher_id)

    scores = calculate_matchup_scores(
        batter_stats=batter_stats,
        pitcher_stats=pitcher_stats,
        bvp=bvp,
        balls=balls,
        strikes=strikes,
        outs=outs,
    )

    best_angle, recommendation = choose_best_angle(scores)

    print(
        f"{batter_name} vs {pitcher_name} | "
        f"HIT {scores['final_hit']} RBI {scores['final_rbi']} HR {scores['final_hr']} | "
        f"{best_angle}",
        flush=True
    )

    if best_angle:
        msg = build_bet_alert_message(
            offense_team=offense_team,
            half=half,
            inning=inning,
            outs=outs,
            balls=balls,
            strikes=strikes,
            batter_name=batter_name,
            pitcher_name=pitcher_name,
            away_team=away_team,
            home_team=home_team,
            away_runs=away_runs,
            home_runs=home_runs,
            scores=scores,
            best_angle=best_angle,
            recommendation=recommendation,
            on_deck_name=on_deck_name,
        )

        broadcast(msg)
        sent_alerts.add(batter_spot_key)
        active_loaded_spots.add(spot_key)
        return

    if SEND_WEAK_BASES_LOADED_ALERTS and spot_key not in active_loaded_spots:
        msg = build_watch_message(
            offense_team=offense_team,
            half=half,
            inning=inning,
            outs=outs,
            balls=balls,
            strikes=strikes,
            batter_name=batter_name,
            pitcher_name=pitcher_name,
            away_team=away_team,
            home_team=home_team,
            away_runs=away_runs,
            home_runs=home_runs,
            scores=scores,
        )

        broadcast(msg)
        active_loaded_spots.add(spot_key)
        sent_alerts.add(batter_spot_key)


def main():
    broadcast("✅ MLB Matchup Alert Bot is live.")

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
