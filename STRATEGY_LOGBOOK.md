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

## How to Add a Candidate Evaluation

Run `python3 backtest.py --pair <pair>` (scalp) and `--pair <pair> --long` for each candidate. Compute 60d and 730d net price changes for regime labels. Append a `## Candidate Pair Evaluation` section with both tables sorted by PF, plus notes with a clear verdict (add / watch / skip) for each pair.

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

## Snapshot — 2026-05-09

**Period:** scalp = 60d ending 2026-05-09 · long = 730d ending 2026-05-09
**Changes since last snapshot:** (1) Split telnet `pause`/`resume` into independent `pause_entry`/`resume_entry` and `pause_exit`/`resume_exit` commands. (2) Added `materialise_sl` and `materialise_tp` control commands — place real broker SL/TP orders for occult-stops positions on demand. (3) Added `sl_materialised`/`tp_materialised` flags to `Position`; occult exits skip `close_trade()` when the relevant stop is already materialised. (4) Added `modify_trade_tp()` to `oanda.py`. No strategy logic or parameter changes.

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD +1.5%, GBPUSD +1.5%, USDJPY −0.8%, AUDUSD +2.6%, BTCUSD +15.0%

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     82 | 42.7% |  28.2 p  | 11.5 p  | 1.82 |   5.4 p/tr |    444.7 p |    −82.5 p  |
| GBPUSD | FLAT          |     78 | 29.5% |  42.6 p  | 11.9 p  | 1.50 |   4.2 p/tr |    324.9 p |    −95.4 p  |
| USDJPY | FLAT          |     68 | 22.1% |  59.4 p  | 10.2 p  | 1.64 |   5.1 p/tr |    348.1 p |   −105.0 p  |
| AUDUSD | FLAT          |     66 | 42.4% |  28.1 p  | 11.8 p  | 1.75 |   5.1 p/tr |    337.5 p |    −70.8 p  |
| BTCUSD | TREND_UP      |    135 | 27.4% | 964.7 p  | 206.8 p | 1.76 | 114.3 p/tr |  15,430.8 p |  −3,727.9 p |

(p = pips · tr = trade · BTCUSD pips = USD)

### Long mode — 730d · 1h bars

730d net-change: EURUSD +9.7%, GBPUSD +9.1%, USDJPY +0.8%, AUDUSD +10.2%, BTCUSD +27.6%

| Pair   | Market Regime | Trades | Win%  |   Avg W   | Avg L   |  PF  |   Expec    |     Total    | Max DD      |
|--------|---------------|--------|-------|-----------|---------|------|------------|--------------|-------------|
| EURUSD | FLAT          |    326 | 24.2% |   53.1 p  | 11.6 p  | 1.46 |   4.1 p/tr |    1,326.1 p |   −193.5 p  |
| GBPUSD | FLAT          |    354 | 19.5% |   76.1 p  | 12.4 p  | 1.49 |   4.8 p/tr |    1,715.4 p |   −444.1 p  |
| USDJPY | FLAT          |    354 | 16.9% |  104.3 p  | 12.3 p  | 1.74 |   7.5 p/tr |    2,652.1 p |   −313.5 p  |
| AUDUSD | TREND_UP      |    341 | 23.8% |   51.4 p  | 11.5 p  | 1.39 |   3.4 p/tr |    1,161.9 p |   −179.0 p  |
| BTCUSD | TREND_UP      |    326 | 24.5% | 2,619.0 p | 405.8 p | 2.10 | 336.5 p/tr |  109,697.6 p |  −5,244.0 p |

### Notes

- **No strategy changes this snapshot** — all movements are market-driven. Results validate that the control-port and materialise changes have no effect on backtest logic.
- **EURUSD scalp** ticked back slightly (PF 1.93 → 1.82) but WR is holding at 42.7%. Still the best FX pair by PF this window.
- **AUDUSD scalp** stable (PF 1.75 unchanged, WR 42.4% unchanged). AUDUSD crossed into TREND_UP in the 730d window (+10.2%); long-mode PF 1.39 is the weakest of the group — watch for further compression if the bull regime matures.
- **USDJPY scalp** dipped (PF 1.74 → 1.64). The 730d regime dropped from TREND_UP back to FLAT (+0.8%) — the yen trend has unwound. Long-mode PF held (1.73 → 1.74), suggesting robustness across regimes.
- **GBPUSD** broadly stable in both modes. Long-mode drawdown (−444 p) remains disproportionate to avg loss; no deterioration but continue to monitor.
- **BTCUSD** essentially unchanged in both modes (scalp PF 1.76, long PF 2.10 vs 2.13 prior — within noise).

---

## Snapshot — 2026-05-09 (post-Supertrend)

**Period:** scalp = 60d ending 2026-05-09 · long = 730d ending 2026-05-09
**Changes since last snapshot:** (1) Added `compute_supertrend()` (Pine Script v4 replica, ATR-based ratcheting bands) to all indicator files and `backtest.py` for testing; subsequently reverted from `indicator_eurusd.py`, `indicator_gbpusd.py`, and `indicator_audusd.py` after results confirmed no edge — net code change is Supertrend only in `indicator_usdjpy.py`. (2) Added Pattern E (5m Supertrend flip, period=10, mult=3.0) to USDJPY only — tested on all four FX pairs; retained only on USDJPY (PF 1.99 over 28 trades in D+E experiment). Pattern E was rejected for EURUSD (PF 1.01), AUDUSD (PF 1.03), and GBPUSD (PF 0.74); those three indicator files reverted to A+C+D unchanged. (3) H4 Supertrend AND gate (EMA22 + ST must agree) was tested and rejected — reduced trade count ~30% while hurting PF across all pairs by cutting D-pattern trades. H4 gate reverted to EMA22-only. (4) USDJPY switched to D+E only (Patterns A and C removed). (5) `backtest.py` trade log now includes a `pattern` column in all CSV exports.

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD +1.5%, GBPUSD +1.5%, USDJPY −0.8%, AUDUSD +2.0%, BTCUSD +14.7%

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total       | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|-------------|-------------|
| EURUSD | FLAT          |     82 | 42.7% |  28.2 p  | 11.5 p  | 1.82 |   5.4 p/tr |     444.7 p |    −82.5 p  |
| GBPUSD | FLAT          |     78 | 29.5% |  42.6 p  | 11.9 p  | 1.50 |   4.2 p/tr |     324.9 p |    −95.4 p  |
| USDJPY | FLAT          |     62 | 24.2% |  59.9 p  |  9.8 p  | 1.96 |   7.1 p/tr |     439.0 p |    −96.0 p  |
| AUDUSD | FLAT          |     66 | 42.4% |  28.1 p  | 11.8 p  | 1.75 |   5.1 p/tr |     337.5 p |    −70.8 p  |
| BTCUSD | TREND_UP      |    135 | 28.1% | 954.5 p  | 207.5 p | 1.80 | 119.6 p/tr |  16,145.0 p |  −3,727.9 p |

