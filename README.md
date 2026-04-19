# FX Scalper

A two-timeframe scalping system for major FX pairs. The higher timeframe sets
the directional bias; the lower timeframe finds the precise entry trigger.
Signals can be generated live, or the strategy can be replayed against
historical data via the walk-forward backtest.

## Files

| File | Purpose |
|---|---|
| `indicator_eurusd.py` | Signal logic and parameters for EURUSD |
| `indicator_gbpusd.py` | Signal logic and parameters for GBPUSD |
| `indicator_usdjpy.py` | Signal logic and parameters for USDJPY |
| `indicator_audusd.py` | Signal logic and parameters for AUDUSD |
| `daemon.py` | Long-running daemon — polls pairs, manages positions, sends email alerts |
| `mailer.py` | SMTP email helper used by the daemon |
| `tradelog.py` | Append-only trade journal (`trades.jsonl`) — persists positions across daemon restarts |
| `backtest.py` | Walk-forward backtest — replays the strategy against historical OHLCV data |
| `signals.jsonl` | Append-only log of every live signal that has been generated |
| `trades.jsonl` | Daemon trade log — one JSON line per OPEN / BE / CLOSE event |
| `{pair}_backtest_trades.csv` | Trade-by-trade backtest output (one file per pair) |

## Active pairs

The system trades the four most profitable pairs, each with its own indicator
file so signal parameters and risk settings can be tuned independently.

| Indicator file | Pair | Yahoo symbol |
|---|---|---|
| `indicator_eurusd.py` | Euro / US Dollar | `EURUSD=X` |
| `indicator_gbpusd.py` | Cable — British Pound / US Dollar | `GBPUSD=X` |
| `indicator_usdjpy.py` | US Dollar / Japanese Yen | `USDJPY=X` |
| `indicator_audusd.py` | Australian Dollar / US Dollar | `AUDUSD=X` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Live signal for a specific pair
python indicator_eurusd.py
python indicator_usdjpy.py

# Backtest a single pair — scalp mode, ~60 days of 5m bars
python backtest.py --pair gbpusd

# Backtest a single pair — long mode, ~730 days of 1h bars
python backtest.py --pair gbpusd --long

# Backtest all 4 pairs and show combined summary table
python backtest.py --all
```

---

## Docker

### Prerequisites

Create a `.env` file with your email credentials before building (see `mailer.py` for the required variables). The file is copied into the image at build time and is also passed via `env_file` in Compose so runtime overrides work too.

### Build

```bash
docker build -t fxtrader .
```

### Build for Intel on Mac (cross-compile to `linux/amd64`)

If you are running Apple Silicon (M-series) and need to deploy to an Intel/AMD64
Linux host, pass `--platform linux/amd64` so Docker emulates the target
architecture via QEMU:

```bash
docker build --platform linux/amd64 -t iansparkes/fxtrader:1.0.0 .
```

> **Note:** all dependencies (including numpy) are installed from pre-built
> binary wheels. Do **not** add `--no-binary numpy` or any other
> `--no-binary` flag — cross-compilation has no C compiler available and the
> source build will fail.

### Run with Docker Compose (recommended)

`docker-compose.yml` mounts `signals.jsonl` and `trades.jsonl` from the host so both the signal log and daemon trade state survive container restarts.

```bash
docker compose up -d
```

By default the daemon monitors all pairs on a 5-minute poll interval. To override, set `command` in `docker-compose.yml` or pass flags directly:

```yaml
# docker-compose.yml — examples
command: ["--dry-run"]
command: ["--pair", "eurusd", "--interval", "60"]
```

### Run without Compose

```bash
# All pairs, default interval, with persistent signal log and trade state
docker run -d \
  --env-file .env \
  -v "$(pwd)/signals.jsonl:/app/signals.jsonl" \
  -v "$(pwd)/trades.jsonl:/app/trades.jsonl" \
  --restart unless-stopped \
  fxtrader

# Single pair, 60-second interval, dry-run (no emails)
docker run -d \
  --env-file .env \
  -v "$(pwd)/signals.jsonl:/app/signals.jsonl" \
  -v "$(pwd)/trades.jsonl:/app/trades.jsonl" \
  fxtrader --pair eurusd --interval 60 --dry-run
