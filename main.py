import os
import time
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
SHEET_WEBHOOK_URL = os.environ["SHEET_WEBHOOK_URL"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

sent_alerts = set()
active_loaded_spots = set()
last_update_id = None


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
        "status": status
    }

    try:
        requests.post(SHEET_WEBHOOK_URL, json=payload, timeout=10)
        return True
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


def check_telegram_messages():
    global last_update_id

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {}

    if last_update_id is not None:
        params["offset"] = last_update_id + 1

    data = requests.get(url, params=params, timeout=10).json()

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

        if text == "/start":
            if save_subscriber(chat_id, username, first_name, "active"):
                send_telegram(chat_id, "✅ You’re subscribed to Grand Slam Tracker alerts.")
            else:
                send_telegram(chat_id, "⚠️ Subscription failed. Try again later.")

        elif text == "/stop":
            if save_subscriber(chat_id, username, first_name, "inactive"):
                send_telegram(chat_id, "❌ You’ve been unsubscribed.")
            else:
                send_telegram(chat_id, "⚠️ Unsubscribe failed. Try again later.")

        elif text == "/status":
            send_telegram(chat_id, "✅ Grand Slam Tracker is online and watching live MLB games.")


def get_today_games():
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1"
    data = requests.get(url, timeout=10).json()

    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            status = game.get("status", {}).get("abstractGameState")

            if status == "Live":
                games.append(game.get("gamePk"))

    return games


def check_game(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    data = requests.get(url, timeout=10).json()

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
    batter = offense.get("batter", {}).get("fullName", "Unknown batter")

    spot_key = f"{game_pk}-{inning}-{half}"
    score_key = f"{game_pk}-{inning}-{half}-{away_runs}-{home_runs}"

    if not bases_loaded:
        active_loaded_spots.discard(spot_key)
        return

    if spot_key not in active_loaded_spots:
        active_loaded_spots.add(spot_key)

        msg = (
            f"🚨 BASES LOADED\n\n"
            f"{offense_team} batting\n"
            f"{half} {inning}\n"
            f"{outs} outs\n"
            f"Batter: {batter}\n\n"
            f"Score:\n"
            f"{away_team}: {away_runs}\n"
            f"{home_team}: {home_runs}\n\n"
            f"Grand slam spot 👀"
        )

        broadcast(msg)
        sent_alerts.add(score_key)
        return

    if score_key not in sent_alerts:
        sent_alerts.add(score_key)

        msg = (
            f"⚾ SCORE CHANGED — BASES STILL LOADED\n\n"
            f"{offense_team} batting\n"
            f"{half} {inning}\n"
            f"{outs} outs\n"
            f"Batter: {batter}\n\n"
            f"Score:\n"
            f"{away_team}: {away_runs}\n"
            f"{home_team}: {home_runs}"
        )

        broadcast(msg)


def main():
    broadcast("✅ Grand Slam Tracker is live.")

    while True:
        try:
            check_telegram_messages()

            games = get_today_games()
            print(f"Checking {len(games)} live games...", flush=True)

            for game_pk in games:
                if game_pk:
                    check_game(game_pk)

        except Exception as e:
            print("Error:", e, flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
