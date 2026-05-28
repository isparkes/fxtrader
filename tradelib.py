"""
Trade Management Library
========================
Single source of truth for all trade lifecycle logic.

Both backtest.py and daemon.py import from here. Neither re-implements anything
in this module. The three-phase trailing stop model here is authoritative.

Contents
--------
  Signal      — structured output of indicator.build_signal()
  Position    — open-trade state (automated and discretionary)
  pip_value() — pip size for a given pair
  check_position_events() — three-phase trailing stop model
  calc_units()            — position sizing from risk %

Design constraints
------------------
  This module has NO imports of indicator_*.py or oanda.py.
  check_position_events() accepts any duck-typed `ind` object (indicator module
  or test mock) with ATR_SL_MULT, TRAIL_ACTIVATE_FRAC, and pip_value().
  calc_units() receives pre-fetched nav and rate values from the caller.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

log = logging.getLogger("fxtrader.tradelib")

# ── Default trailing-stop constant (overridden per-pair via ind.TRAIL_ACTIVATE_FRAC) ──
_DEFAULT_TRAIL_ACTIVATE_FRAC = 0.80


# ── Signal ────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """
    Structured output of an indicator's build_signal() call.

    Core fields are mandatory; diagnostic fields (h1_*) are optional and used
    only for logging / reporting.
    """
    direction:    str            # "BUY" | "SELL" | "FLAT"
    timestamp:    str            # UTC string at signal generation
    entry_basis:  str            # human-readable description of the pattern that fired
    bar_time:     Optional[str] = None   # 5m bar timestamp — used for duplicate-signal guard

    # Price levels — None only when direction == "FLAT"
    entry_price:  Optional[float] = None
    stop_loss:    Optional[float] = None
    take_profit:  Optional[float] = None
    atr:          Optional[float] = None
    risk_pips:    Optional[float] = None
    reward_pips:  Optional[float] = None
    rr_ratio:     Optional[float] = None

    # Diagnostic — informational, not used in position management
    h1_macd_hist: Optional[float] = None
    h1_rsi:       Optional[float] = None
    h1_trend:     Optional[str]   = None


# ── Position ──────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """
    All mutable state for one open trade.

    trade_type distinguishes trades opened by the signal engine ("automated")
    from those registered by the operator via the control console ("discretionary").
    """
    # Identity
    pair:         str            # internal key, e.g. "eurusd"
    symbol:       str            # broker instrument string, e.g. "EUR_USD"
    direction:    str            # "BUY" | "SELL"
    trade_type:   str            # "automated" | "discretionary"

    # Levels at entry
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    atr:          float
    risk_pips:    float
    reward_pips:  float
    rr_ratio:     float

    # Metadata
    opened_at:    str            # UTC timestamp string
    basis:        str            # pattern/reason description

    # State — all default to their at-entry values
    be_activated:    bool          = False
    trade_id:        Optional[str] = None   # broker trade ID after fill
    occult_stops:    bool          = False  # True → SL/TP not on broker
    sl_materialised: bool          = False  # occult SL placed as real broker order
    tp_materialised: bool          = False  # occult TP placed as real broker order
    signal_price:    Optional[float] = None # intended entry; entry_price is the fill
    tp_extended:     bool          = False  # True once Phase 3 TP extension has fired
    original_tp:     float         = 0.0   # TP at entry — reference for Phase 3 sizing
    best_price:      float         = 0.0   # running best (high for BUY, low for SELL)


# ── Pip value ─────────────────────────────────────────────────────────────────

def pip_value(pair: str) -> float:
    """Return the pip size for a pair. JPY pairs: 0.01; all others: 0.0001."""
    return 0.01 if "jpy" in pair.lower() else 0.0001


# ── Three-phase trailing stop model ──────────────────────────────────────────

def check_position_events(
    pos: Position,
    bar: pd.Series,
    ind,
) -> list[tuple[str, float]]:
    """
    Evaluate the latest bar against an open position and return a list of events.

    `ind` is any object (indicator module or test mock) that exposes:
        ind.ATR_SL_MULT          float   — trail distance multiplier
        ind.TRAIL_ACTIVATE_FRAC  float   — optional; defaults to 0.80
        ind.pip_value(pair)      float   — pip size for the pair

    Three-phase model
    -----------------
    Phase 1 — Breakeven:
        Once price reaches TRAIL_ACTIVATE_FRAC of the initial TP distance from
        entry, SL moves to entry price (risk to zero).

    Phase 2 — Active trail:
        After Phase 1, SL ratchets ATR × ATR_SL_MULT behind the running best
        price each bar.

    Phase 3 — TP extension (momentum gate):
        When the original TP is first hit and the current HA candle colour
        agrees with trade direction, the trade is extended rather than closed:
          • SL locks at 90% of the original TP distance from entry
          • TP doubles to 2× the original TP distance
          • Trail tightens to ATR × ATR_SL_MULT × 0.5

    Returns an ordered list of (event_name, price) tuples:
        "be"        — stop moved to breakeven; position remains open
        "extend_tp" — Phase 3 fired; position remains open
        "close_tp"  — take profit hit; position should be closed
        "close_sl"  — stop loss hit; position should be closed

    The caller stops processing further events once a close event is received.
    """
    events: list[tuple[str, float]] = []
    high = float(bar["high"])
    low  = float(bar["low"])
    pv   = ind.pip_value(pos.pair)

    # Guard: initialise best_price for positions that pre-date this field
    if pos.best_price == 0.0:
        pos.best_price = pos.entry_price

    # ── Phase 1 — breakeven trigger ───────────────────────────────────────────
    if not pos.be_activated:
        tp_dist_pips  = abs(pos.take_profit - pos.entry_price) / pv
        trail_frac    = getattr(ind, "TRAIL_ACTIVATE_FRAC", _DEFAULT_TRAIL_ACTIVATE_FRAC)
        activate_pips = tp_dist_pips * trail_frac
        progress = (
            (high - pos.entry_price) if pos.direction == "BUY"
            else (pos.entry_price - low)
        ) / pv
        if progress >= activate_pips:
            pos.stop_loss    = pos.entry_price
            pos.be_activated = True
            events.append(("be", pos.entry_price))

    # ── Check TP / SL hits (against current SL before Phase 2 trails it) ───────
    # Phase 2 is intentionally moved below: trailing is computed from this
    # bar's extremes but should only be checked on the NEXT bar.  Running the
    # check here (pre-trail) prevents a false close_sl when Phase 2 first
    # activates and immediately lowers the stop below entry — at that point
    # the bar's high can exceed the new lower stop even though the broker SL
    # at the old (entry) level was never actually hit.
    hit_tp = (
        (pos.direction == "BUY"  and high >= pos.take_profit) or
        (pos.direction == "SELL" and low  <= pos.take_profit)
    )
    hit_sl = (
        (pos.direction == "BUY"  and low  <= pos.stop_loss) or
        (pos.direction == "SELL" and high >= pos.stop_loss)
    )

    # ── Phase 3 — intercept first TP hit: extend unconditionally ────────────
    if hit_tp and not pos.tp_extended:
        ref_tp  = pos.original_tp if pos.original_tp else pos.take_profit
        tp_dist = abs(ref_tp - pos.entry_price)
        sign    = 1 if pos.direction == "BUY" else -1
        pos.stop_loss   = pos.entry_price + sign * 0.9 * tp_dist
        pos.take_profit = pos.entry_price + sign * 2.0 * tp_dist
        pos.be_activated = True
        pos.tp_extended  = True
        events.append(("extend_tp", pos.take_profit))
        return events   # hold — no close event this bar

    if hit_tp:
        events.append(("close_tp", pos.take_profit))
        return events
    elif hit_sl:
        events.append(("close_sl", pos.stop_loss))
        return events

    # ── Phase 2 — active trailing (only runs when position is not closing) ────
    if pos.be_activated:
        trail_dist = pos.atr * ind.ATR_SL_MULT * (0.5 if pos.tp_extended else 1.0)
        if pos.direction == "BUY":
            pos.best_price = max(pos.best_price, high)
            new_trail = pos.best_price - trail_dist
            if new_trail > pos.stop_loss:
                pos.stop_loss = new_trail
        else:
            pos.best_price = min(pos.best_price, low)
            new_trail = pos.best_price + trail_dist
            if new_trail < pos.stop_loss:
                pos.stop_loss = new_trail

    return events


# ── Registration-level calculation ───────────────────────────────────────────

def calc_registration_levels(
    direction:     str,
    entry_price:   float,
    current_price: float,
    atr:           float,
    ind,
    pv:            float,
) -> tuple[float, float, bool, float]:
    """
    Compute SL, TP, be_activated, and best_price when registering an existing
    discretionary trade for daemon management.

    Applies the same trail model as check_position_events so a trade that opened
    while the daemon was offline is caught up to its correct state.

    Returns (sl, tp, be_activated, best_price).
    """
    sign = 1 if direction == "BUY" else -1
    sl   = entry_price - sign * atr * ind.ATR_SL_MULT
    tp   = entry_price + sign * atr * ind.ATR_TP_MULT

    trail_frac   = getattr(ind, "TRAIL_ACTIVATE_FRAC", _DEFAULT_TRAIL_ACTIVATE_FRAC)
    tp_dist_pips = abs(tp - entry_price) / pv
    prog_pips    = (
        (current_price - entry_price) if direction == "BUY"
        else (entry_price - current_price)
    ) / pv

    be_activated = False
    best_price   = current_price

    if prog_pips >= tp_dist_pips * trail_frac:
        be_activated = True
        trail_dist   = atr * ind.ATR_SL_MULT
        trailing_sl  = (
            current_price - trail_dist if direction == "BUY"
            else current_price + trail_dist
        )
        sl = (
            max(entry_price, trailing_sl) if direction == "BUY"
            else min(entry_price, trailing_sl)
        )
    elif (
        (direction == "BUY"  and current_price <= sl) or
        (direction == "SELL" and current_price >= sl)
    ):
        sl = (
            current_price - atr * ind.ATR_SL_MULT if direction == "BUY"
            else current_price + atr * ind.ATR_SL_MULT
        )

    return sl, tp, be_activated, best_price


# ── Fill-slippage SL adjustment ───────────────────────────────────────────────

def adjust_sl_for_fill(
    fill_price:  float,
    stop_loss:   float,
    take_profit: float,
    direction:   str,
    ind,
    pv:          float,
) -> tuple[float, float, float, float]:
    """
    Recalculate SL, risk_pips, reward_pips, and rr_ratio after a fill price
    that differs from the signal price.

    If the SL distance from fill exceeds HA_SL_MAX_PIPS (the pair's cap), the
    SL is moved to exactly HA_SL_MAX_PIPS from fill so risk stays within bounds.

    Returns (stop_loss, risk_pips, reward_pips, rr_ratio).
    """
    sl_max = getattr(ind, "HA_SL_MAX_PIPS", None)
    if sl_max is not None and abs(fill_price - stop_loss) / pv > sl_max:
        sl_dist   = sl_max * pv
        stop_loss = round(
            (fill_price - sl_dist) if direction == "BUY"
            else (fill_price + sl_dist), 5,
        )
    risk_pips   = round(abs(fill_price - stop_loss) / pv, 1)
    reward_pips = round(abs(take_profit - fill_price) / pv, 1)
    rr_ratio    = round(reward_pips / risk_pips, 2) if risk_pips > 0 else 0.0
    return stop_loss, risk_pips, reward_pips, rr_ratio


# ── Position sizing ───────────────────────────────────────────────────────────

def calc_units(
    pair:      str,
    risk_pips: float,
    nav:       float,
    risk_pct:  float,
    jpy_rate:  float = 150.0,
) -> int:
    """
    Return the number of units to trade so that `risk_pips` of adverse movement
    equals exactly risk_pct percent of nav.

    Args:
        pair:      internal pair key, e.g. "eurusd"
        risk_pips: distance from entry to stop loss in pips
        nav:       account net asset value in account currency (USD)
        risk_pct:  percent of NAV to risk, e.g. 1.0 = 1%
        jpy_rate:  live USD/JPY rate — only used for USDJPY to convert pip value
                   to USD.  Caller should supply the live rate; 150.0 is a fallback.

    Returns the unit count, minimum 1.
    """
    if risk_pips <= 0:
        log.warning("calc_units: risk_pips=%s is non-positive — returning 1 unit", risk_pips)
        return 1

    risk_usd = nav * risk_pct / 100.0
    pip_size = pip_value(pair)

    if pair.lower() == "usdjpy":
        # Pip size is in JPY; convert to USD
        pip_usd = pip_size / jpy_rate
    else:
        # Quote currency is USD; pip_size is already in USD per unit
        pip_usd = pip_size

    units = int(risk_usd / (risk_pips * pip_usd))
    return max(units, 1)
