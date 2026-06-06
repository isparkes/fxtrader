"""
EURJPY Scalper
==============
Generates intraday scalping signals on Euro / Japanese Yen.

Overview
--------
Two-timeframe approach: 1h chart sets directional bias; 5m chart finds the
precise entry. London/NY overlap session (07:00–16:00 UTC) only — EURJPY also
has real institutional flow during Tokyo hours, which creates a Tokyo-range
breakout edge at London open that the session gate captures automatically.

EURJPY specifics
----------------
- Average daily range ~95 pips — materially wider than EURUSD. Stop parameters
  are widened accordingly (HA_SL_MIN_PIPS = 10, HA_SL_MAX_PIPS = 15).
- Driven primarily by JPY sentiment (BOJ policy, carry dynamics, risk-off
  flows). The EUR leg is secondary on most intraday moves.
- Carry unwinds are violent and asymmetric: both legs sell simultaneously in
  risk-off, producing faster and deeper drawdowns than either parent pair.
- Daily ADX gate is set to 20 (vs 17 for EURUSD) — EURJPY spends more time in
  carry-driven ranging regimes between macro events.
- TRAIL_ACTIVATE_FRAC = 0.70 (same as EURUSD) — earlier breakeven to reduce
  give-back on fast JPY reversals.

──────────────────────────────────────────────────────────────────────────────
TREND FILTER  (1h bars — must pass ALL THREE to open a BUY or SELL bias)
──────────────────────────────────────────────────────────────────────────────

1. EMA50 side
   Price must be above EMA50 for BUY, below for SELL.

2. MACD histogram — sign + building
   The 1h MACD histogram (12/26/9) must be positive AND larger than the
   previous bar for BUY; negative AND smaller (more negative) for SELL.
   Requiring it to be building means we only trade when momentum is
   accelerating — not fading.

3. RSI(14) above / below 50
   Second momentum confirmation independent of MACD.

──────────────────────────────────────────────────────────────────────────────
SUPPLEMENTARY GATES
──────────────────────────────────────────────────────────────────────────────

  • 4h EMA22        — 4h close must be on the same side as the 1h direction.
  • Daily ADX(14)   — must be ≥ 20. Suppresses entries on directionless days.
  • Day-of-week     — Friday (4) is blocked.

──────────────────────────────────────────────────────────────────────────────
ENTRY FILTERS  (5m bars — evaluated once the 1h bias is active)
──────────────────────────────────────────────────────────────────────────────

Pre-checks applied to every bar before pattern evaluation:

  • Session gate     — bar timestamp must fall within 07:00–16:00 UTC.
  • ATR floor        — 5m ATR(14) must be ≥ 0.0002 (2 pips). Skips entries
                       when the market is too compressed to reach the target
                       before reversing.

Pattern A — EMA8/21 cross
  BUY:  EMA8 crosses above EMA21 on the current bar.
  SELL: EMA8 crosses below EMA21.
  Guards: RSI(7) 52–75 / 25–48; Stoch %K above/below %D with room to run.

Pattern C — MACD histogram flip
  BUY:  5m MACD histogram (6/13/4) crosses zero upward; price above EMA21.
  SELL: 5m MACD histogram crosses zero downward; price below EMA21.
  Guards: same RSI and Stochastic conditions as Pattern A.

Pattern D — Heikin-Ashi pullback + resumption
  Requires 3 consecutive same-colour HA candles establishing a local trend,
  followed by exactly 1 opposing HA candle (the pullback), then entry on the
  open of the first candle that resumes the trend direction.
  No additional RSI/Stochastic guards — the 5-bar HA sequence provides the
  quality filter.

Pattern E — Supertrend flip (same as USDJPY)
  Entry on the bar where Supertrend(10, 3.0) changes direction, provided the
  flip is aligned with the 1h bias. EURJPY is only eligible for Pattern E when
  DAILY_ADX_MIN is satisfied — the ADX gate at bias level already enforces this.

──────────────────────────────────────────────────────────────────────────────
RISK MANAGEMENT
──────────────────────────────────────────────────────────────────────────────

Patterns A, C, E:
  Stop loss:   ATR(14) × 0.4, floored at HA_SL_MIN_PIPS (10 pips).
  Take profit: ATR(14) × 3.0. Trailing stop typically exits first.

Pattern D:
  Stop loss:   Pullback candle's HA extreme ± 2-pip buffer, clamped to
               10–15 pips from entry. Suppressed if R:R < 1.5.
  Take profit: ATR(14) × 3.0 (same ceiling as A/C/E).

Trailing stop:
  Phase 1 (breakeven trigger): 70% of TP distance (TRAIL_ACTIVATE_FRAC = 0.70).
  Phase 2 (active trail): ATR × 0.4 behind running best price.
  Phase 3 (TP extension): at original TP, SL locks at 90% of TP distance,
                           TP doubles, trail tightens to ATR × 0.2.

Cooldown: 60 minutes after a stop-loss close (COOLDOWN_MINS in daemon.py).
"""

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange


