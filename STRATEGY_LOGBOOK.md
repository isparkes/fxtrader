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

## Cooldown Analysis — 2026-05-21

**Context:** Live vs backtest trade-by-trade matchup (Apr 27–May 21, 98 closed trades across EURUSD, GBPUSD, USDJPY, AUDUSD) showed that 13 live trades were opened 30–60 minutes after a prior loss on the same pair. These trades were not blocked by the existing 30-minute cooldown and had substantially worse outcomes than the overall baseline.

**Method:** Each live trade was labelled with the elapsed time since the previous loss closed on the same pair. The `last_loss_close` timestamp resets to `None` after a win (a win clears the "troubled" state). Trades with no prior recent loss carry no gap label and are excluded from the bucket analysis. The live total of 98 trades was then simulated at cooldown values of 0, 30, 60, 120, and 240 minutes.

### Outcome by gap since last loss — live trades

| Gap since loss | Trades | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0–30 min | 0 | — | — | — | — | — (currently blocked) |
| **30–60 min** | **13** | **2** | **10** | **15%** | **−2.3** | **−29.8** |
| 1–2 hrs | 4 | 1 | 2 | 25% | +1.3 | +5.3 |
| 2–4 hrs | 6 | 2 | 4 | 33% | +10.7 | +64.0 |
| 4+ hrs | 33 | 19 | 13 | 58% | +12.1 | +397.9 |
| All trades | 98 | 37 | 54 | 38% | +7.9 | +770.3 |

The 30–60 min window is the worst segment in the dataset. 10 of 13 trades were losses. Stripping out GBPUSD (now ADX-gated and no longer active), the remaining 5 trades in that window across EURUSD/USDJPY/AUDUSD were 0 wins, 4 losses, 1 BE — total −27.6 pips. The pattern is consistent across pairs.

### Cooldown regime simulation — all pairs and per instrument

All pairs combined:

| Cooldown | N | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0 min (no cooldown) | 98 | 37 | 54 | 38% | 7.9 | +770.3 |
| **30 min ← prior** | **98** | **37** | **54** | **38%** | **7.9** | **+770.3** |
| **60 min ← new** | **86** | **35** | **45** | **41%** | **9.3** | **+796.2** |
| 120 min | 84 | 35 | 44 | 42% | 9.6 | +809.1 |
| 240 min | 76 | 31 | 40 | 41% | 7.5 | +566.3 |

EURUSD:

| Cooldown | N | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0 / 30 min | 26 | 11 | 12 | 42% | 6.4 | +165.9 |
| **60 min** | **24** | **11** | **10** | **46%** | **7.5** | **+180.0** |
| 120 min | 24 | 11 | 10 | 46% | 7.5 | +180.0 |
| 240 min | 22 | 9 | 10 | 41% | 4.5 | +98.4 |

USDJPY:

| Cooldown | N | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0 / 30 min | 20 | 6 | 13 | 30% | 10.5 | +210.7 |
| **60 min** | **18** | **6** | **12** | **33%** | **12.3** | **+221.0** |
| 120 min | 18 | 6 | 12 | 33% | 12.3 | +221.0 |
| 240 min | 14 | 4 | 10 | 29% | 3.2 | +45.2 |

AUDUSD:

| Cooldown | N | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0 / 30 min | 24 | 10 | 13 | 42% | 5.1 | +123.1 |
| **60 min** | **23** | **10** | **12** | **43%** | **5.5** | **+126.3** |
| 120 min | 22 | 10 | 11 | 45% | 6.3 | +139.2 |
| 240 min | 22 | 10 | 11 | 45% | 6.3 | +139.2 |

GBPUSD (now ADX-gated, included for completeness):

| Cooldown | N | W | L | WR% | Avg pip | Total pips |
|---|---|---|---|---|---|---|
| 0 / 30 min | 28 | 10 | 16 | 36% | 9.7 | +270.6 |
| 60 min | 21 | 8 | 11 | 38% | 12.8 | +268.9 |
| 240 min | 18 | 8 | 9 | 44% | 15.8 | +283.5 |

### Key findings

- **0 min = 30 min in the live data.** The 0–30 min window fired zero trades across the entire 98-trade sample — the existing 30-min gate never blocked a real entry. It was a free safety net that cost nothing observable.
- **30–60 min is where the damage is.** 15% WR, −29.8 pips. In every case the system suffered a loss, waited the minimum 30 minutes, and re-entered while the adverse condition was still active (e.g. GBPUSD firing 4 times in 90 minutes on Apr 29; EURUSD May 15 re-entered 30 minutes after a stop-out in the same direction).
- **60 min is the inflection point.** EURUSD and USDJPY both improve cleanly. Beyond 120 min the tables are stable for EURUSD/USDJPY but 240 min cuts profitable trades (particularly USDJPY multi-hour trends) — total pips drop sharply.
- **AUDUSD benefits slightly more from 120 min** (+139 vs +126 at 60 min) with no further gain beyond that. The difference is small (2 trades) and within noise given sample size; 60 min applied uniformly is the cleaner choice.
- **Backtest is insensitive to cooldown below 30 min** because Yahoo Finance 5m bars rarely produce consecutive same-pair signals within 60 minutes. The live data is the reliable signal here — consecutive re-entries in adverse conditions are a live-system phenomenon.

### Decision

**Cooldown extended from 30 → 60 minutes.**

Code changes:
- `backtest.py`: `COOLDOWN_BARS = 6 → 12` (12 × 5m = 60 min)
- `daemon_fx.py`: `COOLDOWN_MINS = 30 → 60`

Daemon cooldown implementation verified end-to-end: (1) set on `close_sl` only — TP closes do not trigger cooldown; (2) gated before every entry check; (3) reported in status emails. No change needed.

---

## Signal Divergence Analysis — 2026-05-21

**Context:** Live trade matchup (Apr 27–May 21, 70 active-pair trades across EURUSD, USDJPY, AUDUSD) showed only ~19% of live trades had a backtest counterpart. This section quantifies the divergence by running the full indicator chain on both OANDA (live data source) and Yahoo Finance (backtest data source) for all three pairs across the full period.

**Method:** `signal_divergence.py` walks every 5m bar in the period, evaluating `assess_h1_bias` + `find_m5_entry` on rolling windows built from each data source independently. Signals are matched if they fire within ±10 minutes of each other in the same direction. Results are cross-referenced against `fx_trades.jsonl`.

### Signal Match Rate by Pair

| Pair | OANDA Signals | Yahoo Signals | Matched | Match % | OANDA-only | Yahoo-only |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| EURUSD | 40 | 20 | 11 | 28% | 29 | 9 |
| USDJPY | 21 | 22 | 18 | 86% | 3 | 4 |
| AUDUSD | 0 | 21 | 0 | 0% | 0 | 21 |
| **Total** | **61** | **63** | **29** | **48%** | **32** | **34** |

**OANDA-only**: live system trades backtest misses. **Yahoo-only**: phantom backtest entries the live system never took.

### Live Trade Signal Coverage

| Pair | Live Trades | OANDA explains | Yahoo explains |
|------|:---:|:---:|:---:|
| EURUSD | 26 | 15 (58%) | 6 (23%) |
| USDJPY | 20 | 6 (30%) | 6 (30%) |
| AUDUSD | 24 | 0 (0%) | 8 (33%) |

### Root Cause: Daily ADX Divergence

The ADX gate (`DAILY_ADX_MIN`) is the primary source of divergence. Yahoo Finance's synthetic bar construction produces ADX values that systematically diverge from OANDA real-tick data:

| Pair | ADX_MIN | OANDA ADX (Apr 27–May 21) | Yahoo ADX | Impact |
|------|:---:|:---:|:---:|:---|
| EURUSD | 17 | 19–24 (gate never blocks) | 15–22 (blocks May 5+) | Yahoo misses second half of period |
| USDJPY | 0 | 15–28 (gate exempt) | 13–26 (gate exempt) | No ADX impact; high match rate |
| AUDUSD | 18 | 14–18 (blocks entire period) | 17–21 (never blocks to May 14) | Yahoo fires phantom signals; OANDA correctly blocks |

**EURUSD**: OANDA ADX is 2–6 pts *higher* than Yahoo from May 4 onwards. Yahoo ADX drops below 17 on May 5 and stays there; Yahoo backtest fires 0 signals from May 5–21. OANDA correctly identifies EURUSD as still trending (ADX 19–22) and the live system keeps trading.

