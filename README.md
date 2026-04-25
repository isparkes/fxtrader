# FX Scalper

A two-timeframe scalping system for major FX pairs and BTCUSD. The higher
timeframe sets the directional bias; the lower timeframe finds the precise
entry trigger. Signals can be generated live, or the strategy can be replayed
against historical data via the walk-forward backtest.

## Files

| File | Purpose |
|---|---|
| `indicator_eurusd.py` | Signal logic and parameters for EURUSD |
| `indicator_gbpusd.py` | Signal logic and parameters for GBPUSD |
| `indicator_usdjpy.py` | Signal logic and parameters for USDJPY |
| `indicator_audusd.py` | Signal logic and parameters for AUDUSD |
| `indicator_btcusd.py` | Signal logic and parameters for BTCUSD (pip = $1) |
| `daemon_fx.py` | Long-running daemon for FX pairs — polls, manages positions, sends email alerts |
| `daemon_crypto.py` | Long-running daemon for BTCUSD — as above, plus Binance order execution |
| `mailer.py` | SMTP email helper used by both daemons |
| `tradelog.py` | Append-only trade journal — persists positions across daemon restarts |
| `backtest.py` | Walk-forward backtest — replays the strategy against historical OHLCV data |
| `signals.jsonl` | Append-only log of every live FX signal that has been generated |
| `fx_trades.jsonl` | FX daemon trade log — one JSON line per OPEN / BE / CLOSE event |
| `crypto_trades.jsonl` | Crypto daemon trade log |
| `{pair}_backtest_trades.csv` | Trade-by-trade backtest output (one file per pair) |

## Active pairs

### FX (daemon_fx.py)

| Indicator file | Pair | Yahoo symbol |
|---|---|---|
| `indicator_eurusd.py` | Euro / US Dollar | `EURUSD=X` |
| `indicator_gbpusd.py` | Cable — British Pound / US Dollar | `GBPUSD=X` |
| `indicator_usdjpy.py` | US Dollar / Japanese Yen | `USDJPY=X` |
| `indicator_audusd.py` | Australian Dollar / US Dollar | `AUDUSD=X` |

### Crypto (daemon_crypto.py)

| Indicator file | Pair | Yahoo symbol |
|---|---|---|
| `indicator_btcusd.py` | Bitcoin / US Dollar | `BTC-USD` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Live signal for a specific pair
python indicator_eurusd.py
python indicator_btcusd.py

# Backtest a single pair — scalp mode, ~60 days of 5m bars
python backtest.py --pair gbpusd

# Backtest a single pair — long mode, ~730 days of 1h bars
python backtest.py --pair gbpusd --long

# Backtest BTCUSD
python backtest.py --pair btcusd

# Backtest all pairs and show combined summary table
python backtest.py --all
```

---

## Docker

### Prerequisites

Create a `.env` file with your email credentials (see `mailer.py` for the
required variables). The file is **not** baked into the image — it is passed
at runtime via `--env-file` in `docker run` or via `env_file:` in Compose.

For the crypto daemon also add:
```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TESTNET=false          # set to true to paper-trade on testnet
CRYPTO_RISK_USD=50             # max risk per trade in USD
CRYPTO_TRADE_SIZE_USD=1000     # max notional per trade in USD
```

### Build

There are two separate Dockerfiles — one per daemon:

```bash
# FX daemon
docker build -f Dockerfile.fx -t fxtrader .

# Crypto daemon
docker build -f Dockerfile.crypto -t cryptotrader .
```

### Build for Intel on Mac (cross-compile to `linux/amd64`)

If you are running Apple Silicon (M-series) and need to deploy to an Intel/AMD64
Linux host, pass `--platform linux/amd64` so Docker emulates the target
architecture via QEMU:

```bash
docker build --platform linux/amd64 -f Dockerfile.fx -t iansparkes/fxtrader:1.0.0 .
```

> **Note:** all dependencies (including numpy) are installed from pre-built
> binary wheels. Do **not** add `--no-binary numpy` or any other
> `--no-binary` flag — cross-compilation has no C compiler available and the
> source build will fail.

### Run with Docker Compose (recommended)

`docker-compose.yml` defines two services — `fxtrader` and `cryptotrader` —
and mounts separate trade-state files from the host so state survives restarts.

```bash
# Start both services
docker compose up -d

# Start only the FX daemon
docker compose up -d fxtrader

# Start only the crypto daemon
docker compose up -d cryptotrader
```

To override the default command for a service, add `command:` to
`docker-compose.yml`:

```yaml
# docker-compose.yml — examples
services:
  fxtrader:
    command: ["--dry-run"]
    # command: ["--pair", "eurusd", "--interval", "60"]

  cryptotrader:
    command: ["--dry-run"]
    # command: ["--interval", "60"]
