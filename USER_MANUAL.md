# FX Scalper — User Manual

## Overview

This tool generates intraday scalping signals for major FX pairs and BTCUSD
using a two-timeframe approach: the **1h chart** sets the directional bias,
and the **5m chart** finds precise entry timing within that bias.  It can be
used interactively (one-shot signal checks) or as a long-running daemon that
sends email alerts. The crypto daemon also places orders directly on Binance.

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
# for the crypto daemon also add BINANCE_API_KEY, BINANCE_API_SECRET, etc.
```

---

## Interactive Mode (per-pair indicator scripts)

Each active pair has its own indicator file. Run it directly to get an
immediate signal.

### Basic usage

```bash
# FX pairs
python indicator_eurusd.py
python indicator_gbpusd.py
python indicator_usdjpy.py
python indicator_audusd.py

# BTCUSD
python indicator_btcusd.py

# Suppress FLAT (no-signal) output
python indicator_eurusd.py --quiet
```

### Active pairs

| Script | Pair | Ticker |
|--------|------|--------|
| `indicator_eurusd.py` | Euro / US Dollar | `EURUSD=X` |
| `indicator_gbpusd.py` | Cable — British Pound / US Dollar | `GBPUSD=X` |
| `indicator_usdjpy.py` | US Dollar / Japanese Yen | `USDJPY=X` |
| `indicator_audusd.py` | Australian Dollar / US Dollar | `AUDUSD=X` |
| `indicator_btcusd.py` | Bitcoin / US Dollar | `BTC-USD` |

Each file contains its own tunable parameter block at the top. Changing
values there affects only that pair — `daemon_fx.py`, `daemon_crypto.py`, and
`backtest.py` all dispatch to the correct file automatically.

### Output

Each signal panel shows:

| Field        | Meaning                                             |
|--------------|-----------------------------------------------------|
| Direction    | **BUY**, **SELL**, or **FLAT** (no signal)          |
| Entry        | Suggested entry price                               |
| Stop Loss    | Hard stop (ATR × 0.4 for patterns A/C; clamped pullback extreme for D) |
| Take Profit  | Wide ceiling (ATR × 3.0 from entry)                |
| R:R          | Risk-to-reward ratio                                |
| ATR(14) 1h   | 1h Average True Range — volatility measure         |
| 1h Trend     | Price position relative to EMA50                   |
| 1h RSI       | 1h RSI(14) — momentum gate                         |
| MACD Hist    | 1h MACD histogram — momentum direction             |
| Basis        | Which pattern fired and on which bar               |

All signals are appended to `signals.jsonl` in the current directory.  The
daemons additionally write every OPEN / BE / CLOSE event to their trade logs
(`fx_trades.jsonl` / `crypto_trades.jsonl`).

### Signal logic summary

**Trend gates (1h — all three must pass):**
1. Price above/below EMA(50)
2. MACD histogram positive (BUY) or negative (SELL)
3. RSI(14) above 50 for BUY, below 50 for SELL

**4h agreement gate (Measure 4):**
- 4h close must also be above/below the **4h EMA(22)** in the same direction as the 1h bias
- Trades where 1h and 4h conflict are suppressed as FLAT

**Entry patterns (5m — first match wins):**
- **Pattern A** — EMA(8) crosses EMA(21) in trend direction, confirmed by RSI(7) and Stochastic
- **Pattern C** — 5m MACD histogram flips sign in trend direction while price is on the right side of EMA(21)
- **Pattern D** — 3 same-colour Heikin-Ashi candles → 1 opposing pullback candle → resumption in trend direction; stop anchored to pullback extreme

**Session filter:** FX entries only fire during **07:00–16:00 UTC** (London / NY overlap). BTCUSD has no session filter (24/7 market).

**Risk management:**
- Stop loss (A/C): ATR × 0.4 (~4–8 pips for FX; ~$200–800 for BTC via ATR scaling)
- Stop loss (D): pullback candle extreme ± buffer, clamped to `HA_SL_MIN_PIPS`–`HA_SL_MAX_PIPS`
- Take profit: ATR × 3.0 (wide ceiling)
- **Breakeven move:** stop moves to entry once price reaches a fraction of the TP distance (70% for EURUSD, 80% for all other pairs)
- **Cooldown:** no new entry for 30 minutes after a loss

---

## FX Daemon (`daemon_fx.py`)

Monitors EURUSD, GBPUSD, USDJPY, and AUDUSD indefinitely, polling every 5
minutes (configurable), and sends email alerts when a trade opens, the stop
moves to breakeven, or the trade closes.

### Email alerts

| Event      | Sent when …                                        |
|------------|----------------------------------------------------|
| **OPEN**   | A BUY or SELL signal fires on a watched pair       |
| **BE**     | Price reaches the breakeven trigger — stop moved to entry |
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

### Trade log and restart persistence

The daemon writes every OPEN, BE, and CLOSE event as a JSON line to
`fx_trades.jsonl` (mapped to `trades.jsonl` inside the container) in the
working directory.  On startup it replays this file to restore any open
positions and the month-to-date pip total, so you can stop and restart the
daemon without losing trade state.

Mount `fx_trades.jsonl` as a Docker volume to ensure persistence across
container restarts.

### Starting the daemon

```bash
# Watch all 4 FX pairs (default), poll every 5 minutes
python daemon_fx.py

