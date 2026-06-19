import os
import time
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "8"))

SUBSCRIBERS_FILE = "subscribers.txt"
sent_alerts = set()


def get_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": msg
        },
        timeout=10
    )


def broadcast(msg):
    subscribers = get_subscribers()

    for chat_id in subscribers:
        send_telegram(chat_id, msg)


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

    inning = linescore.get("currentInningOrdinal", "?")
    half = linescore.get("inningHalf", "?")
    outs = linescore.get("outs", "?")

    batter = offense.get("batter", {}).get("fullName", "Unknown batter")
    team = offense.get("team", {}).get("name", "Unknown team")

    alert_key = f"{game_pk}-{inning}-{half}-{outs}-{batter}"

    if alert_key in sent_alerts:
        return

    sent_alerts.add(alert_key)

    msg = (
        f"🚨 BASES LOADED\n\n"
        f"{team} batting\n"
        f"{half} {inning}\n"
        f"{outs} outs\n"
        f"Batter: {batter}\n\n"
        f"Grand slam spot 👀"
    )

    broadcast(msg)


def main():
    broadcast("✅ Grand Slam Tracker is live.")

    while True:
        try:
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
