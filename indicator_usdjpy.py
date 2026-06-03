"""
USDJPY Scalper
==============
Generates intraday scalping signals targeting 8-15 pip moves.

Overview
--------
The strategy uses a two-timeframe approach: the 1h chart sets the directional
bias and the 5m chart finds precise entry timing within that bias. Signals are
only generated during the London/NY overlap session (07:00-16:00 UTC) where
liquidity and volatility are highest.

──────────────────────────────────────────────────────────────────────────────
TREND FILTER  (1h bars — must pass ALL THREE to open a BUY or SELL bias)
──────────────────────────────────────────────────────────────────────────────

1. EMA50 side
   Price must be above EMA50 for BUY, below for SELL.
   This anchors every trade to the prevailing medium-term trend.

2. MACD histogram — sign + building
   The 1h MACD histogram (12/26/9) must be positive AND larger than the
   previous bar for BUY; negative AND smaller (more negative) for SELL.
   Requiring it to be building, not just on the right side, means we only
   trade when momentum is accelerating — not fading.

3. RSI(14) above / below 50
   The 1h RSI must be above 50 for BUY, below 50 for SELL. This is a
   second momentum confirmation independent of MACD. A MACD that is
   technically positive but accompanied by sub-50 RSI often means the
   move is exhausted; this gate filters those out.

──────────────────────────────────────────────────────────────────────────────
ENTRY FILTERS  (5m bars — evaluated once the 1h bias is active)
──────────────────────────────────────────────────────────────────────────────

Pre-checks applied to every bar before pattern evaluation:

  • Session gate     — bar timestamp must fall within 07:00–16:00 UTC.
  • ATR floor        — 5m ATR(14) must be ≥ 0.0002 (2 pips). Skips entries
                       when the market is too compressed to reach the target
                       before reversing. Effectively a volatility on/off switch.

Pattern A — EMA8/21 cross
  BUY:  EMA8 crosses above EMA21 on the current bar (was below on the previous
        bar). Confirms local momentum has flipped bullish.
  SELL: EMA8 crosses below EMA21. Local momentum flipped bearish.

  Additional guards:
    - RSI(7) must be 52–75 for BUY (momentum present, not overbought)
    - RSI(7) must be 25–48 for SELL (momentum present, not oversold)
    - Stochastic %K must be above %D and below 80 for BUY (aligned, room to run)
    - Stochastic %K must be below %D and above 20 for SELL

Pattern C — MACD histogram flip
  BUY:  5m MACD histogram (6/13/4) crosses from negative to positive while
        price is above EMA21. The short-period MACD is deliberately faster
        than the 1h version — it catches micro-momentum shifts.
  SELL: 5m MACD histogram crosses from positive to negative while price is
        below EMA21.

  Additional guards: same RSI and Stochastic conditions as Pattern A.

Note: an earlier "Pattern B" (EMA21 wick bounce) was removed during development
because it fired on virtually every minor retracement, producing too many false
entries without a meaningful edge.

──────────────────────────────────────────────────────────────────────────────
RISK MANAGEMENT
──────────────────────────────────────────────────────────────────────────────

Stop loss:   ATR(14) × 0.4  (~4–8 pips). Set at entry, never widened.

Take profit: ATR(14) × 3.0  Wide ceiling (~30+ pips). Rarely the binding
             exit — the trailing stop typically closes the trade first.
             Kept as an absolute cap against sudden gap moves.

Trailing stop — two phases:

  Phase 1 (hard stop → breakeven):
    Once price reaches 80% of the initial TP distance the stop is moved to
    entry price, dropping risk to zero (minus spread). The activation is
    intentionally late — firing too early converts near-winners into
    breakeven exits when normal noise pulls price back before TP.

  Phase 2 (breakeven → active trail):
    Once at breakeven the stop trails ATR × 0.4 behind the running best
    price with no fixed ceiling. Winners run until the trail is hit.
    This asymmetry — capped loss, uncapped win — is the core of the edge.

Cooldown:    No new entry for 30 minutes (6 × 5m bars) after a loss.
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

# Daily regime gate — skip when daily ADX < threshold (ranging market)
DAILY_ADX_MIN = 0   # exempt — Supertrend/HA patterns self-select trending conditions

# Day-of-week gate — blocked weekdays (0=Mon … 4=Fri)
BLOCKED_DAYS: frozenset[int] = frozenset({4})   # Friday: PF 1.27 vs 2.86 overall

# 5m entry
M5_EMA_FAST      = 8
M5_EMA_SLOW      = 21
M5_RSI_PERIOD    = 7
M5_STOCH_PERIOD  = 14
M5_STOCH_SMOOTH  = 3
M5_ATR_MIN       = 0.02     # 2 pips (JPY: pip=0.01, so 2 pips = 0.02) — don't scalp a dead market

# Risk — tight scalper targets
ATR_PERIOD        = 14
ATR_TRAIL_MULT       = 0.4   # trailing stop distance: ATR × 0.4 behind best price
ATR_TP_MULT       = 3.0   # wide ceiling — trailing stop usually exits first

# Pattern D — HA pullback stop parameters
HA_SL_BUFFER_PIPS = 2     # pips added beyond the pullback extreme
HA_SL_MIN_PIPS    = 7     # floor: stop can't be tighter than this
HA_SL_MAX_PIPS    = 12    # ceiling: stop can't be wider than this
HA_MIN_RR         = 1.5   # suppress signal if clamped R:R falls below this

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
    Add trend-context indicators to a bar DataFrame (designed for 1h, also
    used on 4h resampled bars in long-mode backtesting).

    Columns added:
        macd_hist  — MACD histogram (12/26/9). Positive = bullish momentum,
                     negative = bearish. The strategy requires this to be
                     building (larger than the previous bar) before trading.
        ema_trend  — EMA(50). Price must be on the correct side of this line
                     for the corresponding direction to be active.
        atr        — ATR(14). Used to size stop-loss and take-profit levels.
        rsi        — RSI(14). Must be above 50 for BUY bias, below 50 for
                     SELL bias — a second momentum gate independent of MACD.
    """
    close = df["close"]

    macd_ind = MACD(close=close, window_fast=H1_MACD_FAST,
                    window_slow=H1_MACD_SLOW, window_sign=H1_MACD_SIGNAL)
    df["macd_hist"] = macd_ind.macd_diff()

    ema = EMAIndicator(close=close, window=H1_EMA_TREND)
    df["ema_trend"] = ema.ema_indicator()

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
    basic_upper = hl2 + multiplier * atr_vals   # dn in Pine Script
    basic_lower = hl2 - multiplier * atr_vals   # up in Pine Script

    n     = len(df)
    upper = basic_upper.copy()
    lower = basic_lower.copy()
    trend = np.ones(n, dtype=int)

    for i in range(1, n):
        # Lower band ratchets upward — only moves when prior close was above it
        if close_v[i - 1] > lower[i - 1]:
            lower[i] = max(basic_lower[i], lower[i - 1])
        # Upper band ratchets downward — only moves when prior close was below it
        if close_v[i - 1] < upper[i - 1]:
            upper[i] = min(basic_upper[i], upper[i - 1])
        # Flip to uptrend on a close above the prior upper band
        if trend[i - 1] == -1 and close_v[i] > upper[i - 1]:
            trend[i] = 1
        # Flip to downtrend on a close below the prior lower band
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
    Add entry-timing indicators to a bar DataFrame (designed for 5m, also
    used on 1h bars in long-mode backtesting).

    Columns added:
        ema_fast   — EMA(8). Compared against ema_slow to detect crossovers.
        ema_slow   — EMA(21). Price must be above this for BUY entries,
                     below for SELL entries.
        rsi        — RSI(7). Short period for responsiveness. Must be in the
                     52-75 band for BUY, 25-48 for SELL.
        macd_hist  — MACD histogram (6/13/4). Faster settings than the trend
                     MACD to catch micro-momentum shifts. A cross of zero
                     while price is on the correct side of ema_slow triggers
                     Pattern C entries.
        stoch_k    — Stochastic %K (14,3). Must be above stoch_d and below
                     80 for BUY; below stoch_d and above 20 for SELL.
        stoch_d    — Stochastic %D (3-bar smoothed signal line).
        atr        — ATR(14). Used as a volatility gate: entries are skipped
                     when atr < M5_ATR_MIN (market too flat to reach target).
        st_trend   — Supertrend(7, 2.0) direction: 1 uptrend, -1 downtrend.
        st_line    — Active Supertrend band level (dynamic S/R).
        st_flip    — True on the bar Supertrend changes direction (Pattern E).
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

    # Heikin-Ashi for Pattern D
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

    df = compute_supertrend(df, period=10, multiplier=3.0)
    return df

