# Strategy Logbook

Track backtest snapshots over time to detect strategy decay, assess market-regime sensitivity, and guide parameter tuning.

---

## How to Add a Snapshot

1. Run `python3 backtest.py --all` and `python3 backtest.py --all --long`.
2. Compute the period net-change for each instrument:
   - **60d window** (scalp): TREND_UP > +4%, TREND_DOWN < −4%, else FLAT.
   - **730d window** (long): TREND_UP > +10%, TREND_DOWN < −10%, else FLAT.
3. Copy the **Snapshot Template** below, fill in the values, and append it as a new `## Snapshot` section.
4. Record any code or parameter changes in the **Changes Since Last Snapshot** field.

---

## Market Regime Classification

| Label        | Definition (60d scalp / 730d long)               |
|--------------|--------------------------------------------------|
| `TREND_UP`   | Net price change > +4% / +10% over the window   |
| `FLAT`       | Net price change within ±4% / ±10%              |
| `TREND_DOWN` | Net price change < −4% / −10%                   |

The regime is computed from Yahoo Finance daily closes at the start and end of the backtest window. It characterises the *macro backdrop* the strategy was tested against, not individual trade conditions.

---

## Snapshot Template

```
## Snapshot — YYYY-MM-DD

**Period:** scalp = 60d ending YYYY-MM-DD · long = 730d ending YYYY-MM-DD
**Changes since last snapshot:** <describe code / parameter changes, or "none">

### Scalp mode — 60d · 5m bars

| Pair   | Market Regime | Trades | Win% | Avg W | Avg L |  PF  | Expec | Total | Max DD |
|--------|---------------|--------|------|-------|-------|------|-------|-------|--------|
| EURUSD |               |        |      |       |       |      |       |       |        |
| GBPUSD |               |        |      |       |       |      |       |       |        |
| USDJPY |               |        |      |       |       |      |       |       |        |
| AUDUSD |               |        |      |       |       |      |       |       |        |
| BTCUSD |               |        |      |       |       |      |       |       |        |

### Long mode — 730d · 1h bars

| Pair   | Market Regime | Trades | Win% |  Avg W  | Avg L |  PF  |  Expec  |   Total  | Max DD  |
|--------|---------------|--------|------|---------|-------|------|---------|----------|---------|
| EURUSD |               |        |      |         |       |      |         |          |         |
| GBPUSD |               |        |      |         |       |      |         |          |         |
| USDJPY |               |        |      |         |       |      |         |          |         |
| AUDUSD |               |        |      |         |       |      |         |          |         |
| BTCUSD |               |        |      |         |       |      |         |          |         |

### Notes
-
```

---

## Snapshot — 2026-05-03

**Period:** scalp = 60d ending 2026-05-03 · long = 730d ending 2026-05-03
**Changes since last snapshot:** Initial logbook entry. Immediately prior changes: (1) wired 4h EMA22 gate into `daemon_crypto.py` — was defined in `indicator_btcusd.assess_h1_bias()` but never passed `df_4h`; now fetches 4h bars and passes them on every tick. (2) Restored `compute_sl_tp()` to `indicator_btcusd` (required by `backtest.py` interface).

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD −1.1%, GBPUSD −0.8%, USDJPY +1.2%, AUDUSD +3.8%, BTCUSD +16.7%

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     89 | 33.7% |  29.5 p  |  8.4 p  | 1.78 |   4.4 p/tr |    387.9 p |    −83.7 p  |
| GBPUSD | FLAT          |     82 | 23.2% |  44.2 p  |  9.9 p  | 1.35 |   2.7 p/tr |    218.4 p |    −81.7 p  |
| USDJPY | FLAT          |     69 | 23.2% |  60.1 p  | 10.3 p  | 1.76 |   6.0 p/tr |    416.1 p |   −113.5 p  |
| AUDUSD | FLAT          |     67 | 38.8% |  29.0 p  |  9.0 p  | 2.03 |   5.7 p/tr |    381.9 p |    −39.0 p  |
| BTCUSD | TREND_UP      |    140 | 26.4% | $988/BTC | $211    | 1.68 | $106/tr    | $14,800.9  |   −$3,727.9 |

(p = pips · tr = trade · BTCUSD pips = USD)

### Long mode — 730d · 1h bars

730d net-change: EURUSD +5.3%, GBPUSD +5.6%, USDJPY +10.8%, AUDUSD +7.1%, BTCUSD +22.1%

| Pair   | Market Regime | Trades | Win%  |   Avg W   | Avg L   |  PF  |   Expec    |     Total    | Max DD      |
|--------|---------------|--------|-------|-----------|---------|------|------------|--------------|-------------|
| EURUSD | FLAT          |    326 | 24.2% |   53.3 p  | 11.4 p  | 1.49 |   4.3 p/tr |    1,386.2 p |   −204.1 p  |
| GBPUSD | FLAT          |    351 | 20.2% |   76.7 p  | 13.1 p  | 1.48 |   5.0 p/tr |    1,765.2 p |   −450.3 p  |
| USDJPY | TREND_UP      |    337 | 21.4% |  111.8 p  | 16.1 p  | 1.89 |  11.2 p/tr |    3,790.8 p |   −208.7 p  |
| AUDUSD | FLAT          |    347 | 22.8% |   50.9 p  | 10.6 p  | 1.41 |   3.4 p/tr |    1,173.7 p |   −163.6 p  |
| BTCUSD | TREND_UP      |    326 | 25.2% | $2,604/BTC| $407    | 2.15 | $351/tr    |  $114,306.8  |  −$5,244.0  |

### Notes

- **AUDUSD** is the best scalp pair this window: highest win rate (38.8%), best FX PF (2.03), and by far the tightest drawdown (−39 pips). Approaching TREND_UP boundary (+3.8%) — recheck next snapshot to see if a bull regime boosts or saturates it.
- **BTCUSD** dominates long mode (PF 2.15) across its 730d TREND_UP window. High absolute drawdown (−$5,244) is expected given dollar-denominated stops; at 1% risk / $10k account this is ~52 consecutive max-loss trades.
- **GBPUSD** is the weakest pair in both modes (scalp PF 1.35). The long-mode drawdown (−450 p) is disproportionate to its avg loss (13 p), suggesting a concentrated losing streak in the 730d history. Monitor — if scalp PF dips below 1.2 at the next snapshot, consider suspending it.
- **USDJPY** improves markedly from scalp to long (1.76 → 1.89) and carries the highest expectancy of the FX pairs in long mode (11.2 p/trade). Regime shifted to TREND_UP in the 730d window (+10.8%), which may partly explain the wide avg win.
- **All FX pairs** tested in a FLAT 60d macro environment. This is the baseline condition; a future TREND_UP or TREND_DOWN snapshot will reveal regime sensitivity.
- **4h EMA22 gate** was inactive in live crypto trading until 2026-05-03. The backtest results above already include the gate; prior live results (crypto_trades.jsonl, 18 trades, PF 2.47) did not have it — treat the live PF as uncontrolled for comparison purposes.

---