```

### Run without Compose

```bash
# FX daemon — all pairs, default interval
docker run -d \
  --env-file .env \
  -v "$(pwd)/signals.jsonl:/app/signals.jsonl" \
  -v "$(pwd)/fx_trades.jsonl:/app/trades.jsonl" \
  --restart unless-stopped \
  fxtrader

# Crypto daemon — BTCUSD, dry-run
docker run -d \
  --env-file .env \
  -v "$(pwd)/crypto_trades.jsonl:/app/trades.jsonl" \
  --restart unless-stopped \
  cryptotrader --dry-run
```

### Daemon flags

**daemon_fx.py**

| Flag | Default | Description |
|---|---|---|
| `--pair <name>` | all FX pairs | Monitor a single pair (e.g. `eurusd`) |
| `--interval <seconds>` | `300` | Poll interval in seconds |
| `--dry-run` | off | Log events but do not send emails |

**daemon_crypto.py**

| Flag | Default | Description |
|---|---|---|
| `--interval <seconds>` | `300` | Poll interval in seconds |
| `--dry-run` | off | Log events; skip emails and Binance order placement |

### Viewing logs

```bash
docker compose logs -f
docker compose logs -f fxtrader
docker compose logs -f cryptotrader
```

---

## Strategy

### Trend filter (1h bars — all three gates must pass)

The trend is assessed on the most recent 1h bar (`iloc[-1]`, the forming bar),
matching live trading where waiting for close is impractical.

| Gate | BUY condition | SELL condition |
|---|---|---|
| EMA50 side | Close above EMA(50) | Close below EMA(50) |
| MACD histogram sign | Positive | Negative |
| RSI(14) | > 50 | < 50 |

All three must agree simultaneously. If any gate fails the bias is `FLAT` and
no entry is taken.

### 4h agreement gate — Measure 4

In addition to the 1h gates, the strategy applies a fourth filter on 4h bars
resampled from 1h data. The 4h close must be on the same side of the **4h
EMA(22)** as the 1h direction. A trade where 1h and 4h disagree is suppressed
as `FLAT` — this typically corresponds to intraday chop against the
higher-timeframe structure.

| Gate | BUY condition | SELL condition |
|---|---|---|
| 4h EMA(22) side | 4h close above 4h EMA(22) | 4h close below 4h EMA(22) |

### SL/TP sizing

Stop loss and take profit distances are sized using the **1h ATR**, not the 4h
ATR. The 4h bars set the direction; the 1h ATR (forward-filled onto entry bars)
provides a sizing reference that matches the scale of the trade.

### Entry patterns (5m bars — evaluated only when bias is active)

Pre-checks applied to every bar:
- **Session gate** — bar must fall within 07:00–16:00 UTC (London open through
  NY afternoon). Only applied in scalp mode; skipped in long mode. Not applied
  to BTCUSD (24/7 market).
- **ATR floor** — 5m ATR(14) ≥ 0.0002 (2 pips / $50 for BTC). Prevents entries
  when the market is too compressed to reach the target.

**Pattern A — EMA8/21 cross**

| Direction | Trigger | Guards |
|---|---|---|
| BUY | EMA(8) crosses above EMA(21) | RSI(7) 52–75; Stoch %K > %D and < 80 |
| SELL | EMA(8) crosses below EMA(21) | RSI(7) 25–48; Stoch %K < %D and > 20 |

**Pattern C — MACD histogram flip**

| Direction | Trigger | Guards |
|---|---|---|
| BUY | 5m MACD hist (6/13/4) crosses zero upward; close > EMA(21) | RSI(7) 52–72; same Stoch conditions |
| SELL | 5m MACD hist crosses zero downward; close < EMA(21) | RSI(7) 28–48; same Stoch conditions |

**Pattern D — Heikin-Ashi pullback + resumption**

Requires a 5-bar HA sequence: 3 consecutive same-colour candles establishing
the local trend, 1 opposing pullback candle, then entry on the first candle
that resumes trend direction.

| Direction | Trigger |
|---|---|
| BUY | 3 bullish HA → 1 bearish pullback → bullish resumption |
| SELL | 3 bearish HA → 1 bullish pullback → bearish resumption |

Stop loss is anchored to the pullback candle's extreme ± a buffer, then
clamped within `HA_SL_MIN_PIPS`–`HA_SL_MAX_PIPS`. If the clamped stop
produces R:R < 1.5 the signal is suppressed. No additional RSI or Stochastic
guards — the HA sequence itself provides the quality filter.

### Risk management

| Parameter | Default | Notes |
|---|---|---|
| Stop loss (A/C) | 1h ATR(14) × 0.4 | Set at entry, never widened; ~4–8 pips on EURUSD |
| Take profit | 1h ATR(14) × 3.0 | Wide ceiling; trailing stop typically exits first |
| Stop loss (D) | Pullback extreme ± buffer, clamped | `HA_SL_MIN_PIPS` to `HA_SL_MAX_PIPS` from entry |
| Trailing stop — phase 1 | Move to entry (breakeven) | EURUSD: triggered at 70% of TP; others: 80% |
| Trailing stop — phase 2 | Trail ATR × 0.4 behind best price | Runs from breakeven; exits when momentum exhausts |
| Cooldown after loss | 6 bars (30 min in scalp mode) | Prevents revenge trading |

### Indicator parameters

Parameters are defined at the top of each pair's indicator file
(`indicator_eurusd.py`, `indicator_gbpusd.py`, etc.) and can be tuned
independently per pair.

**Trend timeframe (1h)**

| Parameter | Constant | Default |
|---|---|---|
| EMA trend | `H1_EMA_TREND` | 50 |
| MACD | `H1_MACD_FAST / SLOW / SIGNAL` | 12 / 26 / 9 |
| RSI | `H1_RSI_PERIOD` | 14 |
| ATR (for SL/TP sizing) | `ATR_PERIOD` | 14 |

**4h agreement gate**

| Parameter | Constant | Default |
|---|---|---|
| EMA period | `H4_EMA_PERIOD` | 22 |

**Entry timeframe (5m)**

| Parameter | Constant | Default |
|---|---|---|
| EMA fast / slow | `M5_EMA_FAST / SLOW` | 8 / 21 |
| RSI | `M5_RSI_PERIOD` | 7 |
| MACD | (hard-coded 6 / 13 / 4) | — |
| Stochastic | `M5_STOCH_PERIOD / SMOOTH` | 14 / 3 |
| ATR floor | `M5_ATR_MIN` | 0.0002 (FX) / 50.0 (BTC) |

**Risk**

| Parameter | Constant | EURUSD / GBPUSD / AUDUSD | USDJPY | BTCUSD |
|---|---|---|---|---|
| Stop loss multiplier | `ATR_SL_MULT` | 0.4 | 0.4 | 0.4 |
| Take profit multiplier | `ATR_TP_MULT` | 3.0 | 3.0 | 3.0 |
| Pattern D — SL buffer | `HA_SL_BUFFER_PIPS` | 2 pips | 2 pips | $50 |
| Pattern D — SL floor | `HA_SL_MIN_PIPS` | 10 pips | 7 pips | $200 |
| Pattern D — SL ceiling | `HA_SL_MAX_PIPS` | 12 pips | 12 pips | $800 |
| Breakeven trigger | `TRAIL_ACTIVATE_FRAC` | 0.7 (EURUSD) / 0.8 | 0.8 | 0.8 |

---

## Backtest modes

### Scalp mode (default)

- **Data:** ~60 days of 5m entry bars; trend from 4h bars resampled from 1h
- **SL/TP sizing:** 1h ATR, forward-filled onto 5m bars
- **Session filter:** active for FX (entries restricted to 07:00–16:00 UTC); disabled for BTCUSD
- **Spread:** pair-dependent (see table below)

### Long mode (`--long`)

- **Data:** ~730 days of 1h entry bars; trend from 4h bars resampled from those same 1h bars
- **SL/TP sizing:** ATR computed on the 1h entry bars
- **Session filter:** disabled (1h bars already smooth thin periods)
- **Same indicator logic** — entry patterns and risk parameters are identical

The merged dataset uses `merge_asof` with `direction="backward"` so each entry
bar receives only the most recently *completed* trend bar's values. This
prevents look-ahead bias.

### Default spreads per pair

| Pair | Scalp | Long | Unit |
|---|---|---|---|
| EURUSD | 1.5 pips | 1.0 pip | pips |
| GBPUSD | 1.8 pips | 1.2 pips | pips |
| USDJPY | 1.5 pips | 1.0 pip | pips |
| AUDUSD | 1.8 pips | 1.2 pips | pips |
| BTCUSD | $20 | $15 | USD |

---

## Output

### Live signal (`indicator_*.py`)

Prints a Rich-formatted panel showing direction, entry, stop loss, take profit,
R:R ratio, and the indicator values that triggered the signal. Appends the
signal as a JSON line to `signals.jsonl`.

### Backtest (`backtest.py`)

Prints a summary table:

| Metric | Description |
|---|---|
| Total trades | Number of completed trades in the period |
| Trades / day | Average daily frequency |
| Win rate | Percentage of trades that closed positive |
| Avg win / Avg loss | Mean pip outcome for winners and losers |
| Profit factor | Gross profit ÷ gross loss (> 1.0 = net profitable) |
| Expectancy | Expected pips per trade = (WR × avg win) − (LR × avg loss) |
| Total pips | Net pip result across all trades |
| Max drawdown | Largest peak-to-trough decline in cumulative pips |
| Avg hold time | Mean trade duration |
| Forced closes | Trades closed by a time limit (always 0 — this strategy has none) |

Saves the full trade-by-trade log to `{pair}_backtest_trades.csv` with columns:
`direction`, `entry`, `exit`, `sl`, `tp`, `held_bars`, `held_mins`,
`pnl_pips`, `result`, `forced`.

Optionally pass `--account` and `--risk` to show position sizing alongside
each trade:

```bash
python backtest.py --pair eurusd --account 10000 --risk 1.0
```

---

## Tuning a pair

Each pair's strategy parameters live entirely in its own indicator file.
To adjust EURUSD, for example, open `indicator_eurusd.py` and edit the
constants in the *Tunable parameters* block near the top:

```python
ATR_SL_MULT        = 0.4    # widen or tighten the stop
ATR_TP_MULT        = 3.0    # adjust the TP ceiling
M5_ATR_MIN         = 0.0002 # raise to filter quieter sessions
HA_SL_MIN_PIPS     = 10     # Pattern D — tightest allowed stop
TRAIL_ACTIVATE_FRAC = 0.7   # move to breakeven at 70% of TP
```

Changes are picked up automatically by `daemon_fx.py` and `backtest.py` on
the next run — no other files need editing.

## Adding a new FX pair

1. Copy an existing indicator file and rename it:
   ```bash
   cp indicator_eurusd.py indicator_eurjpy.py
   ```
2. In `indicator_eurjpy.py` update the `PAIRS` dict and `SYMBOL`:
   ```python
   PAIRS  = {"eurjpy": "EURJPY=X"}
   SYMBOL = "EURJPY=X"
   ```
3. Register the module in **both** `daemon_fx.py` and `backtest.py`:
   ```python
   import indicator_eurjpy
   PAIRS["eurjpy"] = "EURJPY=X"
   PAIR_INDICATORS["eurjpy"] = indicator_eurjpy
   ```
4. Add spread defaults to `PAIR_CONFIG` in `backtest.py`:
   ```python
   "eurjpy": {"spread_scalp": 1.5, "spread_long": 1.0},
   ```

> **JPY pairs:** the pip value is 0.01 (not 0.0001). `pip_value()` in the
> indicator files handles this automatically — no manual adjustment needed.

## Current backtest results

Results use the forming-bar approach: the trend bias reads `iloc[-1]` (current
forming 4h bar), matching live trading where waiting for bar close is
impractical at the 5m/1h entry timeframe.

### Scalp mode — 60 days · 5m bars (as of 2026-04-19)

| Pair | Trades | Win % | Avg Win | Avg Loss | Prof. Factor | Expectancy | Total | Max DD | Unit |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 111 | 25.2% | 32.1 | 7.8 | **1.40** | +2.3 | +255.5 | -175.7 | pips |
| USDJPY | 91 | 20.9% | 55.9 | 10.4 | **1.42** | +3.5 | +316.0 | -115.2 | pips |
| AUDUSD | 81 | 29.6% | 30.7 | 8.5 | **1.52** | +3.1 | +251.1 | -89.9 | pips |
| GBPUSD | 99 | 19.2% | 48.2 | 9.5 | **1.21** | +1.6 | +157.2 | -103.7 | pips |
| BTCUSD | 146 | 26.0% | 1114.5 | 227.5 | **1.72** | +121.8 | +17,781 | -3,295 | USD |

### Long mode — 730 days · 1h bars (as of 2026-04-19)

| Pair | Trades | Win % | Avg Win | Avg Loss | Prof. Factor | Expectancy | Total | Max DD | Unit |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 329 | 23.7% | 53.7 | 10.8 | **1.54** | +4.5 | +1469.7 | -183.2 | pips |
| USDJPY | 332 | 21.4% | 112.4 | 16.1 | **1.90** | +11.4 | +3770.0 | -208.7 | pips |
| GBPUSD | 355 | 20.0% | 77.1 | 12.6 | **1.53** | +5.4 | +1904.3 | -518.5 | pips |
| AUDUSD | 346 | 21.4% | 50.7 | 10.0 | **1.38** | +3.0 | +1033.9 | -159.2 | pips |
| BTCUSD | — | — | — | — | **2.12** | — | — | — | USD |

All five instruments are profitable in both modes. BTCUSD has the strongest
profit factor in scalp mode (1.72) and long mode (2.12). USDJPY shows the
best pip edge in long mode (PF 1.90, +3770 pips). GBPUSD has the largest
drawdown relative to total gain in long mode and warrants monitoring.
