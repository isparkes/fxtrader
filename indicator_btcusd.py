"""
BTCUSD Scalper
==============
Same two-timeframe strategy as the FX pairs, adapted for Bitcoin spot price.

Key differences from the FX indicator modules:
  - pip_value() returns 1.0  — one "pip" = one US dollar.
  - M5_ATR_MIN = 50.0        — require at least $50 of 5m ATR before trading.
  - HA stop clamps are in dollars ($200–$800) not FX pips.
  - No session gate           — BTC trades 24/7; use_session is ignored.
  - Spread quoted in dollars  — PAIR_CONFIG spread_scalp = 20 ($20).

Everything else (Pattern A/C/D logic, trailing stop, 4h EMA gate) is identical
to indicator_eurusd.py so results are directly comparable.
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf
from ta.trend import MACD, EMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange

logging.basicConfig(level=logging.WARNING)

SYMBOL = "BTC-USD"


def pip_value(symbol: str) -> float:
    """For BTC-USD one pip = $1."""
    return 1.0


# ── Tunable parameters ────────────────────────────────────────────────────────
# 1h trend
H1_EMA_TREND   = 50
H1_MACD_FAST   = 12
H1_MACD_SLOW   = 26
H1_MACD_SIGNAL = 9
H1_RSI_PERIOD  = 14

# 4h trend filter (Measure 4)
H4_EMA_PERIOD = 22

# 5m entry
M5_EMA_FAST     = 8
M5_EMA_SLOW     = 21
M5_RSI_PERIOD   = 7
M5_STOCH_PERIOD = 14
M5_STOCH_SMOOTH = 3
M5_ATR_MIN      = 50.0    # $50 minimum 5m ATR — skip dead/illiquid periods

# Risk — patterns A and C
ATR_PERIOD  = 14
ATR_SL_MULT = 0.4
ATR_TP_MULT = 3.0

# Pattern D — HA pullback stop parameters (dollar-denominated, pv=1.0)
HA_SL_BUFFER_PIPS = 50    # $50 buffer beyond the pullback extreme
HA_SL_MIN_PIPS    = 200   # floor: $200 minimum stop
HA_SL_MAX_PIPS    = 800   # ceiling: $800 maximum stop (~1% at $80k)
HA_MIN_RR         = 1.5

# Trailing stop — phase-1 breakeven trigger
TRAIL_ACTIVATE_FRAC = 0.8

# Session — BTC trades 24/7; these values are here for API compatibility
# but use_session is always treated as False in find_m5_entry.
SESSION_START_UTC = 0
SESSION_END_UTC   = 24
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Signal:
    timestamp: str
    direction: str
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
    close = df["close"]

    macd_ind = MACD(close=close, window_fast=H1_MACD_FAST,
                    window_slow=H1_MACD_SLOW, window_sign=H1_MACD_SIGNAL)
    df["macd_hist"] = macd_ind.macd_diff()

    df["ema_trend"] = EMAIndicator(close=close, window=H1_EMA_TREND).ema_indicator()

    atr = AverageTrueRange(high=df["high"], low=df["low"], close=close, window=ATR_PERIOD)
    df["atr"] = atr.average_true_range()

    df["rsi"] = RSIIndicator(close=close, window=H1_RSI_PERIOD).rsi()

    return df


def compute_m5_indicators(df: pd.DataFrame) -> pd.DataFrame:
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

    return df


def assess_h1_bias(df: pd.DataFrame, df_4h: Optional[pd.DataFrame] = None) -> dict:
    last = df.iloc[-1]

    close     = float(last["close"])
    ema_trend = float(last["ema_trend"])
    macd_hist = float(last["macd_hist"])
    atr       = float(last["atr"])
    h1_rsi    = float(last["rsi"])

    above = close > ema_trend
    below = close < ema_trend
    bull  = macd_hist > 0 and h1_rsi > 50
    bear  = macd_hist < 0 and h1_rsi < 50

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
    Same Pattern A / C / D logic as the FX modules.
    Session gate is disabled for BTC regardless of use_session.
    """
    if direction == "FLAT":
        return None

    window = df5m.iloc[-30:].copy()
    last_entry = None

    for i in range(4, len(window)):
        bar  = window.iloc[i]
        prev = window.iloc[i - 1]

        # BTC trades 24/7 — no session filter applied
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
            if ema_fast > ema_slow and prev_ef <= prev_es and 52 < rsi < 75 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross", "atr_m5": atr_m5}
                continue
            if hist > 0 and prev_h <= 0 and close > ema_slow and 52 < rsi < 72 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip", "atr_m5": atr_m5}
                continue

        elif direction == "SELL":
            stoch_ok = stoch_k < stoch_d and stoch_k > 20
            if ema_fast < ema_slow and prev_ef >= prev_es and 25 < rsi < 48 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross", "atr_m5": atr_m5}
                continue
            if hist < 0 and prev_h >= 0 and close < ema_slow and 28 < rsi < 48 and stoch_ok:
                last_entry = {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip", "atr_m5": atr_m5}
                continue

        # Pattern D — HA pullback
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

    return last_entry


def compute_sl_tp(
    entry_result: dict, bias: str, atr: float, spread: float, pv: float
) -> Optional[tuple[float, float, float]]:
    """Return (entry_p, sl, tp) or None if R:R is too low."""
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

    if bias == "BUY":
        entry_p = ep + spread
        sl      = entry_p - atr * ATR_SL_MULT
        tp      = entry_p + atr * ATR_TP_MULT
    else:
        entry_p = ep - spread
        sl      = entry_p + atr * ATR_SL_MULT
        tp      = entry_p - atr * ATR_TP_MULT
    return entry_p, sl, tp


def build_signal(h1_bias: dict, entry: Optional[dict], symbol: str = SYMBOL) -> Signal:
    direction = h1_bias["direction"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    atr       = h1_bias["atr"]
    pv        = pip_value(symbol)

    if direction == "FLAT" or entry is None:
        reason = "No 1h trend alignment" if direction == "FLAT" else "No 5m entry trigger"
        return Signal(
            timestamp=now_str, direction="FLAT",
            entry_price=None, stop_loss=None, take_profit=None,
            atr=round(atr, 2),
            h1_macd_hist=round(h1_bias["macd_hist"], 2),
            h1_rsi=round(h1_bias["h1_rsi"], 1),
            h1_trend=h1_bias["trend"],
            entry_basis=reason,
            risk_pips=None, reward_pips=None, rr_ratio=None,
        )

    ep      = entry["price"]
    pattern = entry.get("pattern", "")

    if pattern == "D-ha-pullback":
        extreme     = entry["pullback_extreme"]
        raw_sl_pips = abs(ep - extreme) / pv + HA_SL_BUFFER_PIPS
        sl_pips     = max(HA_SL_MIN_PIPS, min(HA_SL_MAX_PIPS, raw_sl_pips))
        sl_dist     = sl_pips * pv
        if direction == "BUY":
            sl = ep - sl_dist
            tp = ep + atr * ATR_TP_MULT
        else:
            sl = ep + sl_dist
            tp = ep - atr * ATR_TP_MULT
        risk_pips   = sl_pips
        reward_pips = abs(tp - ep) / pv
        rr          = reward_pips / risk_pips if risk_pips > 0 else 0

        if rr < HA_MIN_RR:
            return Signal(
                timestamp=now_str, direction="FLAT",
                entry_price=None, stop_loss=None, take_profit=None,
                atr=round(atr, 2),
                h1_macd_hist=round(h1_bias["macd_hist"], 2),
                h1_rsi=round(h1_bias["h1_rsi"], 1),
                h1_trend=h1_bias["trend"],
                entry_basis=f"D-ha-pullback suppressed: R:R {rr:.2f} < {HA_MIN_RR} minimum",
                risk_pips=None, reward_pips=None, rr_ratio=None,
            )
    else:
        if direction == "BUY":
            sl = ep - atr * ATR_SL_MULT
            tp = ep + atr * ATR_TP_MULT
        else:
            sl = ep + atr * ATR_SL_MULT
            tp = ep - atr * ATR_TP_MULT
        risk_pips   = abs(ep - sl) / pv
        reward_pips = abs(tp - ep) / pv
        rr          = reward_pips / risk_pips if risk_pips > 0 else 0

    pattern_labels = {
        "A-ema-cross":   "5m EMA8/21 cross",
        "C-macd-flip":   "5m MACD flip",
        "D-ha-pullback": "5m HA pullback",
    }
    label = pattern_labels.get(pattern, pattern)
    basis = f"1h {h1_bias['trend']}, {label} @ {entry['bar_time']}"

    return Signal(
        timestamp=now_str,
        direction=direction,
        entry_price=round(ep, 2),
        stop_loss=round(sl, 2),
        take_profit=round(tp, 2),
        atr=round(atr, 2),
        h1_macd_hist=round(h1_bias["macd_hist"], 2),
        h1_rsi=round(h1_bias["h1_rsi"], 1),
        h1_trend=h1_bias["trend"],
        entry_basis=basis,
        risk_pips=round(risk_pips, 1),
        reward_pips=round(reward_pips, 1),
        rr_ratio=round(rr, 2),
    )
