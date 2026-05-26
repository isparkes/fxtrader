# FX Trader — System Specification v2

**Date:** 2026-05-22  
**Status:** Implemented 2026-05-22; updated 2026-05-25

---

## 1. Purpose

This document specifies the redesigned FX trading system. It preserves all validated strategy insights from the v1 build while resolving four architectural deficiencies:

1. **Dual-codebase drift** — backtest and live daemon duplicate trade management logic and diverge silently.
2. **BTC removal** — BTCUSD has underperformed; crypto daemon is deprecated.
3. **Execution latency** — polling-based entry detection misses bars; occult stop exits suffer slippage.
4. **Discretionary trade integration** — manual trades should live in the same daemon as automated signals, not a separate process.

---

## 2. Active Pairs

| Pair   | Session Gate (UTC) | ADX Gate | Notes                                        |
|--------|--------------------|----------|----------------------------------------------|
| EURUSD | 07:00–16:00        | ≥ 17     | Primary pair; MACD gate added 2026-05-11     |
| USDJPY | 07:00–16:00        | exempt   | Supertrend flip pattern E active             |
| AUDUSD | 07:00–16:00        | ≥ 18     | Backtest validity suspect on Yahoo data      |
| GBPUSD | 07:00–16:00        | ≥ 25     | Weakest pair; prime candidate for retirement |

EURJPY is on the watchlist (PF 1.38/1.57) but deferred until a GBPUSD slot is freed.
GBPJPY: watch-only (high drawdown).
BTCUSD: **removed** (see §10).

**Position limit:** 3 concurrent trades maximum (30:1 leverage).

---

## 3. Strategy Logic

### 3.1 Timeframes

| Role          | Scalp Mode   | Long Mode   |
|---------------|--------------|-------------|
| Trend (bias)  | 1h bars      | 4h bars     |
| Entry timing  | 5m bars      | 1h bars     |
| Filter        | Daily bars   | Daily bars  |

### 3.2 H1 Bias — Must Pass All Three

1. **EMA50 side** — price above EMA50 for BUY; below for SELL.
2. **MACD histogram direction and momentum** — histogram positive and building (increasing) for BUY; negative and falling for SELL. Requires accelerating momentum, not fading.
3. **RSI(14) above/below 50** — secondary momentum confirmation.

### 3.3 Supplementary Gates (applied to the bias, not entry)

| Gate               | Purpose                                          |
|--------------------|--------------------------------------------------|
| 4h EMA22           | Confirms higher-timeframe trend direction.       |
| Daily ADX(14)      | Suppresses entries on directionless days.        |
| Day-of-week (DOW)  | Friday blocked (chop; configurable per pair).    |
| 60-minute cooldown | Post-loss lockout. Timer only starts on SL hits. |

### 3.4 Entry Patterns (5m)

Pre-checks before any pattern fires:

- **Session gate** — bar must fall within 07:00–16:00 UTC.
- **5m ATR floor** — 5m ATR(14) ≥ 0.0002 (2 pips). Skips entries during compression.

**Pattern A — EMA8/21 cross**  
BUY: EMA8 crosses above EMA21. SELL: EMA8 crosses below EMA21.  
Guards: RSI(7) 52–75 / 25–48; Stochastic %K above/below %D with room to run.

**Pattern C — MACD histogram flip**  
BUY: 5m MACD (6/13/4) histogram crosses zero upward; price above EMA21.  
SELL: histogram crosses zero downward; price below EMA21.  
Guards: same RSI and Stochastic conditions as Pattern A.

**Pattern D — Heikin-Ashi pullback and resumption**  
3 consecutive same-colour HA candles → 1 opposing HA pullback → entry on resumption candle.  
BUY: 3 bullish → 1 bearish pullback → bullish resumption.  
SELL: 3 bearish → 1 bullish pullback → bearish resumption.  
No RSI/Stochastic guards — the 5-bar sequence provides the quality filter.

**Pattern E — Supertrend flip (USDJPY only)**  
Entry on a flip of Supertrend(10, 3.0) confirmed on the 5m bar. PF 1.99 on USDJPY.

### 3.5 Risk Management

**Stop Loss (SL)**

| Pattern | SL Basis                                                                 |
|---------|--------------------------------------------------------------------------|
| A, C    | ATR(14) × ATR_SL_MULT (0.4 default) from entry. Hard floor per pair.   |
| D       | Pullback candle's HA extreme ± 2-pip buffer, clamped to pair floor/cap. |
| E       | ATR(14) × ATR_SL_MULT from entry (same as A, C).                        |

**Per-pair SL floors:**