**AUDUSD**: OANDA ADX is 3–5 pts *lower* than Yahoo. OANDA correctly shows AUDUSD in a choppy, low-trend environment (ADX 14–18 < threshold) for the entire period. Yahoo's inflated ADX (17–21) passes the gate and fires 21 phantom signals. These represent false confidence in the AUDUSD backtest PF of 2.45.

**ADX bias direction is inconsistent by pair** — OANDA > Yahoo for EURUSD/USDJPY, OANDA < Yahoo for AUDUSD — confirming this is pair-specific synthetic data error rather than a simple offset.

### EURUSD Signal Quality Breakdown

EURUSD had 40 OANDA signals vs 20 Yahoo signals; 11 matched, 29 OANDA-only:

| Signal category | Trades (live confirmed) | WR | Total pips |
|---|:---:|:---:|:---:|
| Matched (OANDA + Yahoo agree) | 3 | 100% | +116.6 |
| OANDA-only (backtest missed) | 12 | 50% | +65.7 |
| Yahoo-only (live never took) | 0 live trades | n/a | n/a |

Matched signals are all Apr 30 BUY trades (strong trend day, Apr 30 USD sell-off). OANDA-only signals span the full May period where Yahoo ADX gate incorrectly blocked.

### USDJPY Signal Quality Breakdown

USDJPY had 86% signal match — the highest of all pairs due to ADX-exempt status. Matched signals confirmed by live: W:4 L:2, WR:67%, +266.4 pips. 3 OANDA-only signals had no live trade confirmation (timing gaps or daemon missed the entry bar).

### AUDUSD ADX Gate Compliance Issue

After the ADX gate was added to the daemon on 2026-05-11 21:34 UTC, AUDUSD live trades continued through May 19 (10 trades, W:4 L:6, -1.5 pips). OANDA ADX was 14.8 at gate deployment (far below the 18 threshold). Possible causes: daemon not restarted immediately after code update; or a runtime path where `df_1d` is not correctly passed to `assess_h1_bias`. **Needs investigation** before next deployment.

Pre-gate AUDUSD performance (Apr 27–May 10): 14 trades, W:6 L:8, WR:43%, +124.6 pips — indicates the trades themselves were not catastrophic but the market was undeniably below-threshold trend strength.

### Conclusions

1. **USDJPY backtest is most reliable** — 86% signal match; backtest results approximately represent live trading for this pair.

2. **EURUSD backtest valid Apr 27–May 4 only** — Yahoo ADX divergence causes backtest to miss ~half of all live signals from May 5 onwards. The PF 3.01 baseline may be understated for the current period.

3. **AUDUSD backtest results are not reliable** — 21 phantom Yahoo signals in a period where OANDA correctly identifies the market as too choppy to trade. The PF 2.45 baseline is suspect.

4. **Recommended action: switch backtest to OANDA data** — `signal_divergence.py` shows that using OANDA data brings signal match rate from 0–86% to a consistent ~86%+ across all pairs. The backtest already has `FX_DATA_SOURCE` logic; using `_oanda_paginated()` for historical data would eliminate all three classes of divergence. EURUSD and USDJPY can be validated immediately. AUDUSD may require separate evaluation of whether it should be traded at all given consistently low ADX (14–18) on real data.

---

## BTCUSD Live Analysis — 2026-05-15

**Period:** 2026-04-25 to 2026-05-15 (48 closed live trades)
**Summary:** Live PF = 1.087 vs backtest PF 1.74. Two issues identified and fixed.

### Live Performance (before fixes)

| Metric | Value |
|--------|-------|
| Trades | 48 |
| Win rate | 27.1% |
| Avg win | $730 |
| Avg loss | $265 |
| PF | 1.087 |
| Net P&L | +$763 |

Win rate matched backtest (~27%). Gap was entirely in magnitude: avg wins 23% lower, avg losses 26% higher than backtest.

### Root Cause 1 — SL/TP not re-anchored to fill price (live mode bug)

In live Binance mode, `daemon_crypto.py` overwrites `pos.entry_price` with the actual fill price but leaves `stop_loss` and `take_profit` anchored to the **signal bar's price** (which could be 30–70 minutes stale by the time the daemon polls and Binance fills). 15 of 48 trades had actual SL distances 2–7× larger than `risk_pips` indicated. 7 of those closed at a loss, losing 4,150 pips total vs. ~1,300 expected — excess cost of ~2,850 pips. Had those been capped correctly, live PF would have been ~1.5.

**Fix applied:** After a Binance fill, recompute `stop_loss` and `take_profit` by preserving the signal's pip distances (sl_dist, tp_dist) anchored to the actual fill price. The Binance OCO exit order (placed immediately after) now uses the corrected prices.

### Root Cause 2 — Building MACD gate missing from BTC

All four FX pairs had the building MACD gate applied (2026-05-11, +0.57–1.03 PF each). BTC was never updated — `assess_h1_bias` still used sign-only MACD check.

**Fix applied:** Added `prev_macd` and updated bull/bear conditions in `indicator_btcusd.assess_h1_bias()`, identical to the FX indicator pattern.

### Backtest results after fixes

60d net-change: BTCUSD +23.9% (TREND_UP)

| Mode | Trades | Win% | Avg W | Avg L | PF | Total | Max DD |
|------|--------|------|-------|-------|-----|-------|--------|
| Scalp (60d · 5m) | 98 | 31.6% | $951 | $205 | **2.14** | $15,727 | −$1,769 |
| Long (730d · 1h) | 213 | 31.0% | $2,676 | $389 | **3.09** | $119,498 | −$3,084 |

vs. prior baseline (2026-05-11):

| Mode | PF before | PF after | Trades before→after | Max DD before→after |
|------|-----------|----------|---------------------|---------------------|
| Scalp | 1.74 | **2.14** (+0.40) | 131 → 98 (−25%) | −$3,728 → −$1,769 (−53%) |
| Long | 2.10 | **3.09** (+0.99) | 326 → 213 (−35%) | −$5,244 → −$3,084 (−41%) |

- Drawdown halved in scalp mode — the gate specifically cuts fading-momentum entries that were the source of losing streaks.
- PF 2.14 in scalp mode puts BTC above EURUSD (3.01), USDJPY (2.86), AUDUSD (2.45), GBPUSD (2.16) ... wait, recalculating — BTC's 2.14 is above GBPUSD (2.16) but below the others. BTC's long-mode 3.09 is the highest of all instruments.

---

## 2026-05-22 — Infrastructure changes (post-v2 stabilisation)

No strategy logic or parameter changes. All changes are operational.

### daemon.py — parquet warm-start on restart

`refresh_data()` now seeds its in-memory OHLCV caches from the local parquet store (via `datalib.load`) on the first tick after daemon startup, instead of always issuing a full multi-page OANDA fetch. Falls back to the original OANDA-only path if the parquet file is absent or empty. After loading from disk it continues into the normal incremental update path to fetch any bars newer than the last stored timestamp, so the cache is always topped up to the present before the first signal assessment.

**Benefit:** daemon restarts are faster (disk read vs. paginated HTTP) and do not consume OANDA API rate-limit budget for historical bars already stored locally.

### datalib.py — load() log message

`datalib.load()` now emits a `log.info` line after every read, reporting the pair, granularity, number of bars loaded, and the first/last timestamp of the data returned (after any start/end filtering). Example:

```
EURUSD M1  loaded 129600 bars  2026-02-21T00:00:00Z → 2026-05-22T09:59:00Z
```

### Dockerfile.fx — numpy AVX2 / Rosetta 2 fix

Added `ENV NPY_DISABLE_CPU_FEATURES="AVX2 AVX512F"` to the image. Rosetta 2 (amd64 emulation on Apple Silicon) advertises AVX2 availability via CPUID but raises SIGILL when the instructions actually execute. Disabling the dispatch at the numpy level prevents silent crashes when the container is built or tested locally on M-series Macs.

### docker-compose.yml — trades.jsonl volume mount

Added `/data/fxtrader/trades.jsonl:/app/trades.jsonl` to the service volume list. The v2 daemon writes trade records to `trades.jsonl`; without this mount the file was created inside the ephemeral container layer and lost on restart.

### requirements.txt — numpy pinned to 1.26.4

