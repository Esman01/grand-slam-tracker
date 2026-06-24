# Grand Slam Tracker

Grand Slam Tracker is a Telegram worker that watches live MLB games and sends predictive live-betting alerts. It combines MLB Stats API data, current base/out/count state, upcoming batting order, pitcher weakness, and subscriber data stored behind a sheet webhook.

## What the bot does

1. Polls Telegram for `/start`, `/join`, `/stop`, and `/status`.
2. Stores subscriber status through `SHEET_WEBHOOK_URL`.
3. Polls MLB's schedule for live games on today's date.
4. Fetches each live game's feed.
5. Scores upcoming hitters and inning pressure.
6. Sends `GET_READY`, `MATCHUP`, `PRESSURE`, or extreme `LIVE_BET` alerts to active subscribers.
7. Records each sent alert with a tracking ID so users can report the result.
8. Posts alert and result telemetry to the sheet webhook for the `alerts` tab.
9. Logs skipped alert candidates to `candidate_log.json` for tuning.

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
- `MAX_ALERTS_PER_GAME`: Global alert cap per game. Default: `2`.
- `MAX_ALERTS_PER_TEAM_PER_GAME`: Alert cap per team per game. Default: `1`.
- `MAX_ALERTS_PER_PLAYER_PER_GAME`: Alert cap per player per game. Default: `1`.
- `GLOBAL_ALERT_COOLDOWN_SECONDS`: Minimum seconds between any two sent alerts. Default: `600`.
- `PLAYER_SCORE_IMPROVEMENT`: Required score improvement before the same player can alert again. Default: `10`.
- `LOOKAHEAD_BATTERS`: Batters ahead to score. Default: `4`.
- `MIN_TARGET_BATTERS_AWAY`: Minimum distance from current batter. Default: `2`.
- `MAX_TARGET_BATTERS_AWAY`: Maximum distance from current batter. Default: `4`.
- `PREFERRED_MARKET_DISTANCE`: Preferred batting-order distance for available markets. Default: `3`.
- `MIN_GET_READY_SCORE`: Get-ready threshold. Default: `90`.
- `MIN_MATCHUP_SCORE`: Matchup threshold. Default: `92`.
- `MIN_PRESSURE_SCORE`: Pressure threshold. Default: `90`.
- `MIN_PLAYER_MARKET_SCORE`: Minimum score for a listed player market. Default: `90`.
- `MIN_MATCHUP_MARKET_SCORE`: Minimum market score for matchup alerts. Default: `92`.
- `MIN_ALERT_PRESSURE_SCORE`: Minimum pressure score before player alerts are allowed. Default: `60`.
- `STRONG_PITCHER_PRESSURE_SCORE`: Pressure needed to alert against a strong pitcher, with bases loaded. Default: `75`.
- `MAX_MARKETS_PER_ALERT`: Maximum player markets listed in one alert. Default: `2`.
- `SECONDARY_MARKET_MAX_DROP`: Maximum score drop from the top market for secondary markets. Default: `4`.
- `MIN_MARKET_DISPLAY_SCORE`: Minimum market score shown in Telegram. Default: `88`.
- `AUTO_MARKET_PENALTIES`: Penalize markets with poor availability or poor graded results. Default: `true`.
- `MARKET_AVAILABILITY_MIN_SAMPLE`: Minimum sample before market penalties apply. Default: `10`.
- `LOW_MARKET_AVAILABILITY_RATE`: Availability rate that triggers market penalties. Default: `.35`.
- `MARKET_PENALTY_POINTS`: Score penalty for poor markets. Default: `8`.
- `SCORE_CALIBRATION_MIN_SAMPLE`: Minimum high-score graded sample before score calibration applies. Default: `10`.
- `SCORE_CALIBRATION_MIN_WIN_RATE`: Minimum win rate expected from high-score alerts. Default: `.50`.
- `SCORE_CALIBRATION_PENALTY`: Score penalty when high-score alerts underperform. Default: `5`.
- `MIN_PLAYER_OPS`: Minimum OPS for matchup alerts. Default: `.750`.
- `MIN_PLAYER_SLG`: Minimum SLG for matchup alerts. Default: `.400`.
- `MIN_PLAYER_PA`: Minimum plate appearances for matchup alerts. Default: `80`.
- `MIN_POWER_SLG_FOR_HR`: Minimum SLG for HR markets to stay uncapped. Default: `.450`.
- `MIN_POWER_HR_RATE`: Minimum HR rate for HR markets to stay uncapped. Default: `.035`.
- `SEND_SILVER_ALERTS`: Send SILVER alerts. Default: `false`.
- `SHOW_DEBUG`: Include raw debug stats in Telegram messages. Default: `false`.
- `FRESH_INJURY_DAYS`: Injury transaction lookback. Default: `14`.
- `STATS_CACHE_SECONDS`: Player stats cache TTL. Default: `900`.
- `INJURY_CACHE_SECONDS`: Injury cache TTL. Default: `3600`.
- `RECENT_INJURY_NAMES`: Comma-separated manual skip list.
- `TELEGRAM_OFFSET_FILE`: File used to persist Telegram polling offset. Default: `.telegram_offset`.
- `RESULTS_FILE`: JSON file used to persist alert results. Default: `alert_results.json`.
- `CANDIDATE_LOG_FILE`: JSON file used to persist sent and skipped candidates. Default: `candidate_log.json`.
- `RESULTS_RECAP_DAYS`: Lookback window for `/recap`. Default: `1`.
- `MAX_RECAP_ITEMS`: Number of recent/open alerts shown in recaps. Default: `5`.

