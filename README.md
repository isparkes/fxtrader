# FX Scalper

A two-timeframe scalping system for major FX pairs. The higher timeframe sets
the directional bias; the lower timeframe finds the precise entry trigger.
Signals can be generated live, or the strategy can be replayed against
historical data via the walk-forward backtest.

## Files

| File | Purpose |
|---|---|
| `indicator.py` | Live signal generator — fetches current market data and prints the trading signal |
| `backtest.py` | Walk-forward backtest — replays the strategy against historical OHLCV data |
| `signals.jsonl` | Append-only log of every live signal that has been generated |
| `{pair}_backtest_trades.csv` | Trade-by-trade backtest output (one file per pair) |

## Supported pairs

Pass `--pair` to either script. The argument accepts the short name below.

| `--pair` | Pair | Yahoo symbol |
|---|---|---|
| `eurusd` (default) | Euro / US Dollar | `EURUSD=X` |
| `gbpusd` | Cable — British Pound / US Dollar | `GBPUSD=X` |
| `usdjpy` | US Dollar / Japanese Yen | `USDJPY=X` |
| `audusd` | Australian Dollar / US Dollar | `AUDUSD=X` |
| `usdcad` | US Dollar / Canadian Dollar | `USDCAD=X` |
| `usdchf` | US Dollar / Swiss Franc | `USDCHF=X` |
| `nzdusd` | New Zealand Dollar / US Dollar | `NZDUSD=X` |
| `eurgbp` | Euro / British Pound | `EURGBP=X` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Live signal (EURUSD, default)
python indicator.py

# Live signal (Cable)
python indicator.py --pair gbpusd

# Backtest — scalp mode, ~60 days of 5m bars
python backtest.py --pair gbpusd

# Backtest — long mode, ~730 days of 1h bars
python backtest.py --pair gbpusd --long
```

---

## Docker

### Prerequisites

Create a `.env` file with your email credentials before building (see `mailer.py` for the required variables). The file is copied into the image at build time and is also passed via `env_file` in Compose so runtime overrides work too.

### Build

```bash
docker build -t fxtrader .
```

### Build for Intel on Mac

```bash
docker build --platform linux/amd64 -t iansparkes/fxtrader:1.0.0 .
```

### Run with Docker Compose (recommended)

`docker-compose.yml` mounts `signals.jsonl` from the host so the signal log survives container restarts.

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
# All pairs, default interval, with persistent signal log
docker run -d \
  --env-file .env \
  -v "$(pwd)/signals.jsonl:/app/signals.jsonl" \
  --restart unless-stopped \
  fxtrader

# Single pair, 60-second interval, dry-run (no emails)
docker run -d \
  --env-file .env \
  -v "$(pwd)/signals.jsonl:/app/signals.jsonl" \
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

### Trend filter (1h bars — all three gates must pass)

| Gate | BUY condition | SELL condition |
|---|---|---|
| EMA50 side | Close above EMA(50) | Close below EMA(50) |
| MACD histogram | Positive **and** larger than previous bar | Negative **and** smaller (more negative) than previous bar |
| RSI(14) | > 50 | < 50 |

All three must agree simultaneously. If any gate fails the bias is `FLAT` and
no entry is taken.

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
| Stop loss | ATR(14) × 0.4 | Set at entry, never widened; ~4–8 pips on EURUSD |
| Take profit | ATR(14) × 3.0 | Wide ceiling; rarely the binding exit |
| Trailing stop — phase 1 | Move to entry (breakeven) | Triggered once price reaches 80% of the initial TP distance |
| Trailing stop — phase 2 | Trail ATR × 0.4 behind best price | Runs from breakeven with no ceiling; exits when momentum exhausts |
| Cooldown after loss | 6 bars (30 min in scalp mode) | Prevents revenge trading into a still-unfavourable market |

The asymmetry — capped loss, uncapped win — is the core of the edge. The
trailing stop converts many near-winners into free trades once breakeven is
reached, and lets genuine trends run.

### Indicator parameters

**Trend timeframe (1h)**

| Indicator | Setting |
|---|---|
| EMA trend | 50 |
| MACD | 12 / 26 / 9 |
| RSI | 14 |
| ATR (for SL/TP sizing) | 14 |

**Entry timeframe (5m)**

| Indicator | Setting |
|---|---|
| EMA fast / slow | 8 / 21 |
| RSI | 7 (short period for responsiveness) |
| MACD | 6 / 13 / 4 (faster than trend MACD) |
| Stochastic | 14 / 3 |
| ATR | 14 |

---

## Backtest modes

### Scalp mode (default)

- **Data:** ~60 days of 5m entry bars + 1h trend bars from Yahoo Finance
- **Session filter:** active (entries restricted to 07:00–16:00 UTC)
- **Spread:** pair-dependent (EURUSD 1.5 pips, GBPUSD 1.8 pips, etc.)

### Long mode (`--long`)

- **Data:** ~730 days of 1h entry bars; trend bars resampled to 4h
- **Session filter:** disabled (1h bars already smooth thin periods)
- **Spread:** slightly tighter (EURUSD 1.0 pip, GBPUSD 1.2 pips, etc.)
- **Same indicator logic** — the same indicator parameters and entry patterns
  apply; ATR-based stops scale automatically with the larger timeframe's ATR.

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
| USDCAD | 2.0 pips | 1.5 pips |
| USDCHF | 2.0 pips | 1.5 pips |
| NZDUSD | 2.5 pips | 2.0 pips |
| EURGBP | 1.5 pips | 1.0 pip |

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

## Adding a new pair

1. Add it to `PAIRS` in `indicator.py`:
   ```python
   "eurjpy": "EURJPY=X",
   ```
2. Add spread defaults to `PAIR_CONFIG` in `backtest.py`:
   ```python
   "eurjpy": {"spread_scalp": 1.5, "spread_long": 1.0},
   ```
3. That's it — both scripts will accept `--pair eurjpy` immediately.

> **Note:** For JPY pairs the pip value is 0.01 (not 0.0001). The current
> `PIP_VALUE` constant in `backtest.py` is set to 0.0001 and the pip-based
> metrics will be off by a factor of 100 for any JPY pair. Adjust `PIP_VALUE`
> to a per-pair value if you intend to use JPY pairs seriously.