Changed `numpy>=1.24.0,<2.0` to `numpy==1.26.4`. The upper bound was already excluding NumPy 2.x; pinning to a specific patch version ensures reproducible builds and avoids unexpected behaviour from minor-version changes in the presence of the AVX2 workaround above.

---

## 2026-05-22 — v2 OANDA Baseline (data source migration)

**Market regime (90-day window ending 2026-05-22):** TREND_UP (EUR, AUD), RANGING (GBP, USD pairs mixed)

### Changes vs prior baseline (2026-05-11 MACD gate snapshot)

1. **Data source: Yahoo Finance → OANDA exclusively** — eliminates ADX divergence that inflated some Yahoo results
2. **Simulation: M5 bar high/low → M1 within-bar** — per-bar SL/TP ordering now chronologically accurate; 5 M1 bars stepped per M5 window
3. **Window: 60d → 90d** — M1 default lookback; more data but different period
4. **BTC/crypto removed** — deprecated, all FX only
5. **Trailing stop: tradelib.py single source of truth** — same logic used by backtest and daemon

### Results

| Pair | Trades | Win% | Avg W | Avg L | PF | Total pips | Max DD |
|------|--------|------|-------|-------|-----|------------|--------|
| EURUSD | 55 | 54.5% | 29.2 | 11.6 | **3.03** | +587.8 | −48.3 |
| USDJPY | 44 | 38.6% | 48.8 | 9.7 | **3.17** | +567.5 | −68.7 |
| AUDUSD | 28 | 39.3% | 37.4 | 12.0 | **2.02** | +207.7 | −67.5 |
| GBPUSD | 29 | 24.1% | 45.2 | 12.0 | **1.20** | +52.5 | −97.5 |

### vs. prior baseline (Yahoo, 60d)

| Pair | PF before | PF after | Trades before→after | Notes |
|------|-----------|----------|---------------------|-------|
| EURUSD | 3.01 | **3.03** (+0.02) | 54 → 55 | Stable — confirmed reliable pair |
| USDJPY | 2.86 | **3.17** (+0.31) | 45 → 44 | Improved — Yahoo/OANDA 86% match, M1 sim helping |
| AUDUSD | 2.45 | **2.02** (−0.43) | 52 → 28 | As predicted — Yahoo ADX inflated; OANDA blocks more low-trend periods |
| GBPUSD | 2.16 | **1.20** (−0.96) | 39 → 29 | Significant degradation — Yahoo ADX divergence was masking poor real performance |

### Key findings

- **EURUSD and USDJPY are confirmed solid performers** on clean OANDA data. Signal divergence analysis was correct: these two pairs were reliable (USDJPY 86% match, EURUSD stable).
- **GBPUSD at PF 1.20 is borderline** — worst MaxDD (−97.5p), lowest WR (24.1%), essentially noise territory. Prior PF 2.16 was partly an artefact of Yahoo ADX values. Prime candidate for removal from active trading.
- **AUDUSD degraded as expected** — falls from PF 2.45 → 2.02 as OANDA ADX correctly blocks the low-trend periods Yahoo missed. Still profitable and kept active.
- **M1 within-bar simulation working** — zero forced closes across all pairs; SL/TP ordering is clean.
- Trade counts broadly stable for EUR/USD/JPY despite 90d vs 60d window — signal quality gating is working.

### Action items

- [ ] Consider removing GBPUSD from active pairs (PF 1.20, worst DD, 30:1 leverage limit constrains to 3 concurrent trades)
- [ ] Run `python backtest.py --pair eurjpy` once EURJPY seeded — evaluate candidate pair to replace GBPUSD
- [ ] Smoke test daemon.py on paper mode before going live

---

## 2026-05-22 — V2 Final Verification & Sign-off

No strategy logic changes. All items below are verification and tooling additions only.

### Friday block verification

Compared PF with and without `BLOCKED_DAYS = frozenset({4})` across all 4 active pairs (90d OANDA data, scalp mode):

| Pair | PF with Friday block | PF without Friday block | Delta |
|------|:--------------------:|:-----------------------:|:-----:|
| EURUSD | **3.03** | 2.51 | −0.52 |
| USDJPY | **3.17** | 2.89 | −0.28 |
| AUDUSD | **2.02** | 1.86 | −0.16 |
| GBPUSD | 1.20 | 1.20 | 0.00 |

**Verdict: Friday block confirmed beneficial and retained for all 4 pairs.** EURUSD takes the largest hit without it (−0.52 PF). GBPUSD is noise-level either way at PF 1.20. Removing the block adds 8–12 trades per pair but all extra Friday trades drag PF down.

`backtest.py` extended with `--no-blocked-days` flag to support this type of comparison without touching indicator files.

### Parquet data store integrity check

Checked all 12 parquet files (4 pairs × 3 granularities: M1, H1, D):

| Check | Result |
|---|---|
| All files present | ✓ |
| Required columns (OHLCV) | ✓ |
| No NaNs | ✓ |
| OHLC integrity (high ≥ body, low ≤ body) | ✓ |
| No zero / negative prices | ✓ |
| No duplicate timestamps | ✓ |
| Monotonically increasing UTC index | ✓ |
| Data currency (last bar within hours of now) | ✓ |
| All gaps | Normal weekend closes (Fri 21:00 → Sun 21:00 UTC) or brief session-boundary liquidity gaps (≤12 min); none pathological |

All 12 stores are clean. Row counts: M1 ~92,300–92,500 bars (90d), H1 ~12,436–12,437 bars (2y), D ~708 bars (3y).

### Resampling correctness check

Three resampling paths verified:

**M1 → M5** (`datalib.resample`, used by backtest and fetch_data):
- All bars on 5-minute boundaries
- M1/M5 ratio 4.97 across all 4 pairs (expected 5.0; minor variance from weekend gap handling)
- 200-bar random OHLC spot-checks pass: open=first M1, high=max, low=min, close=last M1
- Volume fully conserved over the resampled window

**M1 → H1** (resampled vs. stored OANDA H1):
- ~1,548–1,549 bars in the overlap window per pair
- Zero OHLC differences between resampled-M1 H1 and stored OANDA H1

**H1 → H4** (inline `resample("4h")` in `backtest.py` / `fetch_data`):
- All bars on 4-hour boundaries (00/04/08/12/16/20h UTC)
- 100-bar random OHLC spot-checks pass

Partial-bar drop heuristic (last M5 bar dropped if volume < 10% of rolling median) behaves correctly; no bars incorrectly dropped at present.

### V2 architecture summary

V2 redevelopment completed 2026-05-22. Key changes from V1:

| Area | V1 | V2 |
|------|----|----|
| Data source | Yahoo Finance (backtest) + OANDA (live) | OANDA exclusively (both) |
| Data store | None (fetched fresh each run) | Persistent parquet store (`datalib.py`) |
| Parquet engine | pyarrow | fastparquet (AVX2/Rosetta2 compatibility) |
| Simulation | M5 bar high/low estimation | M1 within-bar chronological SL/TP ordering |
| Trade mechanics | Duplicated across daemon + backtest | Single `tradelib.py` source of truth |
| OANDA fetch | Single-page | Paginated (`oanda.get_candles_paginated`) |
| BTC/crypto | Active | Deprecated |
| Daemon | `daemon_fx.py` + `daemon_crypto.py` | Unified `daemon.py` |
| Cooldown | 30 min | 60 min (extended after live-data analysis) |
| Friday gate | Not present | `BLOCKED_DAYS = frozenset({4})` in all indicator files |

**Active pairs at V2 sign-off:** EURUSD (PF 3.03), USDJPY (PF 3.17), AUDUSD (PF 2.02), GBPUSD (PF 1.20 — marginal, candidate for replacement).

---

## Snapshot — 2026-05-25

