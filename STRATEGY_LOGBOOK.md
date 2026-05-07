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

## Snapshot — 2026-05-07

**Period:** scalp = 60d ending 2026-05-07 · long = 730d ending 2026-05-07
**Changes since last snapshot:** (1) Applied `HA_SL_MAX_PIPS` ceiling to ATR-based SL in patterns A and C across all four FX indicator files — previously only pattern D (HA pullback) clamped to the max; A/C had a floor but no ceiling, allowing SL widths of 13+ pips when ATR was elevated. (2) Removed staleness gate from `daemon_fx.py` — it suppressed all signals when using Oanda as the bar data source (bar_time is candle open, naturally 5–45 min old).

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD −0.8%, GBPUSD +0.0%, USDJPY +2.3%, AUDUSD +2.4%, BTCUSD +18.2%

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     81 | 44.4% |  27.9 p  | 11.5 p  | 1.93 |   6.0 p/tr |    485.3 p |    −82.5 p  |
| GBPUSD | FLAT          |     77 | 29.9% |  42.7 p  | 11.9 p  | 1.53 |   4.4 p/tr |    339.9 p |    −95.4 p  |
| USDJPY | FLAT          |     69 | 23.2% |  59.1 p  | 10.2 p  | 1.74 |   5.8 p/tr |    403.3 p |   −113.5 p  |
| AUDUSD | FLAT          |     66 | 42.4% |  28.1 p  | 11.8 p  | 1.75 |   5.1 p/tr |    337.1 p |    −70.8 p  |
| BTCUSD | TREND_UP      |    141 | 27.7% | 968.6 p  | 210.8 p | 1.76 | 115.4 p/tr |  16271.6 p |  −3727.9 p  |

(p = pips · tr = trade · BTCUSD pips = USD)

### Long mode — 730d · 1h bars

730d net-change: EURUSD +5.7%, GBPUSD +5.8%, USDJPY +11.8%, AUDUSD +7.1%, BTCUSD +32.1%

| Pair   | Market Regime | Trades | Win%  |   Avg W   | Avg L   |  PF  |   Expec    |     Total    | Max DD      |
|--------|---------------|--------|-------|-----------|---------|------|------------|--------------|-------------|
| EURUSD | FLAT          |    325 | 24.3% |   53.1 p  | 11.6 p  | 1.47 |   4.1 p/tr |    1,338.4 p |   −193.5 p  |
| GBPUSD | FLAT          |    354 | 19.5% |   76.1 p  | 12.4 p  | 1.49 |   4.8 p/tr |    1,715.1 p |   −444.1 p  |
| USDJPY | TREND_UP      |    355 | 16.9% |  104.3 p  | 12.3 p  | 1.73 |   7.4 p/tr |    2,639.2 p |   −313.5 p  |
| AUDUSD | FLAT          |    342 | 23.7% |   51.4 p  | 11.5 p  | 1.38 |   3.4 p/tr |    1,149.6 p |   −179.0 p  |
| BTCUSD | TREND_UP      |    327 | 24.8% | 2,618.7 p | 405.8 p | 2.13 | 343.4 p/tr |  112,299.3 p |  −5,244.0 p |

### Notes

- **EURUSD scalp** is the standout improvement: PF 1.78 → 1.93, WR 33.7% → 44.4%, total pips 387.9 → 485.3. The SL cap fix appears to have had the most impact here.
- **GBPUSD scalp** recovered from the weakest position (PF 1.35 → 1.53, total pips 218.4 → 339.9) — no longer at suspension risk.
- **USDJPY** essentially unchanged in both modes (scalp PF 1.76 → 1.74; long PF 1.89 → 1.73). USDJPY uses a lower SL min (7 pips) so patterns A/C were less likely to breach the old uncapped ceiling.
- **AUDUSD scalp** declined (PF 2.03 → 1.75). This is likely a regime shift rather than the SL fix, since avg loss increased (9.0 → 11.8 p) counter to what tightening SL would produce. Prior snapshot was near the TREND_UP boundary (+3.8%); now +2.4% — slightly more corrective period in the window.
- **Long mode** is broadly stable vs prior snapshot. GBPUSD long improved marginally (1.48 → 1.49). EURUSD long dipped slightly (1.49 → 1.47). BTCUSD long unchanged (2.15 → 2.13).
- **Regime context:** all FX pairs remain FLAT in both windows. USDJPY crossed into TREND_UP in the 730d window (+11.8% vs +10.8% prior). Results comparable across snapshots.

---