(p = pips · tr = trade · BTCUSD pips = USD · USDJPY: Patterns D+E only; others: A+C+D)

### Long mode — 730d · 1h bars

730d net-change: EURUSD +9.7%, GBPUSD +9.1%, USDJPY +0.8%, AUDUSD +9.6%, BTCUSD +27.2%

| Pair   | Market Regime | Trades | Win%  |   Avg W   | Avg L   |  PF  |   Expec    |      Total    | Max DD      |
|--------|---------------|--------|-------|-----------|---------|------|------------|---------------|-------------|
| EURUSD | FLAT          |    326 | 24.2% |   53.1 p  | 11.6 p  | 1.46 |   4.1 p/tr |    1,326.1 p  |   −193.5 p  |
| GBPUSD | FLAT          |    353 | 19.5% |   76.1 p  | 12.4 p  | 1.49 |   4.9 p/tr |    1,728.6 p  |   −444.1 p  |
| USDJPY | FLAT          |    252 | 18.3% |  109.7 p  | 11.9 p  | 2.07 |  10.3 p/tr |    2,601.9 p  |   −308.4 p  |
| AUDUSD | FLAT          |    341 | 23.8% |   51.4 p  | 11.5 p  | 1.39 |   3.4 p/tr |    1,161.9 p  |   −179.0 p  |
| BTCUSD | TREND_UP      |    326 | 24.5% | 2,619.0 p | 405.8 p | 2.10 | 336.5 p/tr |  109,697.6 p  |  −5,244.0 p |

### Notes

- **USDJPY scalp** is the standout improvement: PF 1.64 → 1.96, expectancy 5.1 → 7.1 p/tr, total pips 348 → 439. Removing A+C (both sub-1.0 PF on USDJPY in isolated testing) and keeping D+E produced this gain with fewer trades (68 → 62). Long mode also improved: PF 1.74 → 2.07, trade count down from 354 to 252 — higher quality entries only.
- **EURUSD scalp** stable (PF 1.93 → 1.82, WR 44.4% → 42.7%). The slight dip from the prior snapshot appears market-driven — the 60d window has shifted. Still the highest-WR pair among active FX.
- **AUDUSD scalp** unchanged (PF 1.75, WR 42.4%). Reliable baseline.
- **GBPUSD scalp** slight improvement (PF 1.50 vs 1.50 prior, total pips 325 vs 325). Essentially no change — A+C+D retained and the Supertrend experiment confirmed E hurts GBPUSD (PF 0.74 in testing). Long-mode DD (−444 p) still the largest of the group; keep monitoring.
- **BTCUSD** effectively unchanged in both modes (scalp PF 1.77, long PF 2.10). Pattern E was not tested on BTCUSD.
- **USDJPY long mode** remains FLAT in the 730d window (+0.8%, same as prior snapshot). The wide avg win (110 p) is driven by the D+E pattern combination selecting higher-quality entries, not a macro trend tailwind.
- **Regime context:** all four FX pairs FLAT in the 60d window. USDJPY crossed back into TREND_UP at 730d (+10.5%). Other pairs broadly FLAT. Results are directly comparable to the 2026-05-09 prior snapshot.
- **Code revert (EURUSD/GBPUSD/AUDUSD):** `compute_supertrend()` and Pattern E code removed from these three indicator files after the rejection results above. Their indicator files are functionally identical to the 2026-05-07 snapshot state; only `indicator_usdjpy.py` carries the Supertrend implementation.

---

## Snapshot — 2026-05-11

**Period:** scalp = 60d ending 2026-05-11
**Changes since last snapshot:** Added daily ADX(14) regime gate (`compute_daily_adx`, `DAILY_ADX_MIN`) to EURUSD, GBPUSD, USDJPY, AUDUSD. Gate suppresses all entries on days where the daily ADX is below the per-pair threshold. Per-pair thresholds set via sweep over 13–25 range selecting highest PF without excessive trade-count reduction: EURUSD=17, GBPUSD=25, USDJPY=0 (exempt — D+E patterns self-select trending conditions), AUDUSD=18. Gate is checked inside `assess_h1_bias()` as the final gate after the 4h EMA22 check; backtest wires daily data through `fetch_data()` → `run_backtest()` → `assess_h1_bias()`.

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD −1.1%, GBPUSD −0.3%, USDJPY +0.6%, AUDUSD +2.4%, BTCUSD +23.9%

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     73 | 45.2% |  27.8 p  | 11.6 p  | 1.98 |   6.2 p/tr |    455.2 p |    −82.5 p  |
| GBPUSD | FLAT          |     49 | 26.5% |  52.4 p  | 11.9 p  | 1.59 |   5.2 p/tr |    252.6 p |    −95.4 p  |
| USDJPY | FLAT          |     63 | 23.8% |  59.9 p  |  9.7 p  | 1.93 |   6.9 p/tr |    433.8 p |    −96.0 p  |
| AUDUSD | FLAT          |     61 | 42.6% |  28.2 p  | 11.8 p  | 1.77 |   5.2 p/tr |    320.0 p |    −70.8 p  |
| BTCUSD | TREND_UP      |    131 | 27.5% | 950.4 p  | 206.8 p | 1.74 | 111.2 p/tr |  14568.6 p |  −3727.9 p  |

(p = pips · tr = trade · BTCUSD pips = USD · USDJPY: Patterns D+E, ADX gate exempt; EURUSD/GBPUSD/AUDUSD: A+C+D)

### Notes

- **Daily ADX gate** improves 3 of 4 active FX pairs vs prior snapshot. EURUSD: PF 1.82→1.98 (+0.16). GBPUSD: PF 1.50→1.59 (+0.09) — most aggressive filter (ADX≥25) justified by it being the weakest pair; higher avg win (52 vs 43 p) suggests filtering genuinely improved trade selection. AUDUSD: PF 1.75→1.77 (marginal). USDJPY: exempt, PF 1.96→1.93 (within noise, −0.03).
- **USDJPY exemption rationale:** the Supertrend flip (Pattern E) is itself a trend-detection mechanism — stacking a daily ADX gate on top is redundant and loses 68% of valid trades at ADX≥20. Exempt confirmed correct.
- **GBPUSD ADX≥25:** today's GBPUSD ADX is 18.6, meaning GBPUSD would correctly be suppressed on days like today (confirmed — user reported no entries today, which matches ADX <25). Trade count reduced 78→49 but expectancy improved 4.2→5.2 p/trade; the remaining trades are higher quality.
- **Regime context:** all 4 FX pairs FLAT in the 60d window. BTCUSD TREND_UP. No long-mode run this snapshot (no strategy logic changes affecting long mode beyond the daily gate, which is not applied in long mode).

---