| Pair             | HA_SL_MIN_PIPS |
|------------------|----------------|
| EURUSD           | 10             |
| GBPUSD           | 10             |
| AUDUSD           | 10             |
| USDJPY           | 7              |

**Take Profit (TP):** ATR(14) × 3.0 from entry. Trailing stop typically exits before TP is hit.

**Minimum R:R:** 1.5 — signals below this are suppressed.

### 3.6 Three-Phase Trailing Stop Model

This model is **the single source of truth** for both backtesting and live trading. It must live in the shared `tradelib.py` module (see §6.2).

**Phase 1 — Breakeven**  
Once price reaches `TRAIL_ACTIVATE_FRAC` (default 0.80; EURUSD 0.70) of the initial TP distance, SL moves to entry price. Risk drops to zero.

**Phase 2 — Active Trail**  
After Phase 1 fires, SL ratchets `ATR × ATR_SL_MULT` behind the running best price. Winners run until the trail is hit.

**Phase 3 — TP Extension**  
When the original TP is first hit, the trade is extended unconditionally:
- SL locks at 90% of the original TP distance from entry.
- TP doubles to 2× the original TP distance.
- Trail tightens to `ATR × ATR_SL_MULT × 0.5`.

**Per-pair `TRAIL_ACTIVATE_FRAC` overrides:**

| Pair   | TRAIL_ACTIVATE_FRAC |
|--------|---------------------|
| EURUSD | 0.70                |
| Others | 0.80 (default)      |

### 3.7 Position Sizing

Risk per trade: `OANDA_RISK_PCT`% of account NAV (default 1%).  
Units = `(NAV × risk_pct / 100) / (risk_pips × pip_usd)`  
For JPY pairs, pip_usd = pip_size / live_USDJPY_rate.

### 3.8 Spread Guard

Entry is rejected when the live Oanda spread exceeds 2× the standard spread for the pair.

| Pair   | Standard Spread (pips) |
|--------|------------------------|
| EURUSD | 1.0                    |
| GBPUSD | 1.5                    |
| USDJPY | 2.0                    |
| AUDUSD | 1.5                    |

If the OANDA price check fails (network error), the guard **fails closed** — the entry is blocked and the rejection is logged.

### 3.9 Weekend Handling

All open positions are closed at 20:00 UTC Friday to avoid weekend spread blow-out.

---

## 4. Problems with the v1 Architecture

### 4.1 Dual-Codebase Drift (Critical)

`daemon_fx.py`, `trade_manager.py`, and `backtest.py` each contain their own copies of:
- `Position` dataclass
- `check_position_events()` (three-phase trailing stop model)
- Trailing stop constants (`TRAIL_ACTIVATE_FRAC`, `ATR_SL_MULT`)
- Data helpers (`_fetch_oanda`, `_merge_into_cache`, etc.)

These copies are already diverging. A parameter change in one file does not propagate to the others. Backtests validating parameters that are then applied incorrectly in the daemon produce false confidence.

### 4.2 Execution Latency — Missed Entries

The daemon polls pairs every 60 seconds in "hunt" mode (directional bias, no position). 5m bars close on round-minute boundaries (:00, :05, :10...). A signal fires on the _closed_ bar, but the daemon may not sample it for up to 60 seconds. In a fast-moving 5m bar this is a full bar of slippage, or missing the entry entirely.

Root cause: polling is not synchronised to bar boundaries.

### 4.3 Execution Latency — Occult Stop Slippage

In occult-stop mode the daemon detects SL/TP hits by checking the latest 5m bar's high/low. If the bar has already closed when the poll fires, the daemon is using stale data. Worse, if price has gapped through the level, the daemon closes at a worse price than the original stop. The polling interval (up to 60s) means exits can lag by a full 5m bar.

### 4.4 Yahoo Finance Data — Backtest Validity

Yahoo Finance provides synthetic FX data (zero volume, fixed-increment prices). Daily ADX values diverge from OANDA by 2–6 pts per pair. Root cause of 28–0% signal match rates observed in May 2026 analysis. AUDUSD backtest PF 2.45 is suspect — all signals in the test period were phantom entries in a period OANDA's ADX correctly blocked.

### 4.5 Separate Processes for Automated vs Discretionary Trades

`daemon_fx.py` manages automated signals. `trade_manager.py` manages manually-entered trades. They run as separate processes on separate control ports (9876 / 9877), have separate log files, and provide separate status views. There is no single view of overall exposure. Both must be running simultaneously. The operator must choose which port to connect to.

### 4.6 BTC / Crypto Daemon

