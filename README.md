# Grand Slam Tracker

Grand Slam Tracker is a Telegram worker that watches live MLB games and sends predictive live-betting alerts. It combines MLB Stats API data, current base/out/count state, upcoming batting order, pitcher weakness, and subscriber data stored behind a sheet webhook.

## What the bot does

1. Polls Telegram for `/start`, `/join`, `/stop`, and `/status`.
2. Stores subscriber status through `SHEET_WEBHOOK_URL`.
3. Polls MLB's schedule for live games on today's date.
4. Fetches each live game's feed.
5. Scores upcoming hitters and inning pressure.
6. Sends `GET_READY`, `MATCHUP`, or `PRESSURE` alerts to active subscribers.
7. Records each sent alert with a tracking ID so users can report the result.

## Environment variables

Required:

- `BOT_TOKEN`: Telegram bot token.
- `SHEET_WEBHOOK_URL`: Webhook that supports `GET` for active subscribers and `POST` for subscriber status updates.

Optional:

- `POLL_SECONDS`: Poll interval. Default: `8`.
- `ONLY_BASES_LOADED`: Only alert with bases loaded. Default: `false`.
- `ALERT_COOLDOWN_SECONDS`: Minimum seconds before repeat alert in same spot. Default: `300`.
- `MAX_ALERTS_PER_HALF_INNING`: Alert cap per game/inning/half/type/player key. Default: `1`.
- `ALERT_MEMORY_SECONDS`: How long duplicate-alert memory is retained. Default: `14400`.
- `LOOKAHEAD_BATTERS`: Batters ahead to score. Default: `4`.
- `MIN_TARGET_BATTERS_AWAY`: Minimum distance from current batter. Default: `2`.
- `MIN_GET_READY_SCORE`: Get-ready threshold. Default: `88`.
- `MIN_MATCHUP_SCORE`: Matchup threshold. Default: `90`.
- `MIN_PRESSURE_SCORE`: Pressure threshold. Default: `92`.
- `FRESH_INJURY_DAYS`: Injury transaction lookback. Default: `14`.
- `STATS_CACHE_SECONDS`: Player stats cache TTL. Default: `900`.
- `INJURY_CACHE_SECONDS`: Injury cache TTL. Default: `3600`.
- `RECENT_INJURY_NAMES`: Comma-separated manual skip list.
- `TELEGRAM_OFFSET_FILE`: File used to persist Telegram polling offset. Default: `.telegram_offset`.
- `RESULTS_FILE`: JSON file used to persist alert results. Default: `alert_results.json`.
- `RESULTS_RECAP_DAYS`: Lookback window for `/recap`. Default: `1`.
- `MAX_RECAP_ITEMS`: Number of recent/open alerts shown in recaps. Default: `5`.

## Telegram commands

- `/join`: Start alerts.
- `/stop`: Stop alerts.
- `/status`: Check subscription status.
- `/pending`: Show open tracked alerts.
- `/recap`: Show recent performance.
- `/win ID`: Mark an alert as a win.
- `/loss ID`: Mark an alert as a loss.
- `/push ID`: Mark an alert as a push/void.
- `/nomarket ID`: Mark an alert as unavailable or locked.

Each alert includes its own tracking ID and example report commands.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Set the required environment variables before running:

```powershell
$env:BOT_TOKEN = "your-telegram-token"
$env:SHEET_WEBHOOK_URL = "your-sheet-webhook-url"
python main.py
```

## Deployment

The worker command is declared in `Procfile`:

```text
worker: python main.py
```

Configure the required environment variables on the hosting platform before starting the worker.

## Tests

```powershell
python -m unittest
```

The tests cover score helpers, cache expiry, alert throttling, batting-order targeting, current pitcher detection, and result tracking.