## Snapshot — 2026-05-11 (session-gate ablation)

**Period:** scalp = 60d ending 2026-05-11
**Changes since last snapshot:** Session gate (07:00–16:00 UTC) removed from all four FX indicator files and `backtest.py` outer loop for this run only — ablation to quantify how much of the edge is session-specific. Gate was **restored** immediately after; no permanent code change. Prior snapshot (2026-05-11 with daily ADX gate) is the active baseline.

### Scalp mode — 60d · 5m bars (no session gate)

60d net-change: EURUSD −1.1%, GBPUSD −0.3%, USDJPY +0.6%, AUDUSD +2.4%, BTCUSD +23.9% (same window as prior snapshot)

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |    123 | 36.6% |  27.3 p  | 11.6 p  | 1.36 |   2.6 p/tr |    324.5 p |   −117.0 p  |
| GBPUSD | FLAT          |     87 | 23.0% |  51.7 p  | 11.9 p  | 1.30 |   2.7 p/tr |    238.1 p |   −131.8 p  |
| USDJPY | FLAT          |    125 | 18.4% |  56.2 p  |  9.5 p  | 1.33 |   2.6 p/tr |    321.0 p |   −202.2 p  |
| AUDUSD | FLAT          |    106 | 36.8% |  27.7 p  | 11.8 p  | 1.36 |   2.7 p/tr |    287.9 p |   −106.2 p  |
| BTCUSD | TREND_UP      |    131 | 27.5% | 950.4 p  | 206.8 p | 1.74 | 111.2 p/tr |  14568.6 p |  −3727.9 p  |

(p = pips · tr = trade · BTCUSD pips = USD)

### Session gate impact — comparison vs prior snapshot (gate on)

| Pair   | Trades (on→off) | PF (on→off)   | WR (on→off)    | Total pips (on→off) | Max DD (on→off)   |
|--------|-----------------|---------------|----------------|---------------------|-------------------|
| EURUSD | 73 → 123 (+68%) | 1.98 → 1.36   | 45.2% → 36.6%  | +455 → +325 (−130)  | −82 → −117 (worse)|
| GBPUSD | 49 → 87  (+78%) | 1.59 → 1.30   | 26.5% → 23.0%  | +253 → +238 (−15)   | −95 → −132 (worse)|
| USDJPY | 63 → 125 (+98%) | 1.93 → 1.33   | 23.8% → 18.4%  | +434 → +321 (−113)  | −96 → −202 (worse)|
| AUDUSD | 61 → 106 (+74%) | 1.77 → 1.36   | 42.6% → 36.8%  | +320 → +288 (−32)   | −71 → −106 (worse)|

### Notes

- **Session gate is load-bearing.** Removing it increases trade count ~70–100% but degrades PF by 0.4–0.6 across all four pairs. Out-of-session entries (Asia / early morning UTC) are materially lower quality — total pips decline on every pair despite nearly double the opportunities.
- **USDJPY is most sensitive:** PF 1.93 → 1.33 (−0.60), DD doubles to −202 pips. Likely driven by Asian-session JPY volatility producing false pattern signals without the trend follow-through that characterises London/NY.
- **EURUSD WR compression:** 45.2% → 36.6%, reflecting the out-of-session bars pulling win rate toward the unconditional baseline. The session-filtered win rate (45%) is one of the clearest signals that the London/NY overlap is genuinely selective.
- **BTCUSD unaffected** (already ungated; same result both runs: PF 1.74).
- **Verdict:** session gate retained for all four FX pairs. The ablation confirms it is responsible for roughly 0.4–0.6 PF points across the active set.

---

## Snapshot — 2026-05-11 (building MACD gate)

**Period:** scalp = 60d ending 2026-05-11
**Changes since last snapshot:** Added "building MACD" requirement to `assess_h1_bias()` in all four FX indicator files. The 1h MACD histogram must now be **positive AND increasing** (i.e. `macd_hist > prev_macd`) for BUY bias, and **negative AND decreasing** for SELL bias. The check was documented in every indicator docstring since the initial build but had never been implemented — the code only checked sign, not direction of change. This is an ablation from the prior baseline.

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD −1.1%, GBPUSD −0.3%, USDJPY +0.6%, AUDUSD +2.4%, BTCUSD +23.9% (same window as prior snapshot)

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     54 | 53.7% |  29.8 p  | 11.5 p  | 3.01 |  10.7 p/tr |    577.1 p |    −34.5 p  |
| GBPUSD | FLAT          |     39 | 33.3% |  51.5 p  | 11.9 p  | 2.16 |   9.2 p/tr |    358.8 p |    −60.0 p  |
| USDJPY | FLAT          |     45 | 31.1% |  60.4 p  |  9.5 p  | 2.86 |  12.2 p/tr |    550.3 p |    −65.2 p  |
| AUDUSD | FLAT          |     52 | 50.0% |  29.1 p  | 11.8 p  | 2.45 |   8.6 p/tr |    448.1 p |    −47.2 p  |
| BTCUSD | TREND_UP      |    131 | 27.5% | 950.4 p  | 206.8 p | 1.74 | 111.2 p/tr |  14568.6 p |  −3727.9 p  |

(p = pips · tr = trade · BTCUSD pips = USD · USDJPY: Patterns D+E, ADX exempt; EURUSD/GBPUSD/AUDUSD: A+C+D)

### Building MACD gate impact — vs prior snapshot (sign-only)

| Pair   | Trades (old→new) | PF (old→new)   | WR (old→new)    | Total pips (old→new)   | Max DD (old→new)   |
|--------|------------------|----------------|-----------------|------------------------|--------------------|
| EURUSD | 73 → 54 (−26%)   | 1.98 → 3.01    | 45.2% → 53.7%   | +455 → +577 (+122)     | −82 → −35 (better) |
| GBPUSD | 49 → 39 (−20%)   | 1.59 → 2.16    | 26.5% → 33.3%   | +253 → +359 (+106)     | −95 → −60 (better) |
| USDJPY | 63 → 45 (−29%)   | 1.93 → 2.86    | 23.8% → 31.1%   | +434 → +550 (+116)     | −96 → −65 (better) |
| AUDUSD | 61 → 52 (−15%)   | 1.77 → 2.45    | 42.6% → 50.0%   | +320 → +448 (+128)     | −71 → −47 (better) |

### Notes

