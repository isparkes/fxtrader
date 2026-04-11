# FX Scalper — User Manual

## Overview

This tool generates intraday scalping signals for major FX pairs using a
two-timeframe approach: the **1h chart** sets the directional bias, and the
**5m chart** finds precise entry timing within that bias.  It can be used
interactively (one-shot signal checks) or as a long-running daemon that sends
email alerts.

---

## Quick-start

```bash
# 1. Create and activate the virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\Activate.ps1        # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure email (optional — required for daemon alerts)
cp .env.example .env
# edit .env with your SMTP credentials
```

---

## Interactive Mode (`indicator.py`)

Run on demand to get an immediate signal for one or more pairs.

### Basic usage

```bash
# Single pair (default: EURUSD)
python indicator.py

# Specific pair
python indicator.py --pair gbpusd

# All supported pairs at once
python indicator.py --all

# Suppress FLAT (no-signal) results
python indicator.py --all --quiet
```

### Supported pairs

| Key      | Ticker      | Description      |
|----------|-------------|------------------|
| eurusd   | EURUSD=X    | Euro / US Dollar |
| gbpusd   | GBPUSD=X    | Cable            |
| usdjpy   | USDJPY=X    | Dollar / Yen     |
| audusd   | AUDUSD=X    | Aussie Dollar    |
| usdcad   | USDCAD=X    | Dollar / Loonie  |
| usdchf   | USDCHF=X    | Dollar / Swissie |
| nzdusd   | NZDUSD=X    | Kiwi Dollar      |
| eurgbp   | EURGBP=X    | Euro / Sterling  |

### Output

Each signal panel shows:

| Field        | Meaning                                             |
|--------------|-----------------------------------------------------|
| Direction    | **BUY**, **SELL**, or **FLAT** (no signal)          |
| Entry        | Suggested entry price                               |
| Stop Loss    | Hard stop (ATR × 0.4 from entry)                   |
| Take Profit  | Wide ceiling (ATR × 3.0 from entry)                |
| R:R          | Risk-to-reward ratio                                |
| ATR(14) 1h   | 1h Average True Range — volatility measure         |
| 1h Trend     | Price position relative to EMA50                   |
| 1h RSI       | 1h RSI(14) — momentum gate                         |
| MACD Hist    | 1h MACD histogram — momentum direction             |
| Basis        | Which pattern fired and on which 5m bar            |

All signals are appended to `signals.jsonl` in the current directory.

### Signal logic summary

**Trend gates (1h — all three must pass):**
1. Price above/below EMA50
2. MACD histogram positive/negative **and** building (larger than previous bar)
3. RSI(14) above 50 for BUY, below 50 for SELL

**Entry patterns (5m — first match wins):**
- **Pattern A** — EMA8 crosses EMA21 in trend direction, confirmed by RSI(7) and Stochastic
- **Pattern C** — MACD histogram flips sign in trend direction while price is on the right side of EMA21

**Session filter:** entries only fire during **07:00–16:00 UTC** (London / NY overlap)

**Risk management:**
- Stop loss: ATR × 0.4 (~4–8 pips)
- Take profit: ATR × 3.0 (wide ceiling)
- Stop moves to **breakeven** once price reaches 80 % of TP distance
- **Cooldown:** no new entry for 30 minutes after a loss

---

## Daemon Mode (`daemon.py`)

Runs indefinitely, polling every 5 minutes (configurable), and sends email
alerts when a trade opens, the stop moves to breakeven, or the trade closes.

### Email alerts

| Event      | Sent when …                                        |
|------------|----------------------------------------------------|
| **OPEN**   | A BUY or SELL signal fires on a watched pair       |
| **BE**     | Price reaches 80 % of TP — stop moved to entry     |
| **CLOSE**  | Stop loss or take profit is hit                    |

No email is sent for FLAT bars or while a position is already open.

### Email setup

1. Copy the template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your credentials:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=you@gmail.com
   SMTP_PASS=xxxx-xxxx-xxxx-xxxx   # Gmail App Password
   MAIL_TO=you@gmail.com
   ```

   > **Gmail users:** Generate an *App Password* at
   > https://myaccount.google.com/apppasswords — do not use your main password.
   > Other providers (Outlook, Fastmail, etc.) work identically; update
   > `SMTP_HOST` and `SMTP_PORT` accordingly.

3. To send to multiple recipients, comma-separate `MAIL_TO`:
   ```
   MAIL_TO=trader@example.com,alerts@example.com
   ```

### Starting the daemon

```bash
# Watch all pairs (default), poll every 5 minutes
python daemon.py