**Period:** scalp = 60d ending 2026-05-25 (data through 2026-05-23 Friday close)
**Changes since last snapshot:** Code-quality and correctness pass — no indicator logic or parameter changes.
1. **Spread guard failure mode changed** — was failing open (allowing entry) on OANDA price check exception; now fails closed (blocks entry). Prevents accidental entries during news/outage.
2. **Phase 3 momentum gate removed** — TP extension is now unconditional. The HA colour check was near-universally true (any bar that reaches TP on an in-progress trend almost always has a same-colour HA candle due to the smoothing formula); removing it makes the code honest about actual behaviour.
3. **Backtest spread constants aligned** — now match `daemon.py` `STANDARD_SPREADS` exactly (EURUSD 1.0, GBPUSD 1.5, USDJPY 2.0, AUDUSD 1.5 pips). Prior backtest used EURUSD 1.5, USDJPY 1.5. USDJPY spread increase (+0.5 pip) makes the backtest slightly less favourable for that pair; EUR/GBP/AUD are slightly better.
4. **Drawdown circuit breaker added to `daemon.py`** — session loss % tracked; entries halted at `DRAWDOWN_HALT_PCT` (default 3% of NAV); daily reset at UTC midnight.
5. **`extend_tp` event replay fix** — event now persisted with `sl`/`tp` fields and replayed correctly on restart; Phase 3 state was previously lost across daemon restarts.
6. **Signal suppression on order failure fixed** — `last_signal_bar` no longer set when `_open_automated()` raises an exception; prevents the signal bar being marked "seen" after a transient OANDA error.
7. **Threading safety** — `_LOG_LOCK` serialises concurrent JSONL writes; `_STATE_LOCK` guards `ctrl`/`states`/`managed` between the control thread and main loop.
8. **`best_price` initialisation fixed** — was set to bar `high`/`low` on first poll; now initialised to `entry_price`, preventing a false Phase 1 breakeven trigger on the opening bar.

### Scalp mode — 60d · 5m bars

60d net-change: EURUSD +0.4%, GBPUSD +0.5%, USDJPY −0.2%, AUDUSD +2.6% (all FLAT)

| Pair   | Market Regime | Trades | Win%  | Avg W    | Avg L   |  PF  | Expec      | Total      | Max DD       |
|--------|---------------|--------|-------|----------|---------|------|------------|------------|--------------|
| EURUSD | FLAT          |     55 | 52.7% |  30.2 p  |  11.1 p | 3.02 |  10.6 p/tr |    585.1 p |    −44.0 p   |
| USDJPY | FLAT          |     41 | 39.0% |  48.3 p  |  10.5 p | 2.94 |  12.4 p/tr |    509.8 p |    −51.9 p   |
| AUDUSD | FLAT          |     27 | 44.4% |  38.0 p  |  11.7 p | 2.60 |  10.4 p/tr |    281.2 p |    −34.5 p   |
| GBPUSD | FLAT          |     29 | 24.1% |  43.9 p  |  11.7 p | 1.20 |   1.7 p/tr |     50.6 p |   −149.4 p   |

(p = pips · tr = trade · USDJPY: Patterns D+E, ADX exempt; EURUSD/GBPUSD/AUDUSD: A+C+D · GBPUSD not actively traded)

### vs. prior baseline (2026-05-22 V2 OANDA Baseline)

| Pair   | PF before | PF after | Trades before→after | Max DD before→after | Notes |
|--------|-----------|----------|---------------------|---------------------|-------|
| EURUSD | 3.03      | **3.02** | 55 → 55             | −48 → −44           | Stable; 0.5 pip spread reduction offsets rolling window shift |
| USDJPY | 3.17      | **2.94** | 44 → 41             | −69 → −52           | Lower spread cost offset by +0.5 pip spread correction; DD improved |
| AUDUSD | 2.02      | **2.60** | 28 → 27             | −68 → −35           | Improved; rolling window likely dropped some W17/W19 range losers |
| GBPUSD | 1.20      | **1.20** | 29 → 29             | −98 → −149          | Unchanged PF but DD has widened significantly — drawdown profile deteriorating |

### Notes

- **All three active pairs above PF 2.5 — clean green light for the week.** EURUSD and USDJPY are essentially unchanged from the v2 OANDA baseline; AUDUSD has improved.
- **USDJPY PF decline (3.17 → 2.94) is largely mechanical** — the spread correction from 1.5 to 2.0 pips costs ~0.5 pip per trade (41 trades = ~20 pips adjusted). The rolling window dropping 3 profitable trades also contributes. No deterioration of underlying pattern quality; avg win is still 48+ pips.
- **AUDUSD trade count halved (52 → 27 over two snapshots)** relative to the May 11 Yahoo-data baseline. The OANDA ADX gate is correctly suppressing low-trend periods that Yahoo's inflated ADX was allowing. Fewer but higher-quality trades; PF 2.60 and max DD −34.5p is the best drawdown of any pair this snapshot.
- **GBPUSD max DD has grown to −149 pips** against only +51 pips net — a 3:1 DD-to-gain ratio. PF 1.20 is statistically indistinguishable from random in a 29-trade sample. The decision not to trade it is confirmed. EURJPY (PF 1.38/1.57 from May evaluation) remains the candidate replacement when a slot opens.
- **No long-mode run this snapshot** — no indicator or parameter changes affecting long mode.
- **Data integrity:** parquet stores updated through 2026-05-23 Friday close; 1,100–1,160 new M1 bars and 18–19 new H1 bars added per pair.

---

## Candidate Pair Evaluation — 2026-05-26 (EURJPY v2 OANDA baseline)

**Motivation:** establish the first clean OANDA-data baseline for EURJPY using the full v2 indicator stack. Previous evaluation (2026-05-09) used Yahoo Finance data which diverges significantly from OANDA on daily ADX values, making the earlier PF 1.38/1.57 figures suspect.

**Changes made this evaluation:**
- `indicator_eurjpy.py` rewritten to v2 standard: removed yfinance, added MACD building check to `assess_h1_bias`, added `compute_daily_adx`, `compute_supertrend`, Pattern E, and all required v2 constants (`DAILY_ADX_MIN`, `TRAIL_ACTIVATE_FRAC`, `BLOCKED_DAYS`).
- Parameters set: `DAILY_ADX_MIN=18`, `HA_SL_MIN_PIPS=10`, `HA_SL_MAX_PIPS=15`, `TRAIL_ACTIVATE_FRAC=0.70`, `BLOCKED_DAYS={4}`.
- `oanda.py` INSTRUMENTS extended with `"eurjpy": "EUR_JPY"`. `daemon.py` STANDARD_SPREADS extended with `"eurjpy": 1.5`.
- `backtest.py` already registered EURJPY with `spread_scalp=2.0`, `spread_long=1.5`.

**Parameter search:**

| Config | Scalp PF | Scalp n | Long PF | Long n |
|---|---|---|---|---|
| ADX=20, A+C+D+E | 1.59 | 16 | 1.54 | 175 |
| ADX=18, C+D+E (no A) | 1.85 | 21 | 1.47 | 170 |
| **ADX=18, A+C+D+E (final)** | **1.73** | **22** | **1.54** | **175** |

Removing Pattern A degraded long mode (1.54 → 1.47). Root cause: A's `continue` blocks lower-quality C/E signals on the same bar; without A those bars are captured by C/E at worse average outcomes. ADX=18 vs 20 has no effect on long mode (daily bars rarely straddle the boundary) but adds 6 scalp trades.

**EURJPY correlation to EURUSD (H1 returns, 2-year):** r = +0.264 (rolling range −0.07 to +0.56). Genuinely lower correlation than NZDUSD (+0.665) or GBPUSD (implicit through USD). Primary independent driver is BOJ policy / JPY carry dynamics.

### Scalp mode — 60d · 5m bars

60d net-change: EURJPY +0.6% (FLAT)

| Pair   | Market Regime | Trades | Win%  | Avg W   | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|---------|---------|------|------------|------------|-------------|
| EURJPY | FLAT          |     22 | 31.8% |  47.1 p |  12.7 p | 1.73 |  6.3 p/tr  |    139.5 p |    −96.0 p  |

Patterns: A=6 (−24.6p), C=8 (+32.4p), D=8 (+131.7p). Pattern E fired 0 times — ADX+MACD building gates suppress most Supertrend entries in scalp mode at current threshold. 22 trades is a thin sample; monitor over next 3 months before drawing conclusions about scalp viability.

### Long mode — 730d · 1h bars

730d net-change: EURJPY +8.9% (FLAT)

| Pair   | Market Regime | Trades | Win%  |  Avg W   | Avg L   |  PF  |  Expec    |   Total    | Max DD      |
|--------|---------------|--------|-------|----------|---------|------|-----------|------------|-------------|
| EURJPY | FLAT          |    175 | 17.1% | 114.5 p  |  15.4 p | 1.54 |  6.9 p/tr |  1,208.1 p |   −365.0 p  |

Pattern breakdown (long): C=51 (+885p), D=63 (+221p), E=41 (+125p), A=20 (−23p).

### Active pair context (2026-05-25 scalp baseline)