`daemon_crypto.py` was added in April 2026. Backtest showed PF 1.72/2.12 but live performance has underperformed expectations. Crypto adds operational complexity (separate Docker container, separate log, different pip_value semantics, no session gate). The strategy is fundamentally an FX session-based scalper and does not translate cleanly to a 24/7 crypto instrument.

---

## 5. Design Goals for v2

1. **Single trade management library** — one canonical implementation of `Position`, `check_position_events`, and all trailing stop logic. Both backtest and daemon import it; parameter drift is impossible.
2. **OANDA-only data** — eliminate Yahoo Finance from both live trading and backtesting. All historical data comes from `oanda.get_candles()`.
3. **Bar-synchronised polling** — entry detection polls trigger within seconds of each 5m bar close, not on an arbitrary timer.
4. **Broker-native stops by default** — real SL/TP orders on Oanda; occult mode is an opt-in exception, not the default. Eliminates daemon-managed exit slippage in normal operation.
5. **Unified daemon** — one process, one control port, one log file, one status view for both automated-signal trades and discretionary trades.
6. **Crypto removed** — `daemon_crypto.py` and `indicator_btcusd.py` deprecated and removed from active paths.

---

## 6. v2 Architecture

### 6.1 Module Map

```
fxtrader/
├── datalib.py             ← NEW: persistent OANDA data library (M1/H1/D parquet)
├── tradelib.py            ← NEW: shared Position, check_position_events, sizing
├── indicator_eurusd.py    ← unchanged (strategy parameters only)
├── indicator_gbpusd.py    ← unchanged
├── indicator_usdjpy.py    ← unchanged
├── indicator_audusd.py    ← unchanged
├── oanda.py               ← updated: add get_candles_paginated()
├── daemon.py              ← REWRITTEN: merged daemon_fx + trade_manager
├── backtest.py            ← REWRITTEN: imports tradelib + datalib; no Yahoo Finance
├── tradelog.py            ← unchanged (event log for automated trades)
├── mailer.py              ← unchanged
├── logsetup.py            ← unchanged
├── fxctl.py               ← updated (single port default)
├── data/
│   └── oanda/             ← parquet files written by datalib.py
└── DEPRECATED/
    ├── daemon_fx.py
    ├── daemon_crypto.py
    ├── trade_manager.py
    └── indicator_btcusd.py
```

### 6.2 `tradelib.py` — Shared Trade Management Library

This module is the **single source of truth** for all trade lifecycle logic. Neither `daemon.py` nor `backtest.py` shall reimplement it.

**Contents:**

```python
# Position dataclass — all fields used by both backtest and daemon
@dataclass
class Position:
    pair, symbol, direction, entry_price, stop_loss, take_profit
    atr, risk_pips, reward_pips, rr_ratio
    opened_at, basis
    be_activated, trade_id, occult_stops
    sl_materialised, tp_materialised
    signal_price, tp_extended, original_tp, best_price
    trade_type: str  # "automated" | "discretionary"

# Trailing stop model — canonical implementation
def check_position_events(pos: Position, bar: pd.Series, ind) -> list[tuple[str, float]]

# Position sizing
def calc_units(pair: str, risk_pips: float, indicators) -> int

# Pip value resolution
def pip_value(pair: str) -> float

# Signal dataclass (used as input to position construction)
@dataclass
class Signal:
    direction, entry_price, stop_loss, take_profit
    atr, risk_pips, reward_pips, rr_ratio
    timestamp, entry_basis, bar_time
```

### 6.3 `daemon.py` — Unified Daemon

One process handles both automated-signal trades and discretionary trades.

**Trade types:**

| Type           | How it enters                                  | Management                        |
|----------------|------------------------------------------------|-----------------------------------|
| `automated`    | Signal fires from indicator; daemon places order | Full lifecycle in daemon          |
| `discretionary`| Operator enters on Oanda; registers via CLI    | Same three-phase model from entry |

**State model:**

```
PairState
  cache_h1, cache_5m, cache_1d     # OANDA OLHCV caches
  automated_position: Optional[Position]   # one per pair
  cooldown_until: Optional[datetime]
  last_signal_bar: Optional[str]
  last_bias: str

# Discretionary trades keyed by Oanda trade_id, any pair
discretionary: dict[str, Position]
```

Both collections are iterated in every tick. The control socket provides a unified view.

**Control socket (single port, default 9876):**

