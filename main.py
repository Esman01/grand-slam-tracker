import os
import time
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

SUBSCRIBERS_FILE = "subscribers.txt"
sent_alerts = set()
last_update_id = None


def get_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as file:
            return set(line.strip() for line in file if line.strip())
    except FileNotFoundError:
        return set()


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": chat_id, "text": msg},
        timeout=10
    )


def broadcast(msg):
    for chat_id in get_subscribers():
        send_telegram(chat_id, msg)


def save_subscriber(chat_id):
    chat_id = str(chat_id)
    subscribers = get_subscribers()

    if chat_id not in subscribers:
        with open(SUBSCRIBERS_FILE, "a") as file:
            file.write(chat_id + "\n")

        send_telegram(chat_id, "✅ You’re subscribed to Grand Slam Tracker alerts.")
    else:
        send_telegram(chat_id, "✅ You’re already subscribed.")


def remove_subscriber(chat_id):
    chat_id = str(chat_id)
    subscribers = get_subscribers()

    if chat_id in subscribers:
        subscribers.remove(chat_id)

        with open(SUBSCRIBERS_FILE, "w") as file:
            for sub in sorted(subscribers):
                file.write(sub + "\n")

        send_telegram(chat_id, "❌ You’ve been unsubscribed.")
    else:
        send_telegram(chat_id, "You were not subscribed.")


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
        text = message.get("text", "")

        chat_id = chat.get("id")

        if not chat_id:
            continue

        if text == "/start":
            save_subscriber(chat_id)

        elif text == "/status":
            send_telegram(chat_id, "✅ Grand Slam Tracker is online and watching live MLB games.")

        elif text == "/stop":
            remove_subscriber(chat_id)


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

    if not bases_loaded:
        return

    teams = data.get("gameData", {}).get("teams", {})
    away_team = teams.get("away", {}).get("name", "Away")
    home_team = teams.get("home", {}).get("name", "Home")

    away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0)
    home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0)

    inning = linescore.get("currentInningOrdinal", "?")
    half = linescore.get("inningHalf", "?")
    outs = linescore.get("outs", "?")

    batter = offense.get("batter", {}).get("fullName", "Unknown batter")
    team = offense.get("team", {}).get("name", "Unknown team")

    alert_key = f"{game_pk}-{inning}-{half}-{outs}-{batter}-{away_runs}-{home_runs}"

    if alert_key in sent_alerts:
        return

    sent_alerts.add(alert_key)

    msg = (
        f"🚨 BASES LOADED\n\n"
        f"{team} batting\n"
        f"{half} {inning}\n"
        f"{outs} outs\n"
        f"Batter: {batter}\n\n"
        f"Score:\n"
        f"{away_team}: {away_runs}\n"
        f"{home_team}: {home_runs}\n\n"
        f"Grand slam spot 👀"
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