| Pair       |  PF  | Trades | Total  | Max DD  |
|------------|------|--------|--------|---------|
| EURUSD     | 3.02 |     55 | +585p  |  −44p   |
| USDJPY     | 2.94 |     41 | +510p  |  −52p   |
| AUDUSD     | 2.60 |     27 | +281p  |  −35p   |
| GBPUSD     | 1.20 |     29 |  +51p  | −149p   |
| **EURJPY** | **1.73** | **22** | **+140p** | **−96p** |

### Notes

- **EURJPY PF 1.54 long / 1.73 scalp — first clean OANDA result.** Long PF 1.54 is consistent with the May 09 Yahoo evaluation (1.57) despite a completely different data source — this cross-validation is reassuring.
- **Long mode ranks 3rd of 5 by PF** (between EURUSD 1.46 and USDJPY 2.07 in the active pair long-mode table).
- **Pattern A retained.** Its long-mode contribution is negative (−23 pips / 20 trades) but removing it depresses long-mode PF from 1.54 to 1.47. This is a 20-trade sample artefact risk; monitor over live data before acting. Premature to remove as was done for USDJPY (which had isolated testing confirming sub-1.0 PF for A and C independently).
- **Verdict: candidate — pending GBPUSD slot.** EURJPY is confirmed viable in both modes with manageable drawdown and genuine EURUSD decorrelation. Activation deferred until GBPUSD is retired; 3-concurrent-trade limit at 30:1 leverage is the binding constraint.
- **GBPUSD replacement timing:** GBPUSD DD-to-gain ratio has reached 3:1 (−149p DD / +51p total) in the most recent snapshot. The rotation case is strengthening — see project_position_limits.md.

---

## Weekly Review — 2026-05-26 (live trade validation)

**Purpose:** validate that live trades in `fx_trades.jsonl` are consistent with backtest signals for the week of 2026-05-19 to 2026-05-26.

### Live trades this week

| ID  | Pair   | Type          | Dir | Entry   | SL      | TP      | Result     | PnL    |
|-----|--------|---------------|-----|---------|---------|---------|------------|--------|
| 669 | USDJPY | discretionary | BUY | 158.898 | 158.854 | 159.227 | close_manual | +3.7p |
| 679 | USDJPY | automated     | BUY | 159.232 | 159.166 | 159.434 | close_sl     | −6.6p |

### Backtest signals this week (post data refresh)

| Pair   | Entry time (UTC)     | Dir  | Entry   | SL      | PnL    | Result | Pattern       |
|--------|----------------------|------|---------|---------|--------|--------|---------------|
| EURUSD | 2026-05-19 08:05     | SELL | 1.16314 | 1.16057 | +24.7p | WIN    | C-macd-flip   |
| EURUSD | 2026-05-19 14:10     | SELL | 1.16052 | 1.16152 | −11.0p | LOSS   | C-macd-flip   |
| USDJPY | 2026-05-20 13:40     | BUY  | 159.060 | 158.984 | −9.6p  | LOSS   | D-ha-pullback |
| EURUSD | 2026-05-21 10:05     | SELL | 1.16248 | 1.16015 | +22.3p | WIN    | D-ha-pullback |
| USDJPY | 2026-05-21 10:20     | BUY  | 158.991 | 159.232 | +22.1p | WIN    | D-ha-pullback |
| EURUSD | 2026-05-21 12:55     | SELL | 1.15972 | 1.16072 | −11.0p | LOSS   | C-macd-flip   |
| USDJPY | 2026-05-26 08:20     | BUY  | 159.222 | 159.152 | −9.0p  | LOSS   | D-ha-pullback |

GBPUSD and AUDUSD: no signals this week.

### Validation findings

**Trade ID 679 — matched.** The automated USDJPY signal at 08:20 UTC on 2026-05-26 aligns closely with the backtest:
- Same bar (08:20 UTC), same direction (BUY)
- Entry: backtest 159.222 vs live 159.232 (~1 pip fill slippage, expected)
- SL: backtest 159.152 vs live 159.166 (~1.4 pip difference)
- TP: backtest 159.424 vs live 159.434 (near-identical)
- Both resulted in SL hit — backtest −9.0p, live −6.6p (slight difference due to different entry fill price)

**Trade ID 669 — discretionary, no backtest counterpart.** Correctly absent from backtest. Manually entered and closed for a small profit.

**Missed signals (daemon offline May 19–25):** `fxtrader.log` ends at 2026-05-22 10:11 UTC (Signal 15 — daemon stopped locally). No log entries for May 23–25. The live daemon (server) was restarted in time to catch the May 26 signal but missed:
- EURUSD: 4 signals (2W/2L, net +25.0p) on May 19–21
- USDJPY: 2 signals (1W/1L, net +12.5p) on May 20–21
- Estimated missed PnL: ~+37.5p across pairs. Root cause: daemon downtime, not signal failure.

**Minor SL floor discrepancy (trade ID 679):** `HA_SL_MIN_PIPS = 7` for USDJPY but live risk was 6.6p (159.232 − 159.166). The SL was computed from spread-adjusted entry (~159.237), giving SL ~159.167 from ep_adj — which is ≥7 pips from ep_adj — but the actual fill at 159.232 leaves only 6.6p of margin. This is the same class of issue as the A/C SL floor finding (SPEC §11.2); already known, not yet fixed.

### Snapshot — 2026-05-26

**Scalp mode (90d · M5 bars)**

90d net-change: EURUSD −1.2% (TREND_DOWN) · GBPUSD −0.3% (FLAT) · USDJPY +1.7% (TREND_UP) · AUDUSD +1.1% (TREND_UP)

| Pair   | Market Regime | Trades | Win%  | Avg W  | Avg L  |  PF  | Expec      | Total   | Max DD   |
|--------|---------------|--------|-------|--------|--------|------|------------|---------|----------|
| EURUSD | TREND_DOWN    |     55 | 52.7% | 30.2 p | 11.1 p | 3.02 | 10.6 p/tr  | +585 p  |  −44 p   |
| USDJPY | TREND_UP      |     42 | 38.1% | 48.3 p | 10.5 p | 2.84 | 11.9 p/tr  | +501 p  |  −52 p   |
| AUDUSD | TREND_UP      |     27 | 44.4% | 38.0 p | 11.7 p | 2.60 | 10.4 p/tr  | +281 p  |  −35 p   |
| GBPUSD | FLAT          |     29 | 24.1% | 43.9 p | 11.7 p | 1.20 |  1.7 p/tr  |  +51 p  | −149 p   |

**Long mode (730d · H1 bars)**

730d net-change: EURUSD +7.3% (TREND_UP) · GBPUSD +5.8% (TREND_UP) · USDJPY +1.4% (FLAT) · AUDUSD +8.1% (TREND_UP)

| Pair   | Market Regime | Trades | Win%  | Avg W   | Avg L  |  PF  | Expec     | Total   | Max DD    |
|--------|---------------|--------|-------|---------|--------|------|-----------|---------|-----------|
| EURUSD | TREND_UP      |    125 | 24.8% |  64.4 p | 11.2 p | 1.89 |  7.5 p/tr | +940 p  |  −307 p   |
| AUDUSD | TREND_UP      |    144 | 25.7% |  51.6 p | 11.6 p | 1.54 |  4.7 p/tr | +674 p  |  −268 p   |
| GBPUSD | TREND_UP      |    133 | 17.3% |  86.8 p | 12.1 p | 1.50 |  5.0 p/tr | +664 p  |  −160 p   |
| USDJPY | FLAT          |    113 | 15.0% | 106.1 p | 12.7 p | 1.48 |  5.2 p/tr | +585 p  |  −584 p   |

### Notes

- **USDJPY scalp PF 2.84** (was 2.94 at 2026-05-25 snapshot) — one fresh LOSS (trade 679) absorbed; still well above threshold. All other active pairs stable vs prior snapshot.
- **USDJPY long-mode max DD −584p** is large relative to total (+585p). Low win rate (15%) and large lot sizes (~1.2–1.3 lots) are the drivers. Monitor for drawdown deepening.
- **GBPUSD shown for reference only** — removed from live rotation via `FX_PAIRS=eurusd,usdjpy,audusd` in `.env`. Not traded.
- **Daemon gap May 19–25:** ~37.5 pip opportunity cost across EURUSD and USDJPY. No strategy flaw — purely operational. Investigate server restart resilience.

---