```
status              — all automated + discretionary positions, cooldowns
trades              — all open Oanda trades (with managed tag)
register <id>       — take a manual Oanda trade under management
  --sl <price>      — override SL (default: ATR-derived)
  --tp <price>      — override TP (default: ATR-derived)
stoploss  <id> <sl> — update SL for any managed trade
takeprofit <id> <tp>— update TP for any managed trade
deregister <id>     — stop managing a discretionary trade (no close)
be [<id>]           — move SL to breakeven: specific trade or all
close [<id>]        — close specific trade or all managed trades
pause_entry / resume_entry
pause_exit  / resume_exit
materialise_sl / materialise_tp   — occult-stop override
help / quit
```

### 6.4 Bar-Synchronised Polling

**Entry detection (no open automated position, directional bias):**

The main loop calculates the time until the next 5m bar closes and sleeps until ~5 seconds after that boundary. This ensures entries are evaluated within one polling cycle of each bar close, not with up to 60s lag.

```python
def _sleep_until_next_bar_close(buffer_secs: int = 5) -> None:
    now = datetime.now(timezone.utc)
    secs_into_bar = (now.minute % 5) * 60 + now.second
    remaining = (5 * 60 - secs_into_bar) + buffer_secs
    time.sleep(remaining)
```

When no pair has a directional bias and no positions are open, the daemon uses the normal 300s (5-minute) interval to avoid unnecessary API calls.

**Exit monitoring (position open):**

When one or more positions are open, the daemon polls every 15 seconds regardless of bar boundaries. This is the key fix for occult-stop slippage. At 15s intervals the maximum exit lag is 15 seconds, not 60.

Recommended default: **use real broker SL/TP orders**. Occult mode remains available via `--occult-stops` flag for protection against specific stop-hunting conditions, but it should not be the daily default. With broker orders, the broker closes the trade at the specified price; the daemon simply reconciles the closed state on the next poll.

### 6.5 `backtest.py` — Data Library Integration

`backtest.py` loads all historical data from `datalib` (see §6.9). Yahoo Finance is fully removed. No direct OANDA API calls in `backtest.py`; all data access is mediated by `datalib`.

**Data loading:**

```python
import datalib
from tradelib import Position, check_position_events, calc_units

# datalib.update() fetches any bars newer than the last stored timestamp.
# This is a no-op if the library is already current.
datalib.update(pair)   # updates M1, H1, D for the pair

# Load the desired window
df_m1 = datalib.load(pair, "M1", start=start_date, end=end_date)
df_h1 = datalib.load(pair, "H1", start=start_date, end=end_date)
df_1d = datalib.load(pair, "D",  start=start_date, end=end_date)

# Derive M5 by resampling M1 — single source of truth for bar data
df_5m = datalib.resample(df_m1, "M5")
```

No trailing stop logic in `backtest.py` itself — only `tradelib` is used.

**Within-bar M1 simulation:**

The backtest entry loop operates on M5 bars (resampled from M1). For each open position, instead of evaluating the trailing stop model against the M5 bar alone, it steps through the underlying M1 bars to determine the exact chronological order SL and TP are touched. This eliminates the ambiguity of the current approach, where the same M5 bar can show both SL and TP within its high-low range.

```python
# For each 5m bar where a position is open:
m1_slice = df_m1[bar_start : bar_end]   # M1 bars within this 5m window
for _, m1_bar in m1_slice.iterrows():
    events = check_position_events(pos, m1_bar, ind)
    if any(e[0].startswith("close") for e in events):
        break   # SL or TP hit — use this event, discard remainder of 5m bar
```

**Realistic spread simulation:**

Apply the pair's `STANDARD_SPREAD` (from the indicator file) to the fill price, consistent with the daemon. No separate spread constant in `backtest.py`.

### 6.6 Indicator Files

The per-pair indicator files (`indicator_eurusd.py`, etc.) remain unchanged in structure. They own all strategy parameters. The daemon and backtest dispatch via `PAIR_INDICATORS[pair]`.

Required constants per indicator file:

```python
ATR_SL_MULT           # SL multiplier
ATR_TP_MULT           # TP multiplier  
H4_EMA_PERIOD         # H4 EMA gate period (default 22)
TRAIL_ACTIVATE_FRAC   # BE trigger fraction (default 0.80)
DAILY_ADX_MIN         # Daily ADX gate threshold (0 = exempt)
BLOCKED_DAYS          # set of weekday ints (default {4} = Friday)
HA_SL_MIN_PIPS        # floor on SL distance
HA_SL_MAX_PIPS        # cap on SL distance (slippage protection)
STANDARD_SPREAD       # pips — used in spread guard

# Functions
compute_h1_indicators(df) -> df
compute_m5_indicators(df) -> df
compute_daily_adx(df)     -> df
assess_h1_bias(df_h1, df_4h, df_1d) -> dict
find_m5_entry(df_5m, direction) -> Optional[dict]
build_signal(h1_bias, entry, symbol) -> Signal
pip_value(symbol) -> float
```