def pip_value(symbol: str) -> float:
    """Return the pip size for a symbol. JPY pairs use 0.01; all others 0.0001."""
    return 0.01 if "JPY" in symbol.upper() else 0.0001


# ── Tunable parameters ────────────────────────────────────────────────────────
# 1h trend
H1_EMA_TREND   = 50
H1_MACD_FAST   = 12
H1_MACD_SLOW   = 26
H1_MACD_SIGNAL = 9
H1_RSI_PERIOD  = 14

# 4h trend filter (Measure 4)
H4_EMA_PERIOD = 22

# Daily regime gate — suppress entries when daily ADX < threshold
DAILY_ADX_MIN = 0     # gate disabled — backtest shows gate hurts EURJPY (PF 0.54 vs 0.85 without)

# Day-of-week gate — blocked weekdays (0=Mon … 4=Fri)
BLOCKED_DAYS: frozenset[int] = frozenset({4})   # Friday

# 5m entry
M5_EMA_FAST     = 8
M5_EMA_SLOW     = 21
M5_RSI_PERIOD   = 7
M5_STOCH_PERIOD = 14
M5_STOCH_SMOOTH = 3
M5_ATR_MIN      = 0.0002   # 2 pips — don't scalp a dead market

# Risk — patterns A, C, E
ATR_PERIOD  = 14
ATR_TRAIL_MULT = 0.4   # trailing stop distance: ATR × 0.4 behind best price
ATR_TP_MULT = 3.0   # wide ceiling — trailing stop usually exits first

# Pattern D — HA pullback stop parameters
HA_SL_BUFFER_PIPS = 2     # pips added beyond the pullback extreme
HA_SL_MIN_PIPS    = 10    # floor: wider than USDJPY (7) — EURJPY's ~95 pip daily range
HA_SL_MAX_PIPS    = 15    # ceiling: wider than EURUSD (12) for the same reason
HA_MIN_RR         = 1.5   # suppress signal if clamped R:R falls below this

# Trailing stop — phase-1 breakeven trigger
TRAIL_ACTIVATE_FRAC = 0.70   # 70%, same as EURUSD — earlier BE to reduce JPY give-back

# Session — London open through NY afternoon (UTC)
SESSION_START_UTC = 7
SESSION_END_UTC   = 16
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Signal:
    timestamp: str
    direction: str           # "BUY" | "SELL" | "FLAT"
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    atr: Optional[float]
    h1_macd_hist: Optional[float]
    h1_rsi: Optional[float]
    h1_trend: Optional[str]
    entry_basis: str
    risk_pips: Optional[float]
    reward_pips: Optional[float]
    rr_ratio: Optional[float]