# Watch a single pair
python daemon_fx.py --pair usdjpy

# Custom poll interval (seconds)
python daemon_fx.py --interval 60

# Test without sending emails — events are logged to stdout instead
python daemon_fx.py --dry-run
```

### Running in the background (macOS / Linux)

```bash
# Start in background, append output to a log file
nohup python daemon_fx.py >> fxtrader.log 2>&1 &

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
    <string>/Users/YOUR_NAME/Downloads/fxtrader/daemon_fx.py</string>
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

### FX daemon output explained

```
2026-04-11 09:15:02  INFO     Initial fetch for EURUSD=X …
2026-04-11 09:15:08  INFO     EURUSD=X  cache seeded: 168 × 1h bars, 576 × 5m bars
2026-04-11 09:15:09  INFO     EURUSD  OPEN BUY @ 1.08542  SL=1.08490  TP=1.08698  (5.2/15.6 pips  R:R 1:3.00)
2026-04-11 09:20:04  INFO     EURUSD  BE triggered — SL moved to 1.08542
2026-04-11 09:35:10  INFO     EURUSD  CLOSE BUY — close_tp @ 1.08698  P&L 15.6 pips
```

---

## Crypto Daemon (`daemon_crypto.py`)

Monitors BTCUSD continuously, places orders on Binance (via OCO), and sends
email alerts on OPEN / BE / CLOSE events. All money amounts are in USD
(one "pip" = $1.00 for BTC).

### Additional .env variables

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TESTNET=false          # true = paper-trade on Binance testnet
CRYPTO_RISK_USD=50             # max risk per trade in USD
CRYPTO_TRADE_SIZE_USD=1000     # max notional per trade in USD
```

### Starting the crypto daemon

```bash
# Monitor BTCUSD, poll every 5 minutes
python daemon_crypto.py

# Shorter poll interval
python daemon_crypto.py --interval 60

# Dry-run — log events, do not send emails or place Binance orders
python daemon_crypto.py --dry-run
```

### Running in the background

```bash
nohup python daemon_crypto.py >> cryptotrader.log 2>&1 &
echo $! > cryptotrader.pid
kill $(cat cryptotrader.pid)
```

---

## Backtesting (`backtest.py`)

Walk-forward simulation of the strategy against historical data.
Each pair's backtest uses the parameters from its own indicator file,
so changes there are reflected immediately in the next run.

```bash
# Scalp mode — 60 days, 5m entry bars (single pair)
python backtest.py --pair eurusd

# Long mode — 730 days, 1h entry bars (larger sample)
python backtest.py --pair eurusd --long

# BTCUSD
python backtest.py --pair btcusd

# All pairs, scalp mode — prints a combined summary table
python backtest.py --all

# All pairs, long mode
python backtest.py --all --long

# Include position sizing (requires account size and risk %)
python backtest.py --pair eurusd --account 10000 --risk 1.0
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
- The 1h bias may be FLAT — all three 1h gates must align simultaneously.
- The 4h EMA(22) gate may be blocking — the 4h direction must agree with the 1h direction.
- The session filter blocks FX entries outside 07:00–16:00 UTC.
- ATR may be below the floor (2-pip / $50 BTC minimum — market too quiet).

**Emails not arriving**
- Run with `--dry-run` first to confirm signals are firing.
- Check the log for `SMTP authentication failed` or `Failed to send email`.
- Gmail users: ensure you are using an App Password, not your account password.
- Check your spam folder.

**Binance orders not placed (crypto daemon)**
- Confirm `BINANCE_API_KEY` and `BINANCE_API_SECRET` are set in `.env`.
- Check `BINANCE_TESTNET` — if `true`, orders go to the testnet (paper trading only).
- Run `--dry-run` to verify signal logic without touching Binance.

**`RuntimeError: No data returned`**
- Yahoo Finance occasionally rate-limits or returns empty responses.
  The daemon logs a warning and retries on the next poll; the interactive
  script exits with the error message.  Wait a minute and try again.

**`IndexError` on startup**
- The cache needs at least 30 bars before indicators are computed.
  This can happen if you start the daemon outside market hours when
  yfinance returns very few recent bars.  Try again during market hours.