### 6.7 Discretionary Trade Registration

When the operator registers a trade:

1. Daemon fetches the trade from Oanda (`get_open_trades()`), reads instrument/direction/entry.
2. Computes ATR from live 1h data.
3. Constructs SL and TP from ATR unless `--sl` / `--tp` are provided.
4. If price has already moved past the BE activation threshold, pre-activates Phase 1 immediately.
5. In live + non-occult mode, places broker SL/TP orders immediately.
6. Trade is tagged `trade_type = "discretionary"` and added to the `discretionary` dict.
7. Registration is logged to the single trade log (`fx_trades.jsonl`).

Discretionary trades are subject to the same Phase 1–3 trailing stop model as automated trades. They are NOT subject to the 60-minute cooldown (cooldown is per-pair and only triggered by automated SL closes).

### 6.8 Trade Log

A single log file `fx_trades.jsonl` captures all events for both automated and discretionary trades. The `trade_type` field distinguishes the source.

---

### 6.9 `datalib.py` — Persistent OANDA Data Library

`datalib.py` owns all historical market data. It is a standalone module with no dependency on `tradelib`, `daemon`, or `backtest`. Both `backtest.py` and `daemon.py` call it to load market data.

#### Storage Layout

```
data/
└── oanda/
    ├── eurusd_M1.parquet      # 1-minute bars — primary resolution
    ├── eurusd_H1.parquet      # 1-hour bars — bias indicators
    ├── eurusd_D.parquet       # daily bars — ADX gate
    ├── gbpusd_M1.parquet
    ├── gbpusd_H1.parquet
    ├── gbpusd_D.parquet
    ├── usdjpy_M1.parquet
    ├── usdjpy_H1.parquet
    ├── usdjpy_D.parquet
    ├── audusd_M1.parquet
    ├── audusd_H1.parquet
    └── audusd_D.parquet
```

Format: **Parquet with Snappy compression**. Columnar storage gives fast date-range reads with minimal I/O. One file per pair per granularity — simple addressing, no partitioning needed.

Schema (all files):

| Column   | Type    | Notes                          |
|----------|---------|--------------------------------|
| (index)  | DatetimeIndex UTC | closed-bar timestamp  |
| open     | float64 |                                |
| high     | float64 |                                |
| low      | float64 |                                |
| close    | float64 |                                |
| volume   | int64   | OANDA tick volume              |

M5 is **never stored**. It is always derived at runtime: `datalib.resample(df_m1, "M5")`.

#### Default Lookback (initial seed)

| Granularity | Lookback | Rationale                                            |
|-------------|----------|------------------------------------------------------|
| M1          | 90 days  | Entry simulation; more is available but ~90k bars is sufficient |
| H1          | 730 days | 2 years for indicator warmup and regime variety      |
| D           | 1000 days| ~3 years for ADX regime context                      |

These are the defaults. The `seed` command (see CLI below) accepts `--days` overrides.

#### OANDA Pagination

`oanda.get_candles()` returns at most 5000 candles per call. `datalib` handles pagination transparently:

```python
# oanda.py — new function
def get_candles_paginated(
    pair: str,
    granularity: str,        # "M1", "H1", "D", etc.
    from_time: datetime,
    to_time: datetime | None = None,  # defaults to now
) -> pd.DataFrame:
    """
    Repeatedly call get_candles() stepping forward by 5000-candle windows
    until to_time is reached. Returns a single UTC-indexed DataFrame.
    """
```

M1 initial seed for one pair (90 days):  
`90 days × ~1440 bars/day × (5/7 trading fraction) ≈ 92 000 bars → ~19 requests`  
4 pairs: ~76 requests — a one-time cost, completes in under a minute.

Subsequent runs fetch only the delta since the last stored timestamp: typically a few candles per incremental call.

#### `datalib.py` Public API

