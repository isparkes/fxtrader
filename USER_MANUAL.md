# FX Scalper — User Manual

## Overview

This tool generates intraday scalping signals for four major FX pairs (EURUSD,
GBPUSD, USDJPY, AUDUSD) using a two-timeframe approach: the **1h chart** sets
the directional bias, and the **5m chart** finds precise entry timing within
that bias. It runs as a long-running daemon that sends email alerts and manages
positions through the OANDA REST API. Discretionary trades opened manually can
also be registered for automated trailing-stop management.

**v2 architecture (2026-05-22):**

| Module | Role |
|--------|------|
| `daemon.py` | Unified daemon — automated signals + discretionary trade management |
| `backtest.py` | Walk-forward simulation against OANDA parquet data |
| `tradelib.py` | Single source of truth: Position dataclass, trailing-stop logic, unit sizing |
| `datalib.py` | Persistent OANDA parquet store (M1/H1/D per pair) |
| `oanda.py` | OANDA REST client with paginated multi-page fetching |
| `indicator_<pair>.py` | Per-pair parameters and indicator computation |

---

## Quick-start

```bash
# 1. Create and activate the virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\Activate.ps1        # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure OANDA and email credentials
cp .env.example .env
# Edit .env — required fields listed in the OANDA Integration section below

# 4. Seed the OANDA data store (one-time setup, ~2 min per pair)
python datalib.py seed

# 5. Verify the data
python datalib.py status
```

---

## Data Library (`datalib.py`)

All historical data is sourced exclusively from OANDA and stored locally as
Parquet files in `data/oanda/`. Yahoo Finance is not used anywhere in the
project.

### Default storage

| Granularity | Lookback | ~Bars/pair | Purpose |
|-------------|----------|------------|---------|
| M1 | 90 days | ~92,000 | Entry simulation (M5 resampled from M1 at runtime) |
| H1 | 730 days | ~12,400 | Bias indicators, MACD gate |
| D | 1000 days | ~700 | Daily ADX gate |

M5 is never stored. It is always resampled from M1 at runtime via `datalib.resample()`.

### CLI

```bash
# First-time setup — seed all pairs (run once)
python datalib.py seed

# Seed a single pair
python datalib.py seed eurusd

# Incremental update — fetch only new bars since last stored timestamp
python datalib.py update

# Update a single pair
python datalib.py update eurusd

# Show stored date ranges and file sizes
python datalib.py status

# Verify row counts and test resample for a pair
python datalib.py verify eurusd
```

The daemon calls `datalib.update(pair)` at the start of each tick automatically,
so the store stays current without manual intervention during normal operation.

---

## Interactive Mode (per-pair indicator scripts)

Each active pair has its own indicator file. Run it directly to get an
immediate signal check against the current OANDA candles.

```bash
python indicator_eurusd.py
python indicator_gbpusd.py
python indicator_usdjpy.py
python indicator_audusd.py

# Suppress FLAT (no-signal) output
python indicator_eurusd.py --quiet
```

### Active pairs

| Script | Pair |
|--------|------|
| `indicator_eurusd.py` | Euro / US Dollar |
| `indicator_gbpusd.py` | British Pound / US Dollar |
| `indicator_usdjpy.py` | US Dollar / Japanese Yen |
| `indicator_audusd.py` | Australian Dollar / US Dollar |

Each file contains its own tunable parameter block at the top. Changing values
there affects only that pair — `daemon.py` and `backtest.py` dispatch to the
correct file automatically via `PAIR_INDICATORS`.

### Output

| Field | Meaning |
|-------|---------|
| Direction | **BUY**, **SELL**, or **FLAT** (no signal) |
| Entry | Suggested entry price |
| Stop Loss | Hard stop — ATR × 0.4, floored at `HA_SL_MIN_PIPS` |
| Take Profit | Wide ceiling — ATR × 3.0 from entry |
| R:R | Risk-to-reward ratio |
| ATR(14) 1h | 1h Average True Range — volatility measure |
| 1h Trend | Price position relative to EMA(50) |
| 1h RSI | 1h RSI(14) — momentum gate |
| MACD Hist | 1h MACD histogram — building momentum gate |
| Basis | Which pattern fired and on which bar |

---

## Signal Logic

### Trend gates (1h — all three must pass)

1. Price above EMA(50) for BUY; below for SELL
2. MACD histogram positive **and increasing** for BUY; negative **and decreasing** for SELL (building MACD gate)
3. RSI(14) above 50 for BUY; below 50 for SELL

### 4h agreement gate