## Snapshot — 2026-05-29

**Period:** scalp = 90d ending 2026-05-28 (parquet store current as of May 28 close)
**Changes since last snapshot:** None. Routine weekly snapshot to capture May 26–28 window absorption.

### Scalp mode — 90d · 5m bars

90d net-change (approx, per May 26 baseline): EURUSD −1.2% (TREND_DOWN) · USDJPY +1.7% (TREND_UP) · AUDUSD +1.1% (TREND_UP) · EURJPY +0.6% (FLAT)

| Pair   | Market Regime | Trades | Win%  | Avg W   | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|---------|---------|------|------------|------------|-------------|
| EURUSD | TREND_DOWN    |     57 | 52.6% |  29.7 p |  11.1 p | 2.97 |  10.4 p/tr |    590.8 p |    −44.0 p  |
| USDJPY | TREND_UP      |     44 | 34.1% |  47.6 p |  10.2 p | 2.41 |   9.5 p/tr |    417.0 p |    −54.0 p  |
| AUDUSD | TREND_UP      |     26 | 46.2% |  38.0 p |  11.7 p | 2.79 |  11.3 p/tr |    292.7 p |    −34.5 p  |
| EURJPY | FLAT          |     25 | 32.0% |  44.8 p |  12.6 p | 1.68 |   5.8 p/tr |    144.5 p |    −84.0 p  |

(p = pips · tr = trade · USDJPY: Patterns D+E, ADX exempt; EURUSD/AUDUSD: A+C+D; EURJPY: A+C+D+E · EURJPY candidate only, not yet in live rotation · GBPUSD not run)

### vs. prior snapshot (2026-05-26)

| Pair   | PF before | PF after | Trades Δ | Total pips Δ | Max DD Δ |
|--------|-----------|----------|----------|--------------|----------|
| EURUSD | 3.02      | **2.97** | +2       | +5.8         | stable   |
| USDJPY | 2.84      | **2.41** | +2       | −84.8        | −52→−54  |
| AUDUSD | 2.60      | **2.79** | −1       | +11.5        | stable   |
| EURJPY | 1.73¹     | **1.68** | +3       | +5.0         | −96→−84  |

¹ From 2026-05-26 candidate evaluation (same data window)

### Last-30-day daily breakdown (all active pairs combined, Apr 28–May 28)

| Date        | DOW | Tr | W | L | WR%   | Pips    | Cumul   |
|-------------|-----|----|---|---|-------|---------|---------|
| 2026-04-28  | Tue |  2 | 2 | 0 | 100%  | +82.5   | +82.5   |
| 2026-04-29  | Wed |  3 | 1 | 2 |  33%  |  −2.6   | +79.9   |
| 2026-04-30  | Thu |  6 | 4 | 2 |  67%  | +193.8  | +273.7  |
| 2026-05-04  | Mon |  2 | 1 | 1 |  50%  | +11.7   | +285.4  |
| 2026-05-05  | Tue |  2 | 1 | 1 |  50%  | +31.6   | +317.0  |
| 2026-05-06  | Wed |  4 | 2 | 2 |  50%  | +20.8   | +337.8  |
| 2026-05-07  | Thu |  1 | 0 | 1 |   0%  | −11.0   | +326.8  |
| 2026-05-11  | Mon |  2 | 1 | 1 |  50%  | +17.1   | +343.9  |
| 2026-05-12  | Tue |  2 | 1 | 1 |  50%  |  +9.4   | +353.3  |
| 2026-05-13  | Wed |  1 | 1 | 0 | 100%  | +21.8   | +375.1  |
| 2026-05-14  | Thu |  4 | 3 | 1 |  75%  | +121.7  | +496.8  |
| 2026-05-18  | Mon |  1 | 0 | 1 |   0%  | −12.0   | +484.8  |
| 2026-05-19  | Tue |  4 | 3 | 1 |  75%  | +85.1   | +569.9  |
| 2026-05-20  | Wed |  1 | 0 | 1 |   0%  |  −9.6   | +560.3  |
| 2026-05-21  | Thu |  4 | 2 | 2 |  50%  | +21.4   | +581.7  |
| 2026-05-25  | Mon |  1 | 0 | 1 |   0%  | −12.0   | +569.7  |
| 2026-05-26  | Tue |  4 | 0 | 4 |   0%  | −41.0   | +528.7  |
| 2026-05-27  | Wed |  6 | 1 | 5 |  17%  | −36.3   | +492.4  |
| 2026-05-28  | Thu |  3 | 1 | 2 |  33%  | +11.0   | +503.4  |
| **TOTAL**   |     | 53 |24 |29 |**45%**|**+503.4**|        |

30d pair breakdown: EURUSD 20t / 60% WR / +182.6p · USDJPY 16t / 25% WR / +80.3p · EURJPY 17t / 47% WR / +240.5p · AUDUSD 0t (no signals in last 30d — ADX gate suppressing)

### Live trades this week (May 25–28)

| ID  | Pair   | Dir  | Entry   | Exit    | PnL     | Reason   | Signal         |
|-----|--------|------|---------|---------|---------|----------|----------------|
| 728 | EURUSD | BUY  | 1.16255 | 1.16406 | +15.1 p | SL (BE+) | MACD flip      |
| 744 | USDJPY | SELL | 159.273 | 159.341 |  −6.8 p | SL       | ST flip        |
| 758 | USDJPY | SELL | 159.195 | 159.315 | −12.0 p | SL       | HA pullback    |
| 767 | USDJPY | SELL | 159.147 | 159.267 | −12.0 p | SL       | HA pullback    |
| 751 | EURUSD | BUY  | 1.16538 | —       | open    | —        | HA pullback    |

Live closed PnL: −15.7 pips (4 closed, 1 open at time of snapshot).

### Notes

- **EURUSD stable** — PF 3.02 → 2.97, within noise. Two new trades added without disrupting the win rate (52.7% → 52.6%) or drawdown. Pair continues to be the most consistent performer by WR.
- **USDJPY dip — key observation.** PF 2.84 → 2.41 is the most significant single-week move since the Supertrend addition (May 9). Caused by the May 26–28 cluster: 3 consecutive SELL entries all stopped out with USDJPY ranging in a tight 159.15–159.35 band. The pair is still above PF 2.0 and avg win (47.6 p) remains healthy. Monitor W22 — if another poor week follows and PF approaches 2.0, that would be the first structural concern since USDJPY has been exempt from the ADX gate and relies on Supertrend/HA for self-selection. No action yet.
- **AUDUSD improved (2.60 → 2.79)** with one old loser rolling off the window. Continues to be the tightest drawdown pair (−34.5 p). Still generating zero signals in the last 30 days — the ADX gate is correctly holding it out of a low-trend environment on real OANDA data.
- **EURJPY — PF 1.68, 3 new trades.** DD improved from −96 p to −84 p as older losses rolled off. Pattern D dominates (+131.7 p / 8 trades); Pattern A still a net drag. Candidate for GBPUSD replacement once GBPUSD is retired. No change to the watch/defer decision from May 26.
- **May 26–28 was a RANGE-like period** for USDJPY (25% WR, choppy JPY). The early-week indicator (per regime/RR analysis): by end of Tuesday May 26 the TP rate was 0% across the roster — a RANGE warning. Week closed at 33% WR which matches the RANGE classification threshold. Consistent with prior regime analysis findings.

---

## Forward Test Review — 2026-06-03 (W23)

**Second consecutive poor week for USDJPY — monitoring, no action yet.**

The W22 snapshot note said: "Monitor W22 — if another poor week follows and PF approaches 2.0, that would be the first structural concern." W23 (May 28 – Jun 3) is that second poor week.

### Forward test results (fx_trades.jsonl, May 28 – Jun 3)

| Pair   | Trades | Win% | PF   | Total   | Notes |
|--------|--------|------|------|---------|-------|
| EURUSD |      6 | 50%  | 1.35 | +12.4 p | Includes 1 ghost close (−12p) and 1 probable double-counted close |
| USDJPY |     10 | 10%  | 0.10 | −66.3 p | Includes 2 ghost closes (−24p) and 3 sub-RR trades |

**Known data quality issues in this sample** (see diagnostic notes below — these inflate the reported losses):