```python
DATA_DIR = Path("data/oanda")

GRANULARITIES = ("M1", "H1", "D")

DEFAULT_LOOKBACK: dict[str, int] = {
    "M1": 90,
    "H1": 730,
    "D":  1000,
}

def update(pair: str, granularity: str | None = None) -> dict[str, int]:
    """
    Fetch new bars from OANDA and append to the parquet store.
    If granularity is None, updates all three granularities.
    Returns {granularity: new_bars_added}.

    If the parquet file does not exist, performs an initial seed using
    DEFAULT_LOOKBACK for that granularity.
    """

def load(
    pair: str,
    granularity: str,
    start: datetime | None = None,
    end:   datetime | None = None,
) -> pd.DataFrame:
    """
    Load bars from the parquet store for a date range.
    start/end default to the full stored range.
    Raises FileNotFoundError with a helpful message if the pair/granularity
    has not been seeded yet.
    """

def resample(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """
    Resample a DataFrame (typically M1) to a coarser granularity.
    target: "M5", "M15", "H1", "H4", "D"
    Uses standard OHLCV aggregation: open=first, high=max, low=min,
    close=last, volume=sum. Drops incomplete boundary bars.
    """

def status() -> dict[str, dict[str, dict]]:
    """
    Return a summary of stored data per pair/granularity.
    {pair: {granularity: {first: datetime, last: datetime, bars: int}}}
    Printed as a table by the CLI.
    """
```

#### CLI Usage

`datalib.py` is also a standalone script for manual data management:

```
# Show what is stored
python datalib.py status

# Incremental update: fetch all new bars since last stored timestamp
python datalib.py update                 # all pairs, all granularities
python datalib.py update eurusd          # all granularities for one pair
python datalib.py update eurusd M1       # specific pair + granularity

# Initial full seed (only needed once per pair, or to extend history)
python datalib.py seed                   # all pairs, default lookbacks
python datalib.py seed eurusd --days 365 # one pair, override lookback

# Verify: resample and print row counts at each granularity
python datalib.py verify eurusd
```

`update` is idempotent — running it repeatedly does not create duplicate rows. It is safe to call at the start of every backtest run.

#### Daemon Usage

The daemon does **not** use `datalib` for its in-memory cache during live trading. The daemon maintains its own rolling in-memory cache (refreshed incrementally from OANDA on each poll). `datalib` is used:
- On startup to warm the H1/D caches quickly without multiple API round-trips.
- Not at all during the main polling loop (the live daemon always fetches fresh bars from OANDA directly to avoid stale data issues).

This keeps the concerns separate: `datalib` is a historical archive optimised for analytics and backtesting; the daemon's in-memory cache is optimised for low-latency live polling.

Event schema:

```json
{"event": "open|register|be|extend_tp|close|deregister",
 "ts": "...", "trade_id": "...", "pair": "...", "trade_type": "automated|discretionary",
 "direction": "...", "entry": ..., "sl": ..., "tp": ..., ...}
```

`tradelog.py` is updated to handle both types. `trade_manager.jsonl` is deprecated.

---

## 7. Execution Mode Reference

| Mode            | Entry orders | SL/TP placement     | Exit detection          |
|-----------------|-------------|----------------------|-------------------------|
| Paper           | none        | none                 | daemon (15s poll)       |
| Live (default)  | market      | broker orders        | broker (daemon reconciles) |
| Live + occult   | market      | none (daemon-managed)| daemon (15s poll)       |

**Recommendation:** use live (broker orders) as the default. Occult mode is appropriate only when there is specific evidence of stop-hunting on a pair.

---

## 8. Configuration Reference

**Environment variables (`.env`):**

```
OANDA_ACCOUNT_ID     required
OANDA_API_KEY        required
OANDA_ENV            practice | live
OANDA_RISK_PCT       1.0        # % of NAV risked per trade
FX_LIVE              false      # true = place orders
FX_DRY_RUN           false      # true = no emails, no orders
FX_OCCULT_STOPS      false      # true = no broker SL/TP
FX_PAIRS             eurusd,usdjpy,audusd,gbpusd
FX_CTRL_PORT         9876
DATALIB_DIR          data/oanda # override default parquet storage path
LOG_LEVEL            INFO
DRAWDOWN_HALT_PCT    3.0        # halt entries when session loss % exceeds this value
```

`FX_DATA_SOURCE` is removed. Data source is always OANDA. `yfinance` is not installed.

---

## 9. Deprecations

| File / Dependency     | Status      | Replaced by                              |
|-----------------------|-------------|------------------------------------------|
| `daemon_fx.py`        | Deprecated  | `daemon.py`                              |
| `trade_manager.py`    | Deprecated  | `daemon.py`                              |
| `daemon_crypto.py`    | Removed     | n/a                                      |
| `indicator_btcusd.py` | Removed     | n/a                                      |
| `trade_manager.jsonl` | Deprecated  | `fx_trades.jsonl`                        |
| `yfinance` package    | Removed     | `datalib.load()` / `oanda.get_candles()` |
| `Dockerfile.crypto`   | Removed     | n/a                                      |