```

### Daemon flags

| Flag | Default | Description |
|---|---|---|
| `--pair <name>` | all pairs | Monitor a single pair (e.g. `eurusd`) |
| `--interval <seconds>` | `300` | Poll interval in seconds |
| `--dry-run` | off | Log events but do not send emails |

### Viewing logs

```bash
docker compose logs -f
```

---

## Strategy

### Trend filter (4h bars — resampled from 1h, all three gates must pass)

The trend is assessed on 4h bars built by resampling 1h OHLCV data. The most
recent bar is still forming — `assess_h1_bias` reads `iloc[-1]` (the forming
bar), matching live trading where waiting a full 4h for bar close is
impractical.

| Gate | BUY condition | SELL condition |
|---|---|---|
| EMA50 side | Close above EMA(50) | Close below EMA(50) |
| MACD histogram sign | Positive | Negative |
| RSI(14) | > 50 | < 50 |

All three must agree simultaneously. If any gate fails the bias is `FLAT` and
no entry is taken.

### SL/TP sizing

Stop loss and take profit distances are sized using the **1h ATR**, not the 4h
ATR. The 4h bars set the direction; the 1h ATR (forward-filled onto entry bars)
provides a sizing reference that matches the scale of the trade.

### Entry patterns (5m bars — evaluated only when bias is active)

Pre-checks applied to every bar:
- **Session gate** — bar must fall within 07:00–16:00 UTC (London open through
  NY afternoon). Only applied in scalp mode; skipped in long mode.
- **ATR floor** — 5m ATR(14) ≥ 0.0002 (2 pips). Prevents entries when the
  market is too compressed to reach the target.

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

### Risk management

| Parameter | Value | Notes |
|---|---|---|
| Stop loss | 1h ATR(14) × 0.4 | Set at entry, never widened; ~4–8 pips on EURUSD |
| Take profit | 1h ATR(14) × 3.0 | Wide ceiling; rarely the binding exit |
| Trailing stop — phase 1 | Move to entry (breakeven) | Triggered once price reaches 80% of the initial TP distance |
| Trailing stop — phase 2 | Trail ATR × 0.4 behind best price | Runs from breakeven with no ceiling; exits when momentum exhausts |
| Cooldown after loss | 6 bars (30 min in scalp mode) | Prevents revenge trading into a still-unfavourable market |

The asymmetry — capped loss, uncapped win — is the core of the edge. The
trailing stop converts many near-winners into free trades once breakeven is
reached, and lets genuine trends run.

### Indicator parameters

Parameters are defined at the top of each pair's indicator file
(`indicator_eurusd.py`, `indicator_gbpusd.py`, etc.) and can be tuned
independently per pair. The defaults are:

**Trend timeframe (4h, resampled from 1h)**

| Parameter | Constant | Default |
|---|---|---|
| EMA trend | `H1_EMA_TREND` | 50 |
| MACD | `H1_MACD_FAST / SLOW / SIGNAL` | 12 / 26 / 9 |
| RSI | `H1_RSI_PERIOD` | 14 |
| ATR (for SL/TP sizing — computed on 1h bars) | `ATR_PERIOD` | 14 |

**Entry timeframe (5m)**

| Parameter | Constant | Default |
|---|---|---|
| EMA fast / slow | `M5_EMA_FAST / SLOW` | 8 / 21 |
| RSI | `M5_RSI_PERIOD` | 7 |
| MACD | (hard-coded 6 / 13 / 4) | — |
| Stochastic | `M5_STOCH_PERIOD / SMOOTH` | 14 / 3 |
| ATR | `ATR_PERIOD` | 14 |
| ATR floor | `M5_ATR_MIN` | 0.0002 |

**Risk**

| Parameter | Constant | Default |
|---|---|---|
| Stop loss multiplier | `ATR_SL_MULT` | 0.4 |
| Take profit multiplier | `ATR_TP_MULT` | 3.0 |

---

## Backtest modes

### Scalp mode (default)

- **Data:** ~60 days of 5m entry bars; trend from 4h bars resampled from 1h
- **SL/TP sizing:** 1h ATR, forward-filled onto 5m bars
- **Session filter:** active (entries restricted to 07:00–16:00 UTC)
- **Spread:** pair-dependent (EURUSD 1.5 pips, GBPUSD 1.8 pips, etc.)

### Long mode (`--long`)

- **Data:** ~730 days of 1h entry bars; trend from 4h bars resampled from those same 1h bars
- **SL/TP sizing:** ATR computed on the 1h entry bars (no separate sizing step needed)
- **Session filter:** disabled (1h bars already smooth thin periods)
- **Spread:** slightly tighter (EURUSD 1.0 pip, GBPUSD 1.2 pips, etc.)
- **Same indicator logic** — entry patterns and risk parameters are identical; ATR-based stops scale automatically with the 1h ATR.

The merged dataset uses `merge_asof` with `direction="backward"` so each entry
bar receives only the most recently *completed* trend bar's values. This
prevents look-ahead bias.

### Default spreads per pair

| Pair | Scalp | Long |
|---|---|---|
| EURUSD | 1.5 pips | 1.0 pip |
| GBPUSD | 1.8 pips | 1.2 pips |
| USDJPY | 1.5 pips | 1.0 pip |
| AUDUSD | 1.8 pips | 1.2 pips |

---

## Output

### Live signal (`indicator.py`)

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

---

## Tuning a pair

Each pair's strategy parameters live entirely in its own indicator file.
To adjust EURUSD, for example, open `indicator_eurusd.py` and edit the
constants in the *Tunable parameters* block near the top:

```python
ATR_SL_MULT = 0.4   # widen or tighten the stop
ATR_TP_MULT = 3.0   # adjust the TP ceiling
M5_ATR_MIN  = 0.0002  # raise to filter quieter sessions
```

Changes are picked up automatically by `daemon.py` and `backtest.py` on
the next run — no other files need editing.

## Adding a new pair

1. Copy an existing indicator file and rename it:
   ```bash
   cp indicator_eurusd.py indicator_eurjpy.py
   ```
2. In `indicator_eurjpy.py` update the `PAIRS` dict and `SYMBOL`:
   ```python
   PAIRS  = {"eurjpy": "EURJPY=X"}
   SYMBOL = "EURJPY=X"
   ```
3. Register the module in **both** `daemon.py` and `backtest.py`:
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

| Pair | Trades | Win % | Avg Win | Avg Loss | Prof. Factor | Expectancy | Total Pips | Max DD |
|---|---|---|---|---|---|---|---|---|
| EURUSD | 111 | 25.2% | 32.1 | 7.8 | **1.40** | +2.3 | +255.5 | -175.7 |
| USDJPY | 91 | 20.9% | 55.9 | 10.4 | **1.42** | +3.5 | +316.0 | -115.2 |
| AUDUSD | 81 | 29.6% | 30.7 | 8.5 | **1.52** | +3.1 | +251.1 | -89.9 |
| GBPUSD | 99 | 19.2% | 48.2 | 9.5 | **1.21** | +1.6 | +157.2 | -103.7 |

### Long mode — 730 days · 1h bars (as of 2026-04-19)

| Pair | Trades | Win % | Avg Win | Avg Loss | Prof. Factor | Expectancy | Total Pips | Max DD |
|---|---|---|---|---|---|---|---|---|
| EURUSD | 329 | 23.7% | 53.7 | 10.8 | **1.54** | +4.5 | +1469.7 | -183.2 |
| USDJPY | 332 | 21.4% | 112.4 | 16.1 | **1.90** | +11.4 | +3770.0 | -208.7 |
| GBPUSD | 355 | 20.0% | 77.1 | 12.6 | **1.53** | +5.4 | +1904.3 | -518.5 |
| AUDUSD | 346 | 21.4% | 50.7 | 10.0 | **1.38** | +3.0 | +1033.9 | -159.2 |

All four pairs are profitable in both modes. USDJPY shows the strongest edge in
long mode (PF 1.90, +3770 pips). GBPUSD has the largest drawdown relative to
total gain in long mode and warrants monitoring.