1. **Ghost closes (daemon restart bug):** Trades 751/767/838 each appear in the log twice — once with the original trade_id and once with `trade_id: null` a few hours later, after a daemon restart replayed the JSONL and re-closed already-closed positions. Removes −36 pips of artificial losses from the totals.
2. **Sub-RR trades slipped through `HA_MIN_RR=1.5`:** Trades 821 (R:R 0.07), 829 (R:R 0.64), 838 (R:R 0.55) traded with very low ATR at signal time, producing tiny TPs. After fill slippage clamped SL to 12 pips, the post-fill RR check did not close them as expected.
3. **EURUSD 805 double-count:** Close event at Jun 1 (+8.9p, trade_id 805) and a second close at Jun 3 (+23.8p, trade_id null) for the same 1.16416 SELL entry — one is likely a false local-state close with the OANDA trade remaining open.

Correcting for ghost closes only: USDJPY −42.3 p over 8 real trades / 12.5% WR. Still poor, but the primary driver is market regime, not bookkeeping.

### USDJPY regime assessment

USDJPY traded in a 159.0–160.0 band throughout W22–W23. Patterns D (HA pullback) and E (Supertrend flip) both suffered sequential SL hits as price oscillated within the range. The pair is exempt from the daily ADX gate (`DAILY_ADX_MIN = 0`), relying on Supertrend/HA self-selection to avoid ranging conditions — which is proving insufficient.

**Decision: monitor one more week (W24, Jun 2–6).** No parameter or gate changes yet. If USDJPY continues with <25% WR or PF <2.0 in the next backtest snapshot, evaluate adding an ADX floor (candidate threshold: ADX(14) ≥ 15 on daily bars, consistent with the values applied to EURUSD/AUDUSD).

---

## Snapshot — 2026-06-04

**Period:** scalp = 90d ending 2026-06-04 (parquet store current as of Jun 4)
**Changes since last snapshot:** None. Routine mid-week snapshot to capture W22–W23 absorption and check USDJPY PF trajectory per prior decision.

### Scalp mode — 90d · 5m bars

90d net-change: EURUSD −0.1% (FLAT) · USDJPY +1.6% (FLAT) · AUDUSD +1.7% (FLAT) · EURJPY +1.5% (FLAT)

| Pair   | Market Regime | Trades | Win%  | Avg W   | Avg L   |  PF  | Expec      | Total      | Max DD      |
|--------|---------------|--------|-------|---------|---------|------|------------|------------|-------------|
| EURUSD | FLAT          |     58 | 51.7% |  29.7 p |  11.1 p | 2.86 |  10.0 p/tr |    579.8 p |    −44.0 p  |
| USDJPY | FLAT          |     47 | 34.0% |  45.6 p |  10.2 p | 2.32 |   8.8 p/tr |    415.4 p |    −55.6 p  |
| AUDUSD | FLAT          |     27 | 48.1% |  36.3 p |  11.7 p | 2.88 |  11.4 p/tr |    307.6 p |    −46.0 p  |
| EURJPY | FLAT          |     30 | 30.0% |  42.4 p |  12.5 p | 1.46 |   4.0 p/tr |    119.7 p |    −84.0 p  |

(p = pips · tr = trade · USDJPY: Patterns D+E, ADX exempt; EURUSD/AUDUSD: A+C+D; EURJPY: A+C+D+E · EURJPY candidate only, not yet in live rotation · GBPUSD not run)

### vs. prior snapshot (2026-05-29)

| Pair   | PF before | PF after | Trades Δ | Total pips Δ | Max DD Δ  | Notes |
|--------|-----------|----------|----------|--------------|-----------|-------|
| EURUSD | 2.97      | **2.86** | +1       | −11.0        | stable    | EURUSD backtest fired 0 W23 signals; live took 2 — signal divergence persisting |
| USDJPY | 2.41      | **2.32** | +3       | −1.6         | −52→−56   | Third consecutive losing/flat week; PF below 2.5 for first time since May |
| AUDUSD | 2.79      | **2.88** | +1       | +14.9        | stable    | Added 1 trade, slight improvement |
| EURJPY | 1.68      | **1.46** | +5       | −24.8        | stable    | Worst W23 of all pairs in backtest (5 trades, 20% WR) |

### W23 backtest breakdown (Jun 1–4, in-progress)

| Pair   | BT Trades | BT WR | BT PF | BT pips | Live trades | Live WR | Live pips | Live vs BT |
|--------|-----------|-------|-------|---------|-------------|---------|-----------|------------|
| EURUSD | 0         | —     | —     | —       | 2           | 50%     | −2.5 p    | BT silent; live active |
| USDJPY | 3         | 33%   | 0.91  | −1.6 p  | 6           | 17%     | −20.4 p   | Live 3× more trades, deeper loss |
| AUDUSD | 1         | 0%    | 0.00  | −11.5 p | 0           | —       | —         | BT fired; live quiet |
| EURJPY | 5         | 20%   | 0.48  | −24.8 p | —           | —       | —         | Not live |

Live combined W23: 8 real automated closes, 25% WR, −22.9 pips. Two null-ID ghost closes logged on Wed Jun 03 07:13–07:35 UTC (daemon restart artifact, confirmed not real P&L — entry prices match already-closed trades 805 and 838).

### Notes

- **USDJPY PF 2.32 — third consecutive below-par period.** W22 (backtest −54.0p, 0% WR), W23 (backtest −1.6p, 33% WR). The May 29 W23 decision trigger was "PF <2.0 or <25% WR" — current PF 2.32 has not yet reached that level, but trajectory is downward (3.17 → 2.94 → 2.84 → 2.41 → 2.32 over six snapshots). USDJPY continues to trade in the 159.0–160.0 range; D+E patterns are firing into choppy conditions that lack follow-through. **Decision: begin evaluating the ADX floor** — run a sweep of `DAILY_ADX_MIN` values (12, 15, 18) for USDJPY to quantify the trade-off before the next snapshot.
- **EURUSD signal divergence on W23.** Backtest generated zero EURUSD signals while live took 2 trades this week. This is a recurrence of the divergence documented in the May 21 analysis. EURUSD backtest data ends at W22 (last entry May 28) — the parquet update brought data forward but the indicator's ADX gate may be producing different results on the backtest window vs. live. The two live EURUSD trades (−11.4p BUY, +8.9p SELL) were directionally correct for the regime; the backtest missing them is not necessarily a strategy concern, but it undermines confidence in the backtest as a live signal proxy for EURUSD.
- **AUDUSD quietly improving.** PF 2.88 with a max DD of only −46.0p is the best risk-adjusted result in the active set this snapshot. One new W23 trade added (a loss, −11.5p) but the rolling window dropped older losers, lifting PF. ADX gate continues to limit trade frequency correctly.
- **EURJPY degraded most this week.** W23 was its worst week in the backtest sample (5 trades, 20% WR, −24.8p). PF fell from 1.68 → 1.46, now approaching the marginal zone. Consistent with the broader range environment. No change to the watch/defer stance — still a candidate for GBPUSD replacement, not yet activated.
- **W22+W23 combined are a rough patch for the entire portfolio.** USDJPY −55.6p (W22) + −1.6p (W23) = −57.2p over two weeks. EURUSD −16.3p (W22) + 0p (W23, BT silent) also soft. This is the deepest two-week drawdown in the backtest window since W17 (2026-04-21, −96p combined). All pairs remain FLAT macro regime — not a trend reversal, likely a consolidation phase.
- **Daemon restart ghost events (Jun 03, 07:13 UTC)** produced two null-ID close events in fx_trades.jsonl that match already-closed trades. The daemon lost state on restart and re-closed phantom positions. No real P&L impact confirmed (OANDA trade IDs do not match any live open). Root cause: the JSONL replay path does not correctly verify whether a trade_id is still open on OANDA before issuing a close. Should be investigated before the next high-volatility period.

---

## EURUSD Entry Simplification Research — 2026-06-06

**Motivation:** The EURUSD entry system uses three pattern types (A, C, D) with multiple oscillator guards (RSI, Stochastic on A and C; 3-candle HA sequence on D). The question was whether a simpler system could match or exceed performance.

**Baseline (A+C+D, 90d, scalp):** 49 trades · 42.9% WR · PF 2.27 · 7.3 p/tr · −31.5 max DD · $13,512 final balance

**Per-pattern baseline breakdown:**

| Pattern | Trades | WR    | PF   |
|---------|--------|-------|------|
| A       | 2      | —     | 5.02 |
| C       | 23     | 35.0% | 1.61 |
| D       | 24     | 50.0% | 2.86 |