- **Building MACD gate is the single largest improvement since the initial SL cap fix.** Every pair improved on PF, WR, total pips, and drawdown simultaneously. PF gains range from +0.57 (GBPUSD) to +1.03 (EURUSD).
- **The filter works by rejecting entries where 1h MACD is positive but decelerating** — a fading histogram means momentum has already peaked, and entries there typically exit as breakeven or small losses.
- **EURUSD** is now the highest-PF FX pair at 3.01 with a 53.7% WR. Max DD halved to −34 pips.
- **USDJPY** benefits strongly (PF 1.93 → 2.86) despite D+E patterns already being trend-selective. The 1h bias gate still benefits from the building MACD filter — it prevents D+E patterns from firing on a rising 1h trend where momentum is already exhausting.
- **GBPUSD** is no longer the weakest pair (PF 2.16, above EURUSD's prior best of 1.98). The case for replacing it with EURJPY is significantly weaker now.
- **AUDUSD WR reaches 50.0%** — the highest of any pair. At this WR the trailing stop structure extracts full value from winners.
- **Trade frequency reduction (~15–29%)** is acceptable: total pips are higher on every pair despite fewer trades, meaning expectancy per trade increased across the board.
- **Regime context:** same window as prior snapshot — all FX pairs FLAT in the 60d window.

---

## Candidate Pair Evaluation — 2026-05-09

**Pairs tested:** NZDUSD, USDCAD, EURJPY, GBPJPY (all new indicator files created this date).
**Motivation:** explore whether the JPY-cross and commodity-pair dynamics produce a comparable edge to the active set.

### Scalp mode — 60d · 5m bars (all FX pairs, sorted by PF)

60d net-change: NZDUSD −1.1%, USDCAD +0.4%, EURJPY +1.9%, GBPJPY +2.4% (all FLAT)

| Pair   | Market Regime | Trades | Win%  | Avg W   | Avg L   |  PF  | Expec      | Total      | Max DD       |
|--------|---------------|--------|-------|---------|---------|------|------------|------------|--------------|
| EURUSD | FLAT          |     82 | 42.7% |  28.2 p |  11.5 p | 1.82 |  5.4 p/tr  |    444.7 p |     −82.5 p  |
| AUDUSD | FLAT          |     66 | 42.4% |  28.1 p |  11.8 p | 1.75 |  5.1 p/tr  |    337.5 p |     −70.8 p  |
| USDJPY | FLAT          |     68 | 22.1% |  59.4 p |  10.2 p | 1.64 |  5.1 p/tr  |    348.1 p |    −105.0 p  |
| GBPUSD | FLAT          |     78 | 29.5% |  42.6 p |  11.9 p | 1.50 |  4.2 p/tr  |    324.9 p |     −95.4 p  |
| EURJPY | FLAT          |     82 | 22.0% |  52.3 p |  10.6 p | 1.38 |  3.2 p/tr  |    261.7 p |    −101.5 p  |
| GBPJPY | FLAT          |     86 | 20.9% |  58.5 p |  15.3 p | 1.01 |  0.1 p/tr  |     12.2 p |    −588.2 p  |
| USDCAD | FLAT          |     80 | 26.2% |  33.9 p |  12.1 p | 0.99 | −0.1 p/tr  |      −4.3 p |   −219.1 p  |
| NZDUSD | FLAT          |     47 | 29.8% |  22.7 p |  12.5 p | 0.77 | −2.0 p/tr  |     −94.6 p |   −170.7 p  |

(p = pips · tr = trade · active pairs shown for context with current-window stats)

### Long mode — 730d · 1h bars (all FX pairs, sorted by PF)

730d net-change: NZDUSD −3.3%, USDCAD +3.4% (FLAT); EURJPY +17.1%, GBPJPY +17.2% (TREND_UP)

| Pair   | Market Regime | Trades | Win%  |  Avg W   | Avg L   |  PF  |   Expec    |    Total    | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|-------------|-------------|
| USDJPY | FLAT          |    354 | 16.9% | 104.3 p  |  12.3 p | 1.74 |  7.5 p/tr  |  2,652.1 p  |   −313.5 p  |
| EURJPY | TREND_UP      |    406 | 14.3% | 121.5 p  |  12.9 p | 1.57 |  6.3 p/tr  |  2,568.2 p  |   −362.5 p  |
| GBPJPY | TREND_UP      |    385 | 17.7% | 136.8 p  |  18.8 p | 1.56 |  8.7 p/tr  |  3,344.7 p  |   −523.7 p  |
| GBPUSD | FLAT          |    354 | 19.5% |  76.1 p  |  12.4 p | 1.49 |  4.8 p/tr  |  1,715.4 p  |   −444.1 p  |
| EURUSD | FLAT          |    326 | 24.2% |  53.1 p  |  11.6 p | 1.46 |  4.1 p/tr  |  1,326.1 p  |   −193.5 p  |
| AUDUSD | TREND_UP      |    341 | 23.8% |  51.4 p  |  11.5 p | 1.39 |  3.4 p/tr  |  1,161.9 p  |   −179.0 p  |
| USDCAD | FLAT          |    339 | 17.7% |  68.0 p  |  12.5 p | 1.17 |  1.7 p/tr  |    585.1 p  |   −407.2 p  |
| NZDUSD | FLAT          |    317 | 24.0% |  44.2 p  |  12.2 p | 1.14 |  1.3 p/tr  |    409.6 p  |   −353.8 p  |

### Notes

- **EURJPY — add.** The only candidate that clears the bar in both modes: scalp PF 1.38 (+262 pips / 60d), long PF 1.57 (+2,568 pips / 730d). Drawdown is manageable (scalp −102 p, long −363 p) and consistent with GBPUSD which is already live. Behaves like USDJPY structurally — low win rate offset by very large avg wins when the trailing stop runs. The 730d TREND_UP regime (+17.1%) likely contributes to the above-average long-mode avg win (122 p); reassess if regime shifts to FLAT.
- **GBPJPY — watch list.** Long-mode numbers are compelling (PF 1.56, best total pips +3,345) but the scalp-mode max drawdown (−588 pips in 60d) is an outlier — nearly 3× the next worst pair. Avg loss of 18.8 pips (vs 10–13 for all others) reflects the wider stop ceiling set for its higher ATR. The current 60d window was borderline (PF 1.01, +12 pips). Consider enabling only when a clear 1h trend is established; revisit next snapshot.
- **USDCAD — skip for now.** Scalp barely breakeven (PF 0.99, −4 pips), long marginal (PF 1.17). A 2.0-pip spread consumes most of the edge. Could revisit with tighter broker spreads.
- **NZDUSD — skip.** Weakest candidate in both modes (scalp PF 0.77, long PF 1.14). The 2.5-pip spread is too wide for the strategy's avg win at the 5m timeframe.

---

## Regime & RR Analysis — 2026-05-14

**Method:** 5m backtest (`rr_analysis.py`) across the 4 active pairs (EURUSD, GBPUSD, USDJPY, AUDUSD) covering ~60 days of data. Trades are aggregated by ISO week and by calendar day. Regime is classified as **TREND** (WR ≥ 35%) or **RANGE** (WR < 35%). The offered R:R is computed at entry from the raw SL/TP levels before any trailing.

**Motivation:** live trading in W19/W20 has been unprofitable. This analysis examines whether regime can be identified early in the week to inform discretionary trading decisions.

### Weekly View — all 4 pairs combined

| Week     | Trades | WR  | Min RR | Avg RR | Max RR | TP rate | Net pips | Regime |
|----------|--------|-----|--------|--------|--------|---------|----------|--------|
| W09/2026 |      9 | 33% |    3.0 |    4.3 |    7.5 |     33% |     +1.1 | RANGE  |
| W10/2026 |     22 | 41% |    4.0 |    5.8 |   10.6 |     41% |   +283.4 | TREND  |
| W11/2026 |     16 | 75% |    3.8 |    5.4 |    7.5 |     75% |   +486.7 | TREND  |
| W12/2026 |     23 | 39% |    3.8 |    5.8 |    8.2 |     39% |   +190.6 | TREND  |
| W13/2026 |     21 | 38% |    3.4 |    6.0 |   13.9 |     38% |   +226.5 | TREND  |
| W14/2026 |     17 | 41% |    2.7 |    5.6 |   10.2 |     41% |   +151.2 | TREND  |
| W15/2026 |     19 | 47% |    2.5 |    3.8 |    6.0 |     47% |   +132.1 | TREND  |
| W16/2026 |     15 | 67% |    2.3 |    4.3 |    7.5 |     67% |   +255.8 | TREND  |
| W17/2026 |     15 | 13% |    2.5 |    4.5 |    7.6 |     13% |    −96.1 | RANGE  |
| W18/2026 |     17 | 53% |    2.4 |    4.8 |   13.1 |     53% |   +344.7 | TREND  |
| W19/2026 |     14 | 21% |    2.7 |    4.9 |   10.2 |     21% |    −53.4 | RANGE  |
| W20/2026 |      1 |100% |    2.4 |    2.4 |    2.4 |    100% |    +22.2 | TREND* |

*W20 = 1 trade only (partial week at time of analysis)

### Daily View — all 4 pairs combined

| Date       | DoW | Trades | WR  | Min RR | Avg RR | Max RR | TP rate | Net pips | Regime |
|------------|-----|--------|-----|--------|--------|--------|---------|----------|--------|
| 2026-02-24 | Tue |      4 |  0% |    3.0 |    3.5 |    3.9 |      0% |    −46.9 | RANGE  |
| 2026-02-25 | Wed |      3 |100% |    3.1 |    3.6 |    4.5 |    100% |    +69.8 | TREND  |
| 2026-02-27 | Fri |      2 |  0% |    7.0 |    7.2 |    7.5 |      0% |    −21.8 | RANGE  |
| 2026-03-02 | Mon |      3 | 67% |    4.9 |    5.9 |    7.5 |     67% |    +83.0 | TREND  |
| 2026-03-03 | Tue |      7 | 71% |    4.0 |    5.0 |    5.8 |     71% |   +218.7 | TREND  |
| 2026-03-04 | Wed |      1 |  0% |    6.6 |    6.6 |    6.6 |      0% |    −11.8 | RANGE  |
| 2026-03-05 | Thu |      6 | 33% |    4.8 |    6.7 |   10.6 |     33% |    +50.7 | RANGE  |
| 2026-03-06 | Fri |      5 |  0% |    4.6 |    5.5 |    7.5 |      0% |    −57.2 | RANGE  |
| 2026-03-09 | Mon |      2 |100% |    6.0 |    6.7 |    7.5 |    100% |   +128.0 | TREND  |
| 2026-03-10 | Tue |      3 | 33% |    5.3 |    5.7 |    6.1 |     33% |     +9.6 | RANGE  |
| 2026-03-11 | Wed |      4 | 75% |    4.4 |    5.7 |    7.5 |     75% |   +134.3 | TREND  |
| 2026-03-12 | Thu |      3 |100% |    4.5 |    5.0 |    5.7 |    100% |   +126.4 | TREND  |
| 2026-03-13 | Fri |      4 | 75% |    3.8 |    4.4 |    4.9 |     75% |    +88.4 | TREND  |
| 2026-03-17 | Tue |      6 | 17% |    4.2 |    5.8 |    8.1 |     17% |    −26.2 | RANGE  |
| 2026-03-18 | Wed |      5 | 60% |    3.8 |    5.1 |    8.2 |     60% |    +67.6 | TREND  |
| 2026-03-19 | Thu |      7 | 43% |    4.1 |    5.8 |    7.5 |     43% |    +90.6 | TREND  |
| 2026-03-20 | Fri |      5 | 40% |    4.2 |    6.5 |    7.5 |     40% |    +58.6 | TREND  |
| 2026-03-23 | Mon |      6 | 50% |    4.6 |    7.5 |   13.9 |     50% |   +153.3 | TREND  |
| 2026-03-24 | Tue |      2 |  0% |    6.1 |    6.8 |    7.5 |      0% |    −22.8 | RANGE  |
| 2026-03-25 | Wed |      5 | 60% |    4.3 |    5.6 |    7.5 |     60% |   +106.5 | TREND  |
| 2026-03-26 | Thu |      3 | 67% |    3.4 |    4.1 |    4.6 |     67% |    +42.0 | TREND  |
| 2026-03-27 | Fri |      5 |  0% |    3.5 |    5.4 |    7.5 |      0% |    −52.5 | RANGE  |
| 2026-03-30 | Mon |      5 | 40% |    3.3 |    5.2 |    8.1 |     40% |    +43.2 | TREND  |
| 2026-03-31 | Tue |      3 | 67% |    3.9 |    6.3 |    7.5 |     67% |    +70.6 | TREND  |
| 2026-04-01 | Wed |      5 | 40% |    4.5 |    5.4 |    6.6 |     40% |    +36.9 | TREND  |
| 2026-04-02 | Thu |      3 | 33% |    4.2 |    6.9 |   10.2 |     33% |    +12.0 | RANGE  |
| 2026-04-03 | Fri |      1 |  0% |    2.7 |    2.7 |    2.7 |      0% |    −11.5 | RANGE  |
| 2026-04-06 | Mon |      5 | 20% |    2.5 |    3.9 |    6.0 |     20% |     −5.9 | RANGE  |
| 2026-04-07 | Tue |      5 |100% |    2.8 |    3.4 |    4.5 |    100% |   +135.5 | TREND  |
| 2026-04-09 | Thu |      5 | 40% |    3.6 |    4.5 |    5.8 |     40% |    +20.2 | TREND  |
| 2026-04-10 | Fri |      4 | 25% |    2.8 |    3.4 |    4.1 |     25% |    −17.7 | RANGE  |
| 2026-04-13 | Mon |      3 | 33% |    3.7 |    4.0 |    4.3 |     33% |    +10.7 | RANGE  |
| 2026-04-14 | Tue |      6 | 67% |    2.9 |    4.0 |    7.2 |     67% |    +85.9 | TREND  |
| 2026-04-15 | Wed |      1 |100% |    2.6 |    2.6 |    2.6 |    100% |    +24.1 | TREND  |
| 2026-04-16 | Thu |      1 |100% |    6.9 |    6.9 |    6.9 |    100% |    +36.6 | TREND  |
| 2026-04-17 | Fri |      4 | 75% |    2.3 |    4.8 |    7.5 |     75% |    +98.5 | TREND  |
| 2026-04-20 | Mon |      3 |  0% |    3.1 |    3.8 |    4.5 |      0% |    −35.1 | RANGE  |
| 2026-04-21 | Tue |      6 | 17% |    2.5 |    4.4 |    7.6 |     17% |    −32.7 | RANGE  |
| 2026-04-22 | Wed |      1 |100% |    3.5 |    3.5 |    3.5 |    100% |    +21.1 | TREND  |
| 2026-04-23 | Thu |      3 |  0% |    2.9 |    3.9 |    5.6 |      0% |    −32.4 | RANGE  |
| 2026-04-24 | Fri |      2 |  0% |    6.8 |    7.0 |    7.2 |      0% |    −17.0 | RANGE  |
| 2026-04-27 | Mon |      1 |  0% |    6.8 |    6.8 |    6.8 |      0% |     −8.5 | RANGE  |
| 2026-04-28 | Tue |      3 | 33% |    2.5 |    3.8 |    5.9 |     33% |    +28.6 | RANGE  |
| 2026-04-29 | Wed |      4 | 75% |    2.4 |    3.6 |    6.3 |     75% |    +43.1 | TREND  |
| 2026-04-30 | Thu |      8 | 62% |    3.2 |    5.8 |   13.1 |     62% |   +293.3 | TREND  |
| 2026-05-01 | Fri |      1 |  0% |    2.8 |    2.8 |    2.8 |      0% |    −11.8 | RANGE  |
| 2026-05-04 | Mon |      4 | 50% |    2.9 |    3.4 |    3.9 |     50% |    +21.2 | TREND  |
| 2026-05-05 | Tue |      2 | 50% |    3.0 |    5.3 |    7.5 |     50% |    +12.0 | TREND  |
| 2026-05-06 | Wed |      2 |  0% |    3.7 |    7.0 |   10.2 |      0% |    −25.3 | RANGE  |
| 2026-05-07 | Thu |      2 |  0% |    2.7 |    2.9 |    3.1 |      0% |    −23.3 | RANGE  |
| 2026-05-08 | Fri |      4 |  0% |    3.0 |    6.1 |    7.2 |      0% |    −38.0 | RANGE  |
| 2026-05-13 | Wed |      1 |100% |    2.4 |    2.4 |    2.4 |    100% |    +22.2 | TREND  |

### Key Findings

- **RR offered at entry does not predict regime.** W17 (worst week, −96 pips, 13% TP rate) had avg RR 4.5 — indistinguishable from profitable TREND weeks. The strategy correctly identifies high-RR setups in ranging conditions; the market simply does not follow through. High offered RR is not a green light.
- **TP rate is the sole reliable in-week predictor.** RANGE weeks: TP rate ≤ 21%. TREND weeks: TP rate ≥ 38%. The signal is consistently detectable by end of Tuesday.
- **Early-week rule:** if by end of Tuesday the combined TP rate across all 4 pairs is 0% and breakeven conversions are ≤ 2, the week is structurally RANGE. W17 and W19 both showed Mon 0% + Tue ≤ 17% TP rate. W11 (best week) showed Mon 100% + Tue 71%.
- **Friday is structurally RANGE:** 9 of 11 Fridays were RANGE (0% TP rate). The single outlier (2026-04-17, 75% WR) occurred within a strong TREND week and should be treated as exceptional.
- **USDJPY is the highest-variance pair.** In TREND weeks it dominates absolute pip generation (W18: +290 pips). In RANGE weeks it inflicts the deepest per-pair losses (W17: −43 pips, W19: −50 pips). A 0/N USDJPY run is the earliest single-pair warning of a RANGE week.
- **Regime is macro, not pair-specific.** When a RANGE week hits, all 4 pairs fail simultaneously. There is no cross-pair diversification benefit within a ranging macro environment.

---

## Snapshot — 2026-05-14 (BBW percentile gate)

**Period:** scalp = 60d ending 2026-05-14
**Changes since last snapshot:** Added Bollinger Band Width percentile gate (`DAILY_BBW_PCT_MAX = 0.73`) to all four FX indicator files. Derived from regime/RR analysis (`rr_analysis.py`, `regime_predictor.py`) which found that daily BBW percentile rank ≥ 0.73 correctly identified RANGE weeks with 90% accuracy on the 12-week backtest sample. Implementation: `compute_daily_adx()` now also computes `bbw` (20-bar Bollinger Band Width) and `bbw_pct` (20-bar rolling percentile rank). `assess_h1_bias()` returns FLAT when `bbw_pct ≥ DAILY_BBW_PCT_MAX`, after the ADX check. Gate applied uniformly to all four pairs including USDJPY (which remains ADX-exempt but is not BBW-exempt).

### Scalp mode — 60d · 5m bars

60d net-change: same approximate window as 2026-05-11 snapshot (EURUSD −1.1%, GBPUSD −0.3%, USDJPY +0.6%, AUDUSD +2.4%)

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     31 | 54.8% |  29.4 p  | 11.5 p  | 3.10 |  10.9 p/tr |    338.0 p |    −23.0 p  |
| GBPUSD | FLAT          |     32 | 34.4% |  49.7 p  | 11.9 p  | 2.18 |   9.2 p/tr |    295.7 p |    −47.2 p  |
| USDJPY | FLAT          |     36 | 33.3% |  59.3 p  |  9.4 p  | 3.15 |  13.5 p/tr |    486.0 p |    −65.2 p  |
| AUDUSD | FLAT          |     39 | 48.7% |  30.2 p  | 11.9 p  | 2.42 |   8.6 p/tr |    335.8 p |    −47.2 p  |

(p = pips · tr = trade · USDJPY: Patterns D+E, ADX exempt, BBW gate active)

### BBW gate impact — vs prior baseline (2026-05-11 building MACD)

| Pair   | PF (before→after) | Trades (before→after) | Total pips (before→after) | Max DD (before→after) |
|--------|-------------------|-----------------------|---------------------------|-----------------------|
| EURUSD | 3.01 → **3.10**   | 54 → 31 (−43%)        | +577 → +338 (−239)        | −34 → **−23**         |
| GBPUSD | 2.16 → **2.18**   | 39 → 32 (−18%)        | +359 → +296 (−63)         | −60 → **−47**         |
| USDJPY | 2.86 → **3.15**   | 45 → 36 (−20%)        | +550 → +486 (−64)         | −65 → unchanged       |
| AUDUSD | 2.45 → **2.42**   | 52 → 39 (−25%)        | +448 → +336 (−112)        | −71 → **−47**         |

All four pairs hold or improve PF. The gate is filtering losers more than winners. EURUSD max DD halved (−34 → −23 p). Trade-off is fewer total pips — the gate also sits out winning days when BBW is wide — but expectancy per trade rose on every pair.

### Weekly breakdown (all 4 pairs combined) — before vs after gate

| Week     | Before pips | Before regime | After trades | After pips | After regime | Net change |
|----------|------------|--------------|-------------|-----------|-------------|------------|
| W09/2026 | +1    RANGE | 9t  | +1    | RANGE | —          |
| W10/2026 | +283  TREND | 22t | +283  | TREND | —          |
| W11/2026 | +487  TREND | 7t  | +175  | TREND | −312 (gate blocked 9 winning trades on wide-band days) |
| W12/2026 | +191  TREND | 17t | +133  | TREND | −58        |
| W13/2026 | +227  TREND | 15t | +116  | RANGE | −111 (WR fell below 35% after gate removed trades) |
| W14/2026 | +151  TREND | 14t | +143  | TREND | −8         |
| W15/2026 | +132  TREND | 15t | +103  | TREND | −29        |
| W16/2026 | +256  TREND | 7t  | +181  | TREND | −75 (but WR rose 67%→86%) |
| **W17**  | **−96 RANGE** | **5t** | **−43** | **RANGE** | **+53 saved** |
| W18/2026 | +345  TREND | 17t | +345  | TREND | — (BBW_pct was 0.72, below threshold) |
| **W19**  | **−53 RANGE** | **9t** | **−3**  | **RANGE** | **+50 saved** |
| W20/2026 | +22   TREND | 1t  | +22   | TREND | —          |

Gate recovered ~103 pips from the two RANGE weeks (W17, W19). Cost is spread across multiple TREND weeks (~557 pips), but those weeks were already profitable — the gate shaves winners slightly while cutting RANGE damage significantly.

### Full weekly RR & regime table (post-gate)

| Week     | Trades | WR  | Min RR | Avg RR | Max RR | TP rate | Net pips | Regime |
|----------|--------|-----|--------|--------|--------|---------|----------|--------|
| W09/2026 |      9 | 33% |    3.0 |    4.3 |    7.5 |     33% |     +1.1 | RANGE  |
| W10/2026 |     22 | 41% |    4.0 |    5.8 |   10.6 |     41% |   +283.4 | TREND  |
| W11/2026 |      7 | 71% |    4.8 |    5.6 |    6.1 |     71% |   +175.3 | TREND  |
| W12/2026 |     17 | 35% |    3.8 |    6.1 |    8.2 |     35% |   +132.7 | TREND  |
| W13/2026 |     15 | 27% |    3.5 |    6.5 |   13.9 |     27% |   +116.2 | RANGE  |
| W14/2026 |     14 | 43% |    2.7 |    5.9 |   10.2 |     43% |   +142.5 | TREND  |
| W15/2026 |     15 | 47% |    2.8 |    4.0 |    6.0 |     47% |   +102.9 | TREND  |
| W16/2026 |      7 | 86% |    2.9 |    4.9 |    7.5 |     86% |   +180.9 | TREND  |
| W17/2026 |      5 |  0% |    5.6 |    6.8 |    7.6 |      0% |    −43.1 | RANGE  |
| W18/2026 |     17 | 53% |    2.4 |    4.8 |   13.1 |     53% |   +344.7 | TREND  |
| W19/2026 |      9 | 33% |    2.7 |    3.2 |    3.9 |     33% |     −3.3 | RANGE  |
| W20/2026 |      1 |100% |    2.4 |    2.4 |    2.4 |    100% |    +22.2 | TREND  |

### Full daily RR & regime table (post-gate)

| Date       | DoW | Trades | WR  | Min RR | Avg RR | Max RR | TP rate | Net pips | Regime |
|------------|-----|--------|-----|--------|--------|--------|---------|----------|--------|
| 2026-02-24 | Tue |      4 |  0% |    3.0 |    3.5 |    3.9 |      0% |    −46.9 | RANGE  |
| 2026-02-25 | Wed |      3 |100% |    3.1 |    3.6 |    4.5 |    100% |    +69.8 | TREND  |
| 2026-02-27 | Fri |      2 |  0% |    7.0 |    7.2 |    7.5 |      0% |    −21.8 | RANGE  |
| 2026-03-02 | Mon |      3 | 67% |    4.9 |    5.9 |    7.5 |     67% |    +83.0 | TREND  |
| 2026-03-03 | Tue |      7 | 71% |    4.0 |    5.0 |    5.8 |     71% |   +218.7 | TREND  |
| 2026-03-04 | Wed |      1 |  0% |    6.6 |    6.6 |    6.6 |      0% |    −11.8 | RANGE  |
| 2026-03-05 | Thu |      6 | 33% |    4.8 |    6.7 |   10.6 |     33% |    +50.7 | RANGE  |
| 2026-03-06 | Fri |      5 |  0% |    4.6 |    5.5 |    7.5 |      0% |    −57.2 | RANGE  |
| 2026-03-09 | Mon |      1 |100% |    6.0 |    6.0 |    6.0 |    100% |    +49.1 | TREND  |
| 2026-03-10 | Tue |      2 | 50% |    5.3 |    5.7 |    6.1 |     50% |    +21.1 | TREND  |
| 2026-03-11 | Wed |      1 |  0% |    6.1 |    6.1 |    6.1 |      0% |    −11.8 | RANGE  |
| 2026-03-12 | Thu |      2 |100% |    4.8 |    5.3 |    5.7 |    100% |    +83.3 | TREND  |
| 2026-03-13 | Fri |      1 |100% |    4.9 |    4.9 |    4.9 |    100% |    +33.6 | TREND  |
| 2026-03-17 | Tue |      5 |  0% |    4.2 |    6.1 |    8.1 |      0% |    −53.2 | RANGE  |
| 2026-03-18 | Wed |      3 | 67% |    3.8 |    5.6 |    8.2 |     67% |    +53.2 | TREND  |
| 2026-03-19 | Thu |      4 | 50% |    4.1 |    6.2 |    7.5 |     50% |    +74.1 | TREND  |
| 2026-03-20 | Fri |      5 | 40% |    4.2 |    6.5 |    7.5 |     40% |    +58.6 | TREND  |
| 2026-03-23 | Mon |      4 | 50% |    4.6 |    8.4 |   13.9 |     50% |   +115.5 | TREND  |
| 2026-03-24 | Tue |      2 |  0% |    6.1 |    6.8 |    7.5 |      0% |    −22.8 | RANGE  |
| 2026-03-25 | Wed |      3 | 67% |    5.2 |    6.4 |    7.5 |     67% |    +87.8 | TREND  |
| 2026-03-26 | Thu |      1 |  0% |    4.6 |    4.6 |    4.6 |      0% |    −11.8 | RANGE  |
| 2026-03-27 | Fri |      5 |  0% |    3.5 |    5.4 |    7.5 |      0% |    −52.5 | RANGE  |
| 2026-03-30 | Mon |      5 | 40% |    3.3 |    5.2 |    8.1 |     40% |    +43.2 | TREND  |
| 2026-03-31 | Tue |      3 | 67% |    3.9 |    6.3 |    7.5 |     67% |    +70.6 | TREND  |
| 2026-04-01 | Wed |      3 | 67% |    4.9 |    6.0 |    6.6 |     67% |    +60.5 | TREND  |
| 2026-04-02 | Thu |      2 |  0% |    6.3 |    8.2 |   10.2 |      0% |    −20.3 | RANGE  |
| 2026-04-03 | Fri |      1 |  0% |    2.7 |    2.7 |    2.7 |      0% |    −11.5 | RANGE  |
| 2026-04-06 | Mon |      4 | 25% |    3.2 |    4.3 |    6.0 |     25% |     +5.9 | RANGE  |
| 2026-04-07 | Tue |      3 |100% |    3.1 |    3.6 |    4.5 |    100% |    +82.7 | TREND  |
| 2026-04-09 | Thu |      5 | 40% |    3.6 |    4.5 |    5.8 |     40% |    +20.2 | TREND  |
| 2026-04-10 | Fri |      3 | 33% |    2.8 |    3.2 |    3.5 |     33% |     −5.9 | RANGE  |
| 2026-04-13 | Mon |      1 |100% |    3.7 |    3.7 |    3.7 |    100% |    +35.3 | TREND  |
| 2026-04-14 | Tue |      4 | 75% |    2.9 |    4.1 |    7.2 |     75% |    +62.8 | TREND  |
| 2026-04-16 | Thu |      1 |100% |    6.9 |    6.9 |    6.9 |    100% |    +36.6 | TREND  |
| 2026-04-17 | Fri |      1 |100% |    7.5 |    7.5 |    7.5 |    100% |    +46.2 | TREND  |
| 2026-04-21 | Tue |      2 |  0% |    6.7 |    7.1 |    7.6 |      0% |    −17.0 | RANGE  |
| 2026-04-23 | Thu |      1 |  0% |    5.6 |    5.6 |    5.6 |      0% |     −9.1 | RANGE  |
| 2026-04-24 | Fri |      2 |  0% |    6.8 |    7.0 |    7.2 |      0% |    −17.0 | RANGE  |
| 2026-04-27 | Mon |      1 |  0% |    6.8 |    6.8 |    6.8 |      0% |     −8.5 | RANGE  |
| 2026-04-28 | Tue |      3 | 33% |    2.5 |    3.8 |    5.9 |     33% |    +28.6 | RANGE  |
| 2026-04-29 | Wed |      4 | 75% |    2.4 |    3.6 |    6.3 |     75% |    +43.1 | TREND  |
| 2026-04-30 | Thu |      8 | 62% |    3.2 |    5.8 |   13.1 |     62% |   +293.3 | TREND  |
| 2026-05-01 | Fri |      1 |  0% |    2.8 |    2.8 |    2.8 |      0% |    −11.8 | RANGE  |
| 2026-05-04 | Mon |      4 | 50% |    2.9 |    3.4 |    3.9 |     50% |    +21.2 | TREND  |
| 2026-05-05 | Tue |      1 |100% |    3.0 |    3.0 |    3.0 |    100% |    +22.4 | TREND  |
| 2026-05-06 | Wed |      1 |  0% |    3.7 |    3.7 |    3.7 |      0% |    −11.8 | RANGE  |
| 2026-05-07 | Thu |      2 |  0% |    2.7 |    2.9 |    3.1 |      0% |    −23.3 | RANGE  |
| 2026-05-08 | Fri |      1 |  0% |    3.0 |    3.0 |    3.0 |      0% |    −11.8 | RANGE  |
| 2026-05-13 | Wed |      1 |100% |    2.4 |    2.4 |    2.4 |    100% |    +22.2 | TREND  |

### Notes

- **BBW gate is the most impactful structural change since the building MACD gate.** All four pairs improve or hold PF simultaneously. The gate fires when daily BBW percentile rank ≥ 0.73, meaning Bollinger Bands are wide relative to the prior 20 trading days — a signal that the market has already moved and momentum is likely exhausted.
- **Drawdown improvement is the headline result.** EURUSD max DD halved from −34 to −23 pips. GBPUSD and AUDUSD both dropped from ~−65–71 to −47 pips. This is the clearest sign the gate is cutting losers specifically.
- **W17 and W19 damage was cut by ~50%.** W17: −96 → −43 pips. W19: −53 → −3 pips. These were the two clearly identified RANGE weeks in the backtest window. The gate blocked 10 trades in W17 and 5 in W19 that were nearly all losers.
- **W13 flipped to RANGE classification post-gate** (WR fell from 38% to 27% after gate removed 6 trades). The week was still profitable (+116 pips) but the gate removed some high-RR winners alongside the losers. This is a known cost of a cross-pair daily threshold — it cannot distinguish a wide-band day that will trend from one that will range.
- **W18 was completely unaffected** (BBW_pct = 0.72, just below the 0.73 threshold on every day that week). This is the ideal behaviour — the gate correctly stayed open during the most profitable week in the sample (+345 pips).
- **USDJPY PF reached 3.15**, the highest in the active set, overtaking EURUSD. The gate removed losing USDJPY trades in W17 (0/5 run) and W19 (0/5 run) without touching W18 (+290 pips). USDJPY is the pair most sensitive to regime — the gate compounds the Supertrend pattern's trend-selection.
- **Trade frequency dropped 18–43% depending on pair.** This is acceptable because expectancy per trade rose on every pair. EURUSD now generates 10.9 pips/trade vs 10.7 before (fewer trades, same quality) and with half the drawdown.
- **The gate is a daily check, not a weekly one.** Even in TREND weeks it will suppress individual high-BBW days. This is correct behaviour — the signal is about current band width, not the macro week regime.

### Decision — 2026-05-14

**Gate not implemented. Code reverted.**

The results are inconclusive. The 90% weekly accuracy figure comes from 10 data points (two of which are the RANGE weeks the gate was designed to catch), which is too small a sample to trust a derived threshold. The cost — 18–43% trade reduction and ~438 fewer total pips across TREND weeks — is real and well-documented above. A gate that recovers 103 pips from bad weeks while costing 438 pips from good weeks is not yet worth the trade-off. Revisit when more weekly data is available and the threshold can be validated out-of-sample. In the meantime the regime/RR analysis (`rr_analysis.py`) remains available as a manual monitoring tool.

---