def assess_h1_bias(df: pd.DataFrame, df_4h: Optional[pd.DataFrame] = None,
                   df_1d: Optional[pd.DataFrame] = None) -> dict:
    """
    Evaluate the trend gates on the last completed 1h bar and return
    the directional bias together with the raw indicator values.

    Uses iloc[-1] (the current forming bar) so the bias reflects live price action.
    Returns direction "FLAT" unless all three gates pass simultaneously:
        1. Price side of EMA50
        2. MACD histogram positive/negative
        3. RSI(14) above/below 50

    Measure 4 — 4h agreement gate (optional):
        If df_4h is provided, the 4h close must be on the same side of the
        4h EMA50 as the 1h direction. Trades where 1h and 4h conflict are
        suppressed as FLAT.

    Returns a dict with keys:
        direction  — "BUY", "SELL", or "FLAT"
        macd_hist  — raw MACD histogram value
        h1_rsi     — raw RSI value
        atr        — raw ATR value (used for SL/TP sizing)
        trend      — human-readable EMA50 position string
        close      — last completed bar close price
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
        "direction":  direction,
        "macd_hist":  macd_hist,
        "h1_rsi":     h1_rsi,
        "atr":        atr,
        "trend":      "above EMA50" if above else "below EMA50",
        "close":      close,
    }

def find_m5_entry(df5m: pd.DataFrame, direction: str,
                   use_session: bool = True) -> Optional[dict]:
    """
    Scan the last 24 5m bars (2 hours) for a scalp entry trigger.
    Direction is set by 1h bias — entries only fire when aligned with it.

    Pattern A: EMA8 crosses EMA21 in trend direction, RSI showing momentum
    Pattern C: 5m MACD histogram flips in trend direction, RSI confirming
    (Pattern B — EMA21 wick bounce — removed: too noisy for scalping)

    Returns the most recent (latest) matching bar, not the first.
    """
    if direction == "FLAT":
        return None

    window = df5m.iloc[-30:].copy()   # extended for Pattern D's 5-bar lookback
    last_entry = None

    for i in range(4, len(window)):
        bar  = window.iloc[i]
        prev = window.iloc[i - 1]

        # Session filter — skip bars outside London/NY overlap
        if use_session:
            ts = bar.name
            if hasattr(ts, "hour"):
                hour = ts.tz_convert("UTC").hour if getattr(ts, "tzinfo", None) else ts.hour
                if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
                    continue

        close  = float(bar["close"])
        atr_m5 = float(bar["atr"])

        if pd.isna(atr_m5):
            continue

        if atr_m5 < M5_ATR_MIN:
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

        # Pattern E — Supertrend flip aligned with trend direction
        if not pd.isna(bar.get("st_trend")) and not pd.isna(prev.get("st_trend")):
            st_now  = int(bar["st_trend"])
            st_prev = int(prev["st_trend"])
            if direction == "BUY" and st_now == 1 and st_prev == -1:
                last_entry = {"price": close, "bar_time": str(bar.name),
                              "pattern": "E-supertrend-flip", "atr_m5": atr_m5}
            elif direction == "SELL" and st_now == -1 and st_prev == 1:
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

def build_signal(h1_bias: dict, entry: Optional[dict], symbol: str = "EURUSD", spread_pips: float = 0.0) -> Signal:
    """
    Combine the 1h bias and the 5m entry trigger into a Signal dataclass.

    If direction is FLAT or no entry was found, returns a FLAT signal with
    the trend indicator values filled in for diagnostic purposes.

    Otherwise computes:
        stop_loss   = entry ± ATR × ATR_TRAIL_MULT
        take_profit = entry ± ATR × ATR_TP_MULT  (wide ceiling)
        risk_pips / reward_pips / rr_ratio derived from the above
    """
    direction = h1_bias["direction"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    atr       = h1_bias["atr"]

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
    pv      = pip_value(symbol)
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
        if rr < HA_MIN_RR:
            return Signal(
                timestamp=now_str, direction="FLAT",
                entry_price=None, stop_loss=None, take_profit=None,
                atr=round(atr, 5),
                h1_macd_hist=round(h1_bias["macd_hist"], 6),
                h1_rsi=round(h1_bias["h1_rsi"], 1),
                h1_trend=h1_bias["trend"],
                entry_basis=f"{pattern} suppressed: R:R {rr:.2f} < {HA_MIN_RR} minimum",
                risk_pips=None, reward_pips=None, rr_ratio=None,
            )

    pattern_labels = {
        "A-ema-cross":       "5m EMA8/21 cross",
        "B-ema-bounce":      "5m EMA21 bounce",
        "C-macd-flip":       "5m MACD flip",
        "D-ha-pullback":     "5m HA pullback",
        "E-supertrend-flip": "5m Supertrend flip",
    }
    label = pattern_labels.get(pattern, pattern)
    basis = f"1h {h1_bias['trend']}, {label} @ {entry['bar_time']}"

    return Signal(
        timestamp=now_str,
        direction=direction,
        entry_price=round(ep, 5),
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