# Watch a single pair
python daemon.py --pair eurusd

# Custom poll interval (seconds)
python daemon.py --interval 60

# Test without sending emails — events are logged to stdout instead
python daemon.py --dry-run
```

### Running in the background (macOS / Linux)

```bash
# Start in background, append output to a log file
nohup python daemon.py >> fxtrader.log 2>&1 &

# Save the PID so you can stop it later
echo $! > fxtrader.pid

# Check it is running
ps -p $(cat fxtrader.pid)

# Tail the log
tail -f fxtrader.log

# Stop the daemon
kill $(cat fxtrader.pid)
```

### Running as a macOS LaunchAgent (start on login)

Create `~/Library/LaunchAgents/com.fxtrader.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.fxtrader.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOUR_NAME/Downloads/fxtrader/.venv/bin/python</string>
    <string>/Users/YOUR_NAME/Downloads/fxtrader/daemon.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOUR_NAME/Downloads/fxtrader</string>
  <key>StandardOutPath</key>
  <string>/Users/YOUR_NAME/Downloads/fxtrader/fxtrader.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOUR_NAME/Downloads/fxtrader/fxtrader.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.fxtrader.daemon.plist

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.fxtrader.daemon.plist
```

### Daemon output explained

```
2026-04-11 09:15:02  INFO     Initial fetch for EURUSD=X …
2026-04-11 09:15:08  INFO     EURUSD=X  cache seeded: 168 × 1h bars, 576 × 5m bars
2026-04-11 09:15:09  INFO     EURUSD  OPEN BUY @ 1.08542  SL=1.08490  TP=1.08698  (5.2/15.6 pips  R:R 1:3.00)
2026-04-11 09:20:04  INFO     EURUSD  BE triggered — SL moved to 1.08542
2026-04-11 09:35:10  INFO     EURUSD  CLOSE BUY — close_tp @ 1.08698  P&L 15.6 pips
```

---

## Backtesting (`backtest.py`)

Walk-forward simulation of the strategy against historical data.

```bash
# Scalp mode — 60 days, 5m entry bars
python backtest.py --pair eurusd

# Long mode — 730 days, 1h entry bars (larger sample)
python backtest.py --pair eurusd --long

# All pairs, scalp mode
python backtest.py --all

# All pairs, long mode
python backtest.py --all --long
```

Results are printed as a table and saved to `{pair}_backtest_trades.csv`.

---

## Data & Caching

| Mode             | 1h fetch  | 5m fetch | Refresh strategy                  |
|------------------|-----------|----------|-----------------------------------|
| Interactive      | 60 d      | 5 d      | Full download every run           |
| Daemon (startup) | 7 d       | 2 d      | Compact initial seed              |
| Daemon (running) | last 3 h  | last 15 m| Incremental — dedup & append      |

All data comes from Yahoo Finance (`yfinance`) and is for indicative purposes
only.  Yahoo Finance FX data may have gaps or slight inaccuracies; it is not
suitable as a primary feed for live order execution.

---

## Troubleshooting

**No signal generated**
- The 1h bias may be FLAT — all three trend gates must align simultaneously.
- The session filter blocks entries outside 07:00–16:00 UTC.
- ATR may be below the 2-pip floor (market too quiet).

**Emails not arriving**
- Run with `--dry-run` first to confirm signals are firing.
- Check the log for `SMTP authentication failed` or `Failed to send email`.
- Gmail users: ensure you are using an App Password, not your account password.
- Check your spam folder.

**`RuntimeError: No data returned`**
- Yahoo Finance occasionally rate-limits or returns empty responses.
  The daemon logs a warning and retries on the next poll; the interactive
  script exits with the error message.  Wait a minute and try again.

**`IndexError` on startup**
- The cache needs at least 30 bars before indicators are computed.
  This can happen if you start the daemon outside market hours when
  yfinance returns very few recent bars.  Try again during market hours.