`yfinance` is removed from `requirements.txt`. Any remaining import of `yfinance` anywhere in the codebase is a bug. The `FX_DATA_SOURCE` environment variable is removed — OANDA is the only source.

---

## 10. BTC Deprecation Rationale

- Live performance has not matched backtest expectations.
- Strategy is a session-based FX scalper (London/NY overlap). BTC trades 24/7 with no analogous session structure; the session gate that defines edge on FX pairs has no equivalent on BTC.
- No ADX gate was implemented for BTC (ADX=0 = exempt) — the strategy was trading regardless of regime.
- HA stop semantics differ (dollar-based vs pip-based) creating maintenance complexity.
- Operational cost: separate Docker container, separate log, separate alerting.
- Decision: remove BTC, invest the operational overhead in evaluating EURJPY as a fifth FX pair.

---

## 11. Open Issues (pre-implementation)

| # | Issue | Status |
|---|---|---|
| 1 | AUDUSD ADX gate compliance — investigate live trades continuing after May 11 gate deployment | Resolved — v2 uses OANDA-only data; ADX divergence root cause was Yahoo synthetic data |
| 2 | Validate first backtest run against STRATEGY_LOGBOOK.md snapshots | Resolved — new baselines established with OANDA data |
| 3 | `oanda.py` — add `get_candles_paginated()` | Resolved |
| 4 | Unified trade log migration | Resolved — single `fx_trades.jsonl` with `trade_type` field |
| 5 | GBPUSD retirement decision — re-evaluate once EURJPY backtested | Open — EURJPY PF 1.38/1.57; deferred until position headroom available |
| 6 | Bar-synchronised sleep DST boundary handling | Open — low priority |
| 7 | `datalib` initial seed rate-limiting — OANDA throttle testing | Resolved — no throttling observed in practice |

### 11.1 Post-Implementation Fixes

| Date | Fix | Detail |
|---|---|---|
| 2026-05-25 | Spread guard failure mode | Was failing open (allowing entry); now fails closed (blocks entry) |
| 2026-05-25 | Phase 3 momentum gate removed | HA colour check was near-universally true; extension is now unconditional |
| 2026-05-25 | Drawdown circuit breaker | Session loss % tracked per day; entries halted at DRAWDOWN_HALT_PCT; daily reset at UTC midnight |
| 2026-05-25 | Cooldown extended | 30 min → 60 min (15% win rate observed in 30–60 min window) |
| 2026-05-25 | Backtest spread constants aligned | Scalp/long spreads now match daemon STANDARD_SPREADS |
| 2026-05-25 | extend_tp log replay | extend_tp events now persisted with sl/tp fields; replayed correctly on restart |
| 2026-05-25 | Signal suppression on order failure | last_signal_bar no longer set when _open_automated() raises an exception |
| 2026-05-25 | Threading safety | _LOG_LOCK serialises JSONL writes; _STATE_LOCK guards ctrl/states/managed between control thread and main loop |

---

## 11.2 Open Issues — Quant Review 2026-05-25

Findings from the quant software architect review that remain open, renumbered for tracking. See §11.1 for items fixed in the same session. Severity: **Critical** > **High** > **Medium**.