def compute_h1_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add trend-context indicators to a bar DataFrame (1h, or 4h resampled).

    Columns added:
        macd_hist  — MACD histogram (12/26/9). Positive = bullish momentum.
        ema_trend  — EMA(50). Price must be on the correct side of this line.
        atr        — ATR(14). Used to size stop-loss and take-profit levels.
        rsi        — RSI(14). Must be above 50 for BUY bias, below 50 for SELL.
    """
    close = df["close"]

    macd_ind = MACD(close=close, window_fast=H1_MACD_FAST,
                    window_slow=H1_MACD_SLOW, window_sign=H1_MACD_SIGNAL)
    df["macd_hist"] = macd_ind.macd_diff()

    df["ema_trend"] = EMAIndicator(close=close, window=H1_EMA_TREND).ema_indicator()

    atr = AverageTrueRange(high=df["high"], low=df["low"], close=close, window=ATR_PERIOD)
    df["atr"] = atr.average_true_range()

    df["rsi"] = RSIIndicator(close=close, window=H1_RSI_PERIOD).rsi()

    return df


def compute_daily_adx(df: pd.DataFrame) -> pd.DataFrame:
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
    df["adx"] = adx.adx()
    return df


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    ATR-based Supertrend indicator (replication of Pine Script v4 logic).

    The upper/lower bands ratchet in the trend direction — they only tighten,
    acting as a dynamic trailing support/resistance level.

    Adds columns:
        st_trend — 1 for uptrend, -1 for downtrend
        st_line  — the active band level (support in uptrend, resistance in downtrend)
        st_flip  — True on the bar where trend direction changed
    """
    close_v = df["close"].values
    high_v  = df["high"].values
    low_v   = df["low"].values

    atr_vals = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=period,
    ).average_true_range().values

    hl2         = (high_v + low_v) / 2.0
    basic_upper = hl2 + multiplier * atr_vals
    basic_lower = hl2 - multiplier * atr_vals

    n     = len(df)
    upper = basic_upper.copy()
    lower = basic_lower.copy()
    trend = np.ones(n, dtype=int)

    for i in range(1, n):
        if close_v[i - 1] > lower[i - 1]:
            lower[i] = max(basic_lower[i], lower[i - 1])
        if close_v[i - 1] < upper[i - 1]:
            upper[i] = min(basic_upper[i], upper[i - 1])
        if trend[i - 1] == -1 and close_v[i] > upper[i - 1]:
            trend[i] = 1
        elif trend[i - 1] == 1 and close_v[i] < lower[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

    prev     = np.empty(n, dtype=int)
    prev[0]  = trend[0]
    prev[1:] = trend[:-1]

    df["st_trend"] = trend
    df["st_line"]  = np.where(trend == 1, lower, upper)
    df["st_flip"]  = trend != prev
    return df


def compute_m5_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add entry-timing indicators to a bar DataFrame (5m, or 1h in long mode).

    Columns added:
        ema_fast   — EMA(8). Crossover with ema_slow triggers Pattern A.
        ema_slow   — EMA(21). Price anchor for Pattern C entries.
        rsi        — RSI(7). Guards for patterns A and C.
        macd_hist  — MACD histogram (6/13/4). Zero-cross triggers Pattern C.
        stoch_k    — Stochastic %K (14,3). Guards for patterns A and C.
        stoch_d    — Stochastic %D signal line.
        atr        — ATR(14). Volatility gate and SL/TP sizing.
        ha_close / ha_open / ha_high / ha_low  — Heikin-Ashi (Pattern D).
        st_trend / st_line / st_flip           — Supertrend(10, 3.0) (Pattern E).
    """
    close = df["close"]

    df["ema_fast"] = EMAIndicator(close=close, window=M5_EMA_FAST).ema_indicator()
    df["ema_slow"] = EMAIndicator(close=close, window=M5_EMA_SLOW).ema_indicator()
    df["rsi"]      = RSIIndicator(close=close, window=M5_RSI_PERIOD).rsi()

    macd_ind = MACD(close=close, window_fast=6, window_slow=13, window_sign=4)
    df["macd_hist"] = macd_ind.macd_diff()

    stoch = StochasticOscillator(
        high=df["high"], low=df["low"], close=close,
        window=M5_STOCH_PERIOD, smooth_window=M5_STOCH_SMOOTH,
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=close, window=ATR_PERIOD,
    ).average_true_range()

    # Heikin-Ashi — recursive ha_open computed on raw arrays to avoid iloc overhead
    _o = df["open"].values
    _h = df["high"].values
    _l = df["low"].values
    _c = df["close"].values

    _hc    = (_o + _h + _l + _c) / 4.0
    _ho    = _hc.copy()
    _ho[0] = (_o[0] + _c[0]) / 2.0
    for k in range(1, len(_ho)):
        _ho[k] = (_ho[k - 1] + _hc[k - 1]) / 2.0

    df["ha_close"] = _hc
    df["ha_open"]  = _ho
    df["ha_high"]  = df[["high", "ha_open", "ha_close"]].max(axis=1)
    df["ha_low"]   = df[["low",  "ha_open", "ha_close"]].min(axis=1)

    # Supertrend (Pattern E) — same parameters as USDJPY
    df = compute_supertrend(df, period=10, multiplier=3.0)

    return df


def assess_h1_bias(df: pd.DataFrame, df_4h: Optional[pd.DataFrame] = None,
                   df_1d: Optional[pd.DataFrame] = None) -> dict:
    """
    Evaluate the trend gates on the last completed 1h bar.

    Direction requires all three gates to pass simultaneously:
        1. Price side of EMA50
        2. MACD histogram positive/negative AND building (accelerating)
        3. RSI(14) above/below 50

    Optional supplementary gates:
        df_4h — 4h EMA22 agreement gate
        df_1d — daily ADX(14) ≥ DAILY_ADX_MIN gate

    Returns a dict with keys: direction, macd_hist, h1_rsi, atr, trend, close.
    """
    last = df.iloc[-1]

    close     = float(last["close"])
    ema_trend = float(last["ema_trend"])
    macd_hist = float(last["macd_hist"])
    atr       = float(last["atr"])
    h1_rsi    = float(last["rsi"])

    prev_macd = float(df.iloc[-2]["macd_hist"]) if len(df) >= 2 else macd_hist

    above = close > ema_trend
    below = close < ema_trend
    bull  = macd_hist > 0 and macd_hist > prev_macd and h1_rsi > 50
    bear  = macd_hist < 0 and macd_hist < prev_macd and h1_rsi < 50

    if above and bull:
        direction = "BUY"
    elif below and bear:
        direction = "SELL"
    else:
        direction = "FLAT"

    if direction != "FLAT" and df_4h is not None and len(df_4h) > 0:
        bar_4h   = df_4h.iloc[-1]
        h4_above = float(bar_4h["close"]) > float(bar_4h["ema_4h"])
        if direction == "BUY" and not h4_above:
            direction = "FLAT"
        elif direction == "SELL" and h4_above:
            direction = "FLAT"

    if direction != "FLAT" and df_1d is not None and len(df_1d) >= 14:
        adx_val = df_1d.iloc[-1].get("adx")
        if adx_val is not None and not pd.isna(adx_val) and float(adx_val) < DAILY_ADX_MIN:
            direction = "FLAT"

    return {
        "direction": direction,
        "macd_hist": macd_hist,
        "h1_rsi":    h1_rsi,
        "atr":       atr,
        "trend":     "above EMA50" if above else "below EMA50",
        "close":     close,
    }


def find_m5_entry(df5m: pd.DataFrame, direction: str,
                   use_session: bool = True) -> Optional[dict]:
    """
    Scan the last 30 5m bars for a scalp entry trigger.
    Direction is set by the 1h bias — entries only fire when aligned.

    Pattern A: EMA8/21 cross with RSI + Stochastic confirmation.
    Pattern C: 5m MACD histogram zero-cross with RSI + Stochastic confirmation.
    Pattern D: 3 same-colour HA candles → 1 pullback → resumption candle.
    Pattern E: Supertrend(10, 3.0) flip aligned with 1h bias direction.

    Returns the most recent matching bar (latest wins).
    """
    if direction == "FLAT":
        return None

    window     = df5m.iloc[-30:].copy()
    last_entry = None

    for i in range(4, len(window)):
        bar  = window.iloc[i]
        prev = window.iloc[i - 1]

        if use_session:
            ts = bar.name
            if hasattr(ts, "hour"):
                hour = ts.tz_convert("UTC").hour if getattr(ts, "tzinfo", None) else ts.hour
                if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
                    continue

        close    = float(bar["close"])
        ema_fast = float(bar["ema_fast"])
        ema_slow = float(bar["ema_slow"])
        prev_ef  = float(prev["ema_fast"])
        prev_es  = float(prev["ema_slow"])
        rsi      = float(bar["rsi"])
        hist     = float(bar["macd_hist"])
        prev_h   = float(prev["macd_hist"])
        stoch_k  = float(bar["stoch_k"])
        stoch_d  = float(bar["stoch_d"])
        atr_m5   = float(bar["atr"])

        if any(pd.isna(v) for v in [ema_fast, ema_slow, rsi, hist, stoch_k, stoch_d, atr_m5]):
            continue

        if atr_m5 < M5_ATR_MIN:
            continue

        if direction == "BUY":
            stoch_ok = stoch_k > stoch_d and stoch_k < 80
            # A: EMA8 crosses above EMA21
            if ema_fast > ema_slow and prev_ef <= prev_es and 52 < rsi < 75 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross", "atr_m5": atr_m5}
                continue
            # C: MACD histogram flips positive
            if hist > 0 and prev_h <= 0 and close > ema_slow and 52 < rsi < 72 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip", "atr_m5": atr_m5}
                continue

        elif direction == "SELL":
            stoch_ok = stoch_k < stoch_d and stoch_k > 20
            # A: EMA8 crosses below EMA21
            if ema_fast < ema_slow and prev_ef >= prev_es and 25 < rsi < 48 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross", "atr_m5": atr_m5}
                continue
            # C: MACD histogram flips negative
            if hist < 0 and prev_h >= 0 and close < ema_slow and 28 < rsi < 48 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip", "atr_m5": atr_m5}
                continue

        # Pattern D — HA pullback: 3 trend candles → 1 pullback → resumption
        t1 = window.iloc[i - 4]
        t2 = window.iloc[i - 3]
        t3 = window.iloc[i - 2]
        pb = prev

        ha_cols = ("ha_close", "ha_open", "ha_high", "ha_low")
        if any(pd.isna(bar.get(c)) for c in ha_cols):
            continue
        if any(pd.isna(pb.get(c)) or pd.isna(t1.get(c)) or
               pd.isna(t2.get(c)) or pd.isna(t3.get(c)) for c in ha_cols):
            continue

        ha_c  = float(bar["ha_close"]); ha_o  = float(bar["ha_open"])
        pb_hc = float(pb["ha_close"]);  pb_ho = float(pb["ha_open"])
        t1_hc = float(t1["ha_close"]);  t1_ho = float(t1["ha_open"])
        t2_hc = float(t2["ha_close"]);  t2_ho = float(t2["ha_open"])
        t3_hc = float(t3["ha_close"]);  t3_ho = float(t3["ha_open"])

        if direction == "BUY":
            trend_ok  = t1_hc > t1_ho and t2_hc > t2_ho and t3_hc > t3_ho
            pb_ok     = pb_hc < pb_ho
            resume_ok = ha_c > ha_o
            if trend_ok and pb_ok and resume_ok:
                last_entry = {
                    "price":            float(bar["open"]),
                    "bar_time":         str(bar.name),
                    "pattern":          "D-ha-pullback",
                    "pullback_extreme": float(pb["ha_low"]),
                    "atr_m5":           atr_m5,
                }
        elif direction == "SELL":
            trend_ok  = t1_hc < t1_ho and t2_hc < t2_ho and t3_hc < t3_ho
            pb_ok     = pb_hc > pb_ho
            resume_ok = ha_c < ha_o
            if trend_ok and pb_ok and resume_ok:
                last_entry = {
                    "price":            float(bar["open"]),
                    "bar_time":         str(bar.name),
                    "pattern":          "D-ha-pullback",
                    "pullback_extreme": float(pb["ha_high"]),
                    "atr_m5":           atr_m5,
                }

        # Pattern E — Supertrend flip aligned with bias
        st_flip  = bar.get("st_flip")
        st_trend = bar.get("st_trend")
        if pd.isna(st_flip) or pd.isna(st_trend):
            continue
        if bool(st_flip):
            if direction == "BUY" and int(st_trend) == 1:
                last_entry = {"price": close, "bar_time": str(bar.name),
                              "pattern": "E-supertrend-flip", "atr_m5": atr_m5}
            elif direction == "SELL" and int(st_trend) == -1:
                last_entry = {"price": close, "bar_time": str(bar.name),
                              "pattern": "E-supertrend-flip", "atr_m5": atr_m5}

    return last_entry


def compute_sl_tp(
    entry_result: dict, bias: str, atr: float, spread: float, pv: float
) -> Optional[tuple[float, float, float]]:
    """Return (entry_p, sl, tp) or None if R:R is too low to trade."""
    ep      = entry_result["price"]
    pattern = entry_result.get("pattern", "")

    if pattern == "D-ha-pullback":
        extreme     = entry_result["pullback_extreme"]
        entry_p     = ep + spread if bias == "BUY" else ep - spread
        raw_sl_pips = abs(entry_p - extreme) / pv + HA_SL_BUFFER_PIPS
        sl_pips     = max(HA_SL_MIN_PIPS, min(HA_SL_MAX_PIPS, raw_sl_pips))
        sl_dist     = sl_pips * pv
        if bias == "BUY":
            sl = entry_p - sl_dist
            tp = entry_p + atr * ATR_TP_MULT
        else:
            sl = entry_p + sl_dist
            tp = entry_p - atr * ATR_TP_MULT
        if abs(tp - entry_p) / pv / sl_pips < HA_MIN_RR:
            return None
        return entry_p, sl, tp

    sl_pips = max(HA_SL_MIN_PIPS, min(HA_SL_MAX_PIPS, atr * ATR_TRAIL_MULT / pv))
    sl_dist = sl_pips * pv
    if bias == "BUY":
        entry_p = ep + spread
        sl      = entry_p - sl_dist
        tp      = entry_p + atr * ATR_TP_MULT
    else:
        entry_p = ep - spread
        sl      = entry_p + sl_dist
        tp      = entry_p - atr * ATR_TP_MULT
    return entry_p, sl, tp


def build_signal(h1_bias: dict, entry: Optional[dict], symbol: str = "EURJPY",
                 spread_pips: float = 0.0) -> Signal:
    """
    Combine the 1h bias and the 5m entry trigger into a Signal dataclass.
    Returns a FLAT signal if direction is FLAT, no entry was found, or R:R < HA_MIN_RR.
    """
    direction = h1_bias["direction"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    atr       = h1_bias["atr"]
    pv        = pip_value(symbol)

    if direction == "FLAT" or entry is None:
        reason = "No 1h trend alignment" if direction == "FLAT" else "No 5m entry trigger"
        return Signal(
            timestamp=now_str, direction="FLAT",
            entry_price=None, stop_loss=None, take_profit=None,
            atr=round(atr, 5),
            h1_macd_hist=round(h1_bias["macd_hist"], 6),
            h1_rsi=round(h1_bias["h1_rsi"], 1),
            h1_trend=h1_bias["trend"],
            entry_basis=reason,
            risk_pips=None, reward_pips=None, rr_ratio=None,
        )

    ep      = entry["price"]
    pattern = entry.get("pattern", "")
    ep_adj  = ep + spread_pips * pv if direction == "BUY" else ep - spread_pips * pv

    if pattern == "D-ha-pullback":
        extreme     = entry["pullback_extreme"]
        raw_sl_pips = abs(ep_adj - extreme) / pv + HA_SL_BUFFER_PIPS
        sl_pips     = max(HA_SL_MIN_PIPS, min(HA_SL_MAX_PIPS, raw_sl_pips))
        sl_dist     = sl_pips * pv
        if direction == "BUY":
            sl = ep_adj - sl_dist
            tp = ep_adj + atr * ATR_TP_MULT
        else:
            sl = ep_adj + sl_dist
            tp = ep_adj - atr * ATR_TP_MULT
        risk_pips   = sl_pips
        reward_pips = abs(tp - ep_adj) / pv
        rr          = reward_pips / risk_pips if risk_pips > 0 else 0

        if rr < HA_MIN_RR:
            return Signal(
                timestamp=now_str, direction="FLAT",
                entry_price=None, stop_loss=None, take_profit=None,
                atr=round(atr, 5),
                h1_macd_hist=round(h1_bias["macd_hist"], 6),
                h1_rsi=round(h1_bias["h1_rsi"], 1),
                h1_trend=h1_bias["trend"],
                entry_basis=f"D-ha-pullback suppressed: R:R {rr:.2f} < {HA_MIN_RR} minimum",
                risk_pips=None, reward_pips=None, rr_ratio=None,
            )
    else:
        sl_pips = max(HA_SL_MIN_PIPS, min(HA_SL_MAX_PIPS, atr * ATR_TRAIL_MULT / pv))
        sl_dist = sl_pips * pv
        if direction == "BUY":
            sl = ep_adj - sl_dist
            tp = ep_adj + atr * ATR_TP_MULT
        else:
            sl = ep_adj + sl_dist
            tp = ep_adj - atr * ATR_TP_MULT
        risk_pips   = sl_pips
        reward_pips = abs(tp - ep_adj) / pv
        rr          = reward_pips / risk_pips if risk_pips > 0 else 0

    pattern_labels = {
        "A-ema-cross":      "5m EMA8/21 cross",
        "C-macd-flip":      "5m MACD flip",
        "D-ha-pullback":    "5m HA pullback",
        "E-supertrend-flip":"5m Supertrend flip",
    }
    label = pattern_labels.get(pattern, pattern)
    basis = f"1h {h1_bias['trend']}, {label} @ {entry['bar_time']}"

    return Signal(
        timestamp=now_str,
        direction=direction,
        entry_price=round(ep_adj, 5),
        stop_loss=round(sl, 5),
        take_profit=round(tp, 5),
        atr=round(atr, 5),
        h1_macd_hist=round(h1_bias["macd_hist"], 6),
        h1_rsi=round(h1_bias["h1_rsi"], 1),
        h1_trend=h1_bias["trend"],
        entry_basis=basis,
        risk_pips=round(risk_pips, 1),
        reward_pips=round(reward_pips, 1),
        rr_ratio=round(rr, 2),
    )