4h close must be above/below the **4h EMA(22)** in the same direction as the
1h bias. Trades where 1h and 4h conflict are suppressed as FLAT.

### Daily ADX gate

Daily ADX(14) must exceed a per-pair threshold before entries are allowed:

| Pair | ADX threshold |
|------|--------------|
| EURUSD | 17 |
| GBPUSD | 25 |
| USDJPY | 0 (exempt) |
| AUDUSD | 18 |

### Entry patterns (5m — first match wins)

| Pattern | Description |
|---------|-------------|
| **A** | EMA(8) crosses EMA(21) in trend direction; confirmed by RSI(7) and Stochastic |
| **C** | 5m MACD histogram flips sign in trend direction while price is on the right side of EMA(21) |
| **D** | 3 same-colour Heikin-Ashi candles → 1 opposing pullback → resumption; stop anchored to pullback extreme |
| **E** *(USDJPY only)* | Supertrend(10/3.0) flip in trend direction |

### Risk management

- **Stop loss (A/C/E):** ATR × 0.4, floored at `HA_SL_MIN_PIPS` (10 pips for EURUSD/GBPUSD/AUDUSD; 7 pips for USDJPY)
- **Stop loss (D):** pullback candle extreme ± buffer, clamped to `HA_SL_MIN_PIPS`–`HA_SL_MAX_PIPS`
- **Take profit:** ATR × 3.0 (wide ceiling)
- **Trailing stop (three-phase):**
  1. *Breakeven:* stop moves to entry once price reaches a fraction of the TP distance (70% for EURUSD; 80% for all others)
  2. *ATR trail:* stop tracks price at ATR × SL_MULT distance
  3. *TP extension:* if Heikin-Ashi momentum agrees, TP doubles (2× original), stop locks to 90% of TP, trail tightens to 50%
- **Cooldown:** no new entry for **60 minutes** after a loss
- **Spread guard:** live spread is queried before every entry; if it exceeds 2× the pair's standard spread the signal is skipped and logged
- **Trading day gate:** FX entries are blocked on Friday, Saturday, and Sunday
- **Session filter:** entries only fire during **07:00–16:00 UTC** (London / New York overlap)
- **Weekend auto-close:** at 20:00 UTC on Friday the daemon closes all open FX positions ahead of weekend spread blowout

---

## FX Daemon (`daemon.py`)

Unified daemon that manages both automated signals and discretionary trades.
Monitors EURUSD, GBPUSD, USDJPY, and AUDUSD indefinitely with
bar-synchronised polling (wakes at each 5-minute bar boundary + 5 seconds when
no positions are open; polls every 15 seconds when positions are open).

### Starting the daemon

```bash
# Paper mode — all 4 pairs, no orders placed
python daemon.py

# Watch specific pairs only
python daemon.py --pair eurusd usdjpy

# Dry-run — log events only, no emails or broker calls
python daemon.py --dry-run

# Live mode — place real OANDA orders
python daemon.py --live

# Live mode with occult stops (SL/TP not sent to broker)
python daemon.py --live --occult-stops

# Debug logging
python daemon.py --log-level DEBUG
```

`FX_PAIRS=eurusd,usdjpy,audusd` in `.env` selects pairs without a CLI flag.

### Running in the background (macOS / Linux)

```bash
nohup python daemon.py >> fxtrader.log 2>&1 &
echo $! > fxtrader.pid

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
    <string>/Users/YOUR_NAME/fxtrader/.venv/bin/python</string>
    <string>/Users/YOUR_NAME/fxtrader/daemon.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOUR_NAME/fxtrader</string>
  <key>StandardOutPath</key>
  <string>/Users/YOUR_NAME/fxtrader/fxtrader.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOUR_NAME/fxtrader/fxtrader.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.fxtrader.daemon.plist

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.fxtrader.daemon.plist
```

### Real-time control console

The daemon listens for control commands on TCP port **9876** (default).

```
telnet localhost 9876
```

```
FX Trader  |  help=commands  quit=disconnect

> status
=== FX Trader Daemon Status ===
Entries : Active  |  Exits : Active

  EURUSD  [no position]
  GBPUSD  BUY  entry=1.27350  SL=1.27100  TP=1.27800  BE=pending
  USDJPY  [cooldown until 14:30 UTC]
  AUDUSD  [no position]

Discretionary (1):
  id=12345  GBPUSD  BUY  entry=1.27200  SL=1.27000  TP=1.27800  [managed]

> register 12345
Register queued for trade 12345.

> stoploss 12345 1.27050
SL update queued for trade 12345.

> trades
=== Open OANDA Trades (2) ===
  id=12344  GBP_USD  BUY  entry=1.27350  SL=1.27100  TP=1.27800  [managed]
  id=12345  GBP_USD  BUY  entry=1.27200  SL=1.27050  TP=1.27800  [managed]

> close
Close queued.

> quit
Bye.
```