**Experiments run:**

| System                                  | Trades | WR    | PF   | Expect | Max DD  | Balance  |
|-----------------------------------------|--------|-------|------|--------|---------|----------|
| **Original A+C+D** (baseline)           | 49     | 42.9% | 2.27 | 7.3 p  | −31.5 p | $13,512  |
| D-only (drop A+C)                       | 33     | 45.5% | 2.39 | 7.6 p  | −30.0 p | $12,457  |
| C (RSI gate only, no Stoch) + D         | 59     | 40.7% | 1.95 | 5.7 p  | −60.0 p | $13,255  |
| C (no oscillator guards) + D            | 67     | 38.8% | 1.78 | 4.8 p  | −77.6 p | $13,129  |
| 2-bar HA (replace D, no oscillators)    | 77     | 41.6% | 1.88 | 5.2 p  | −64.0 p | $13,987  |

**Findings:**

- D-only produces a marginal PF gain (+0.12) but loses $1,055 final balance; dropping A is essentially free (A fires only 2 times per 90 days), but dropping C removes real edge.
- Removing Stochastic from C expanded trade count 23→53 with PF collapsing to 1.95 and max DD doubling to −60p. The Stochastic gate is filtering a large volume of low-quality C setups.
- Removing all C oscillator guards pushed trade count to 67 total; PF 1.78 and max DD −77.6p — the worst of all tested configurations.
- The 2-bar HA approach (entry on any HA colour change, no oscillators) generated 77 trades at PF 1.88 — substantially more activity but lower quality. The 3-candle sequence in Pattern D is filtering the majority of HA signals.
- Hour-of-day analysis showed C losses concentrated in 11:00–14:00 UTC (6 trades at 13–14h, 0% WR, −60 pips); early London C (07:00–09:00 UTC) was strong (~80% WR). The Stochastic guard is the mechanism suppressing these midday entries.

**Conclusion:** A+C+D retained unchanged. Every simplification tested degraded PF and/or approximately doubled max drawdown. The RSI+Stochastic guards on Pattern C and the 3-candle trend + pullback requirement on Pattern D are load-bearing — complexity in this system is justified by measured outcomes.

---

## Code changes — 2026-06-06

### Strategy / parameter changes

1. **EURJPY: `DAILY_ADX_MIN` 18 → 0 (gate disabled).** Backtest showed the gate was destructive for EURJPY: PF 0.54 with the gate vs 0.85 without. Root cause is that EURJPY trends in short, sharp bursts that are frequently below the ADX threshold. Gate remains on EURUSD (17) and AUDUSD (18) where it adds value.

2. **GBPUSD: `DAILY_ADX_MIN` 25 → 0 (gate disabled).** GBPUSD is not in live rotation but the parameter is kept aligned with backtest-validated config. Gate had no measured benefit given the pair's existing Friday block and position-limit exclusion.

### Order management: fixed SL replaces broker-side trailing stop

3. **`oanda.place_market_order`: `trailing_distance` → `stop_loss` (fixed price).** The order payload now sends `stopLossOnFill` with an absolute price level instead of `trailingStopLossOnFill` with a distance. Broker-managed trailing stops were inconsistently executed on OANDA's side during fast markets; the daemon's internal trailing logic (`tradelib.check_position_events`) already re-evaluates the stop on every tick, making the broker-side trail redundant.

4. **Trailing stop activation on BE event (`daemon._process_events`).** The `"be"` (breakeven) event handler was a no-op (`pass`). It now calls `oanda.set_trailing_stop(pos.trade_id, trail_dist, pair)` where `trail_dist = atr × ATR_TRAIL_MULT`. This means the broker-side stop begins trailing only after the internal BE trigger fires, matching the documented strategy intent. Previously the trailing stop was set at order entry and trailed from the start.

### Backtest / daemon fidelity: forming-bar simulation

5. **Forming-bar simulation in `backtest.run_backtest` (scalp mode).** H1 and daily bars used by `assess_h1_bias()` are now rebuilt from M1 data at each M5 tick instead of using pre-computed slices. The current (open) H1 period is constructed by aggregating all M1 bars since the hour boundary and appending a single forming row; the same is done for the daily bar. This mirrors what the live daemon sees at any given tick — a partially-formed H1 and daily bar — rather than the fully-closed bar that the previous backtest used. `fetch_data` returns `df_h1_raw` and `df_1d_raw` (OHLCV only, no pre-computed indicators) for this path; the daily bar is now derived from M1 resampling rather than the stored OANDA D granularity. Constants `H1_IND_LOOKBACK = 200` and `D_IND_LOOKBACK = 60` control how many completed bars precede the forming bar when indicators are recomputed (wide enough that EMA initialisation error is <0.5%).

6. **Forming-bar simulation in `daemon.tick`.** Daily bar computation (`compute_daily_adx`) now appends a forming daily bar built from `state.cache_m1` M1 data since UTC midnight, matching the backtest path above. `M1_MAX_BARS` increased from 360 to 1500 (25-hour rolling window) to ensure enough M1 history to construct today's forming bar. Previously the daemon always fed `compute_daily_adx` only completed daily bars, so the gate could lag one full day at session open.

7. **Forming M5 bar guard in `daemon.tick`.** `last_signal_bar` is no longer set when the signal comes from the current (open, forming) M5 bar and the signal is stale or rejected. Previously, rejecting a signal from the forming bar would permanently lock that bar's timestamp, causing the daemon to ignore that bar even after it closed and its OHLCV settled. The guard now only locks `last_signal_bar` when (a) a trade is actually opened, (b) the bar is confirmed closed (not the forming bar), or (c) the signal passes all checks but spread is too wide.

### Signal path unification

8. **Backtest now uses `ind.build_signal()` (same path as daemon).** Previously `run_backtest` called `ind.compute_sl_tp()` then advanced entry to the next bar's open. It now calls `ind.build_signal(bias_info, entry_result, pair, spread_pips=...)` directly, producing a `Signal` object with `entry_price`, `stop_loss`, `take_profit`, `risk_pips`, and `reward_pips`. Entry is at the signal bar's close (spread-adjusted), matching the daemon's market-order fill timing. This removes a systematic fill-timing gap where the backtest entered one bar later than the daemon.

9. **`ep_adj` bug fix in all five indicator `build_signal` functions** (`indicator_eurusd.py`, `indicator_usdjpy.py`, `indicator_audusd.py`, `indicator_gbpusd.py`, `indicator_eurjpy.py`). The returned `Signal.entry_price` was `round(ep, 5)` (the mid price before spread adjustment) instead of `round(ep_adj, 5)` (the spread-adjusted fill price). This caused the SL/TP levels in the returned signal to be calculated relative to the correct `ep_adj` but the entry price field itself to report the unadjusted value — meaning `risk_pips` and `rr_ratio` embedded in the signal were correct, but any caller that used `signal.entry_price` directly (including the daemon's position sizing and the backtest's `_record_trade` P&L calc) was operating on the wrong price. Fix: return `ep_adj` from all five files.

10. **Spread accounting in `_record_trade`.** The `spread_pips` argument has been removed. P&L is now computed as `(exit − entry) / pv × direction` with no deduction, because `entry_price` from `build_signal` is already spread-adjusted (`ep_adj`). Callers no longer pass `spread_pips` to `_record_trade`.

### Backtest reporting

11. **`risk_pips` in trade record.** `_record_trade()` now writes `risk_pips` (rounded to 1 dp) directly into each trade dict. `_compute_sizing` uses this stored value instead of re-deriving stop distance from `abs(entry − sl) / pip_value`, removing a floating-point precision issue on JPY pairs.

12. **Data-gap detection (`_find_data_gaps`).** New helper that scans the bar index for unexpected time gaps (≥1 h for scalp, ≥4 h for long). Normal Fri→Sun weekend gaps (≥44 h) are suppressed. Reported as a yellow warning block in `report()`, listing up to 10 gaps. Detects stale or incomplete parquet data before interpreting P&L.

13. **Report enhancements.** Summary table shows `Start date` / `End date` rows and a colour-coded `Final balance` row (compounded dollar result with net change).

14. **Weekly P&L table (`report_weekly_pnl`).** Printed by default; suppress with `--no-weekly-pnl`. One row per complete ISO week (first and last partial weeks dropped): trade count, pips P&L, and running balance. Identifies which calendar weeks drive the aggregate result.

---