## Telegram commands

- `/join`: Start alerts.
- `/stop`: Stop alerts.
- `/status`: Check subscription status.
- `/pending`: Show open tracked alerts.
- `/recap`: Show recent performance.
- `/markets`: Show market availability and no-market counts.
- `/details ID`: Show the hidden debug breakdown for one alert.
- `/settle ID`: Start a quick result prompt.
- `/win ID`: Mark an alert as a win.
- `/loss ID`: Mark an alert as a loss.
- `/push ID`: Mark an alert as a push/void.
- `/nomarket ID`: Mark an alert as unavailable or locked.

Each alert includes its own tracking ID and example report commands.

## Sheet telemetry

The same `SHEET_WEBHOOK_URL` handles subscribers and alert telemetry. Alert creation posts include `kind: "alert"` and result updates include `kind: "alert_result"`. The companion Apps Script should route those payloads to an `alerts` tab.

## Alert quality filters

Player alerts only list markets that clear the configured market threshold, so weaker watch-list picks are omitted. The bot also skips low-pressure spots, two-strike/two-out timing, poor hitter profiles, unreliable pitcher samples, first-inning bases-empty player spots, and strong-pitcher situations unless pressure is extreme.

Alerts are tiered as `GOLD`, `SILVER`, or `WATCHLIST`. Telegram sends `GOLD` by default, sends `SILVER` only when enabled, and logs `WATCHLIST` candidates without sending them. Market ranking favors Hits+Runs+RBIs, Total Bases, and Hits before RBI or Home Run. Home Run markets only appear when the score is elite and the player has a real power profile.

Telegram alert copy is intentionally short: player/team, best bet, backup bet when strong enough, find path, game spot, why it passed, why the alert is early, and tracking ID. Raw stats and model breakdowns are hidden behind `/details ID`.

`/recap` includes sent alerts, record, win rate by alert type, market availability rate, top skipped reasons, and average score of winners versus losers. `/markets` focuses only on market availability. `/pending` only shows ungraded sent alerts.

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

The tests cover score helpers, score normalization, HR caps, player quality gates, alert throttling, market ranking, alert tiering, batting-order targeting, result tracking, recap summaries, and sheet telemetry calls.