**Commands:**

| Command | Effect |
|---------|--------|
| `status` | Show entry/exit pause state, open positions, and cooldown state |
| `pause` | Suspend both new entries and automatic exits |
| `resume` | Re-enable both entries and exits |
| `pause_entry` | Stop entering new trades; open positions continue to be managed |
| `resume_entry` | Re-enable new trade entries |
| `pause_exit` | Suppress automatic position closes (SL/TP hits are logged but not acted on) |
| `resume_exit` | Re-enable automatic position exits |
| `register <id>` | Register an open OANDA trade ID for daemon trailing-stop management |
| `stoploss <id> <sl>` | Override the stop-loss price for a discretionary trade |
| `takeprofit <id> <tp>` | Override the take-profit price for a discretionary trade |
| `deregister <id>` | Stop managing a trade (leaves position open, removes daemon tracking) |
| `close [<id>]` | Close one position by trade ID, or all positions if no ID given |
| `be` | Move every open stop-loss to breakeven immediately |
| `materialise_sl` | Place real broker SL orders for every occult-stops position |
| `materialise_tp` | Place real broker TP orders for every occult-stops position |
| `trades` | List all open OANDA trades with SL/TP, flagged if daemon-managed |
| `help` | List available commands |
| `quit` | Disconnect |

`be`, `close`, `materialise_sl`, and `materialise_tp` wake the daemon
immediately rather than waiting for the next poll.

The port can be changed with `FX_CTRL_PORT=<port>` in `.env`.

For scripted use there is also `fxctl.py`:
```bash
python fxctl.py status
python fxctl.py pause_entry
python fxctl.py materialise_sl
python fxctl.py --host 192.168.1.10 status   # remote host
```

### Discretionary trade management

Any position opened manually on OANDA can be handed to the daemon for
automated trailing-stop management:

1. Open the trade manually on OANDA (web platform or app)
2. Note the trade ID (visible in the OANDA interface or via `trades` command)
3. Register it: `register <id>`

The daemon will fetch the current price, compute ATR from recent H1 bars, and
apply the same three-phase trailing-stop logic used for automated trades. Use
`stoploss` and `takeprofit` to override the computed levels if needed.

To stop managing a trade without closing it, use `deregister <id>`.

### Email alerts

| Event | Sent when … |
|-------|-------------|
| **OPEN** | A BUY or SELL signal fires on a watched pair |
| **BE** | Price reaches the breakeven trigger — stop moved to entry |
| **CLOSE** | Stop loss or take profit is hit |
| **MANUAL CLOSE** | `close` command sent via control console |
| **WEEKEND CLOSE** | Friday ≥ 20:00 UTC — daemon closes positions ahead of weekend spread blowout |
| **Daily Summary** | 08:00 UTC and 20:00 UTC — open positions, month-to-date pips, account balance, and open trade P&L |

### Trade log and restart persistence

The daemon writes every OPEN, BE, and CLOSE event as a JSON line to
`fx_trades.jsonl` in the working directory. On startup it replays this file
to restore open positions and the month-to-date pip total, so you can stop and
restart without losing trade state.

Mount `fx_trades.jsonl` as a Docker volume to ensure persistence across
container restarts.

### Occult stops

By default, every OANDA market order includes attached `stopLossOnFill` and
`takeProfitOnFill` orders so the broker protects the position server-side.
With occult stops enabled those orders are omitted: the daemon itself monitors
price and closes the trade when either level is hit.

**Why use this:** broker-visible stop orders can be targeted by market makers
("stop hunting"). Keeping stops invisible removes that information from the
order book.

| | Broker-side SL/TP (default) | Occult stops |
|---|---|---|
| Protection if daemon crashes | Yes — broker closes automatically | No — position stays open |
| Stop-hunt exposure | Yes — levels visible on broker | No — known only to daemon |
| Breakeven move | Daemon sends modify request to OANDA | Tracked in memory only |

Use `materialise_sl` / `materialise_tp` to promote occult stops to real broker
orders at any time (e.g. before a network outage).

**Enable:**
```
FX_OCCULT_STOPS=true   # .env
python daemon.py --live --occult-stops   # CLI flag
```

---

## OANDA Integration

The daemon uses OANDA for: live position sizing (account NAV), spread checking
before every entry, order execution in live mode, and all historical candle
data. Add the following to `.env`:

```
OANDA_API_KEY=...              # personal access token from the OANDA hub
OANDA_ACCOUNT_ID=...           # numeric account ID
OANDA_ENV=practice             # "practice" (demo) or "live"
OANDA_RISK_PCT=1               # % of NAV to risk per trade (1 = 1%, 0.8 = 0.8%)
FX_LIVE=false                  # true = place live OANDA market orders
FX_OCCULT_STOPS=false          # true = enable occult stops
```

---

## Email Setup

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=xxxx-xxxx-xxxx-xxxx   # Gmail App Password
MAIL_TO=you@gmail.com
```

> **Gmail users:** Generate an *App Password* at
> https://myaccount.google.com/apppasswords — do not use your main password.

To send to multiple recipients, comma-separate `MAIL_TO`:
```
MAIL_TO=trader@example.com,alerts@example.com
```

---

## Backtesting (`backtest.py`)

Walk-forward simulation against the OANDA parquet store. Uses M1 within-bar
simulation for accurate SL/TP ordering (5 M1 bars stepped for each M5 window).
Each pair's parameters come from its indicator file.

### First run

```bash
# Seed data and run backtest in one step
python backtest.py --pair eurusd --seed
```

`--seed` calls `datalib.update_all()` before running.

### Common usage

```bash
# Single pair, scalp mode (5m entry bars, 90d M1 data)
python backtest.py --pair eurusd

# Long mode (1h entry bars, 730d H1 data)
python backtest.py --pair eurusd --long

# All four active pairs — prints a combined summary table
python backtest.py --all

# All pairs, long mode
python backtest.py --all --long

# Skip data update (use stored data as-is)
python backtest.py --all --no-update

# Include position sizing output
python backtest.py --pair eurusd --account 10000 --risk 1.0

# Evaluate EURJPY (candidate pair — not in active trading)
python backtest.py --pair eurjpy
```

Results are printed as a table and saved to `{pair}_backtest_trades.csv`.

---

## Docker

### Build and push

```bash
bash build-push.sh
```

Builds `Dockerfile.fx` for `linux/amd64`, saves a tar, SCPs to the deploy
host, and loads it there. Credentials are read from `.env.deploy`.

### Running with Docker Compose

```bash
docker compose up -d
```

The compose file mounts three volumes:

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `/data/fxtrader/fx_trades.jsonl` | `/app/fx_trades.jsonl` | Trade log — persistent state |
| `/data/fxtrader/fxtrader.log` | `/app/fxtrader.log` | Daemon log |
| `/data/fxtrader/oanda` | `/app/data/oanda` | OANDA parquet store |

Seed the parquet store on the host before first run:
```bash
# On the deploy host, with credentials in .env
python datalib.py seed
```

Or mount an already-seeded store directory from another machine.

Override the default command in `docker-compose.yml` to pass flags:
```yaml
command: ["--live"]
command: ["--live", "--occult-stops"]
command: ["--pair", "eurusd", "usdjpy"]
```

---

## Troubleshooting

**No signal generated**
- The 1h bias may be FLAT — all three 1h gates must align simultaneously.
- The 4h EMA(22) gate may be blocking — 4h direction must agree with 1h.
- The daily ADX gate may be blocking — check `python datalib.py verify <pair>` to confirm daily data is seeded.
- The trading day gate blocks FX entries on Friday, Saturday, and Sunday.
- The session filter blocks entries outside 07:00–16:00 UTC.
- The spread guard may have blocked the entry — check the log for `signal skipped — spread X.X pips exceeds threshold`.

**`FileNotFoundError: No data for EURUSD M1`**
- The parquet store has not been seeded. Run `python datalib.py seed`.

**`IndexError: index 14 is out of bounds`**
- A parquet file exists but has too few rows for indicator warmup (less than 14 bars). Delete the file and re-seed: `rm data/oanda/<pair>_D.parquet && python datalib.py seed <pair>`.

**Emails not arriving**
- Run with `--dry-run` first to confirm signals are firing.
- Check the log for `SMTP authentication failed` or `Failed to send email`.
- Gmail users: ensure you are using an App Password, not your account password.
- Check your spam folder.

**OANDA orders not placed**
- Confirm `OANDA_API_KEY`, `OANDA_ACCOUNT_ID`, and `FX_LIVE=true` are set in `.env`.
- Check `OANDA_ENV` — if `practice`, orders go to the demo account.
- Run `--dry-run` to verify signal logic without placing orders.

**Daemon does not restart after crash**
- Check `fxtrader.log` for the error.
- If a position was open when the crash occurred, use `register <id>` after restart to resume management.