| # | Orig | Severity | File(s) | Finding |
|---|------|----------|---------|---------|
| 1 | 12 | Critical | `daemon.py:98–103` | **Correlated 4-pair USD exposure** — BUY on EUR/GBP/AUD + SELL on USDJPY is four simultaneous USD-short positions. A USD spike hits all four at once. No correlation gate; no max-concurrent-position count enforced in code. |
| 2 | 28 | Critical | `daemon.py:1543` | **Control socket on `0.0.0.0`, no authentication** — anyone reaching port 9876 (e.g. on a VPS) can issue `close`, `stoploss`, or `register` commands. Should bind to `127.0.0.1` and/or require a shared secret. |
| 3 | 6  | High | `daemon.py` | **TP not adjusted to actual fill price** — on slippage, `entry_price` is updated to the fill but `take_profit` (and the order placed on OANDA) is not shifted. The reward distance shrinks or grows silently. |
| 4 | 13/14 | High | `daemon.py` | **Ghost position after broker-fired SL or weekend close** — automated positions are never reconciled against OANDA's open-trades list. A broker SL during a network gap leaves the daemon managing a non-existent position until the next natural event. |
| 5 | 21 | High | `datalib.py:303–306` | **Partial-bar heuristic drops valid low-volume bars** — last bar dropped if volume < 10 % of median. Asian-session and early-London bars legitimately fail this threshold, causing a 5–10 min lag in signal evaluation and a systematic gap in bar series. |
| 6 | 19 | High | `backtest.py` | **Long-mode backtest applies 5m indicator parameters to 1h bars** — `M5_EMA_FAST`, `M5_EMA_SLOW`, `M5_RSI_PERIOD`, `M5_ATR_MIN` are passed to `compute_m5_indicators()` even when running on 1h bars. Long-mode results use mismatched parameters; treat long-mode PF figures as indicative only. |
| 7 | 2  | High | `backtest.py` | **HA open cold-started on 35-bar evaluation slice** — `compute_m5_indicators` resets `ha_open[0]` to `(O+C)/2` at each slice. With a 35-bar window, the first ~14 bars of HA colour are corrupted. Pattern D uses bars i−4 through i — some fall in the warm-up zone. Live daemon (600-bar cache) is unaffected. |
| 8 | 3  | High (deferred) | all indicators | **SL floor `HA_SL_MIN_PIPS` overrides ATR_SL_MULT for patterns A/C** — ATR × 0.4 averages 3–6 pips on EURUSD but is floored to 10, making the parameter effectively inert. R:R degrades silently in low-ATR sessions. Deliberately deferred — see `project_atrslt_floor_issue.md` for full analysis. Dollar risk is correct; only R:R is affected. |
| 9 | 31 | Medium | all indicators | **Parameter optimisation on 60-day window — overfitting risk** — ~60–70 trades per free parameter is below the 100:1 reliability threshold. `GBPUSD ADX=25` is aggressively fitted to one regime; a volatility shift could block GBPUSD entries entirely. Revisit after 6+ months of live data. |
| 10 | 10 | Medium | `backtest.py` | **Spread double-counted in backtest P&L** — spread is applied to entry price when computing SL/TP, then deducted again when recording the exit. Makes backtest slightly pessimistic (1× spread per trade). |
| 11 | 20 | Medium | `backtest.py` | **Max drawdown reported in pips, not dollars** — understates true dollar risk when position size varies across pairs (USDJPY lot sizes differ significantly from EURUSD). |
| 12 | 29 | Medium | `daemon.py` | **`month_pips` on restart accumulates all history** — log replay sums every closed trade regardless of month. Status emails report a cumulative figure, not the current calendar month. |
| 13 | 35 | Medium | `daemon.py` (paper mode) | **Paper mode uses signal bar close as entry price** — in paper mode there is no OANDA fill; `entry_price` is set to the signal bar's close. The backtest uses next-bar open. Paper results are more optimistic than either backtest or live. |

---

## 12. Implementation Sequence

1. **Add `oanda.get_candles_paginated()`** — extend `oanda.py` with the paginated fetch wrapper. Test against all 4 pairs at M1/H1/D.

2. **Create `datalib.py`** — persistent parquet store, `update()`, `load()`, `resample()`, `status()`. Run `python datalib.py seed` for all pairs. Verify row counts and date ranges with `python datalib.py status`.

3. **Create `tradelib.py`** — extract `Position`, `check_position_events`, `calc_units` from `daemon_fx.py`. Write unit tests covering all Phase 1–3 scenarios (breakeven trigger, trail ratchet, TP extension, TP extension rejected when HA colour disagrees).

4. **Rewrite `backtest.py`** — replace all Yahoo Finance and direct OANDA calls with `datalib.load()`. Import `check_position_events` from `tradelib`. Implement the M1 within-bar simulation loop. Remove `indicator_btcusd` import.

5. **Validate backtest against logbook** — run all 4 pairs, compare to STRATEGY_LOGBOOK.md snapshots. Expect some numeric differences (OANDA vs Yahoo). Establish new baselines and record them as the OANDA-data reference in the logbook.

6. **Write unified `daemon.py`** — merge `daemon_fx.py` and `trade_manager.py`. Bar-synchronised polling, 15s position monitoring, single control socket. Import from `tradelib`.

7. **Smoke test on paper mode** — start daemon, trigger an automated signal, register a discretionary trade, verify both show in `status`, both generate emails, both log to `fx_trades.jsonl`.

8. **Deprecate old files** — move `daemon_fx.py`, `trade_manager.py`, `daemon_crypto.py`, `indicator_btcusd.py` to `DEPRECATED/`. Update `Dockerfile.fx` and `docker-compose.yml`. Remove `yfinance` from `requirements.txt`.

9. **Evaluate EURJPY** — run backtest with OANDA data. Compare to May 2026 Yahoo-based results (PF 1.38/1.57). Decide on GBPUSD retirement.
