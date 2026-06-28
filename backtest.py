"""
FX Scalper — Walk-forward backtest
====================================
Simulates the indicator strategy against OANDA historical data stored by
datalib.py.  All market data comes from the local OANDA parquet store.

Two modes:

  Default (scalp mode)
    Trend : H1 bars resampled from M1 (up to 90 days) — same data path as daemon
    Entry : M5 bars resampled from M1
    M1 within-bar simulation: SL/TP ordering resolved using 1-minute bars

  Long mode  (--long)
    Trend : H4 bars resampled from H1
    Entry : H1 bars  (up to 730 days stored)
    No M1 simulation (H1 bars used directly)

Both modes delegate all indicator logic to the pair's indicator module.
Position management uses a broker-native trailing stop: the stop trails at a
fixed distance (initial risk_pips × pip_value) from the best price seen since
entry.  TP/SL resolution is bar-by-bar (M1 in scalp mode); within a single M1
bar the order of TP vs trailing-SL hit is unresolvable.

Usage
-----
    python backtest.py                 # scalp mode, default pair (eurusd)
    python backtest.py --long          # long mode
    python backtest.py --pair usdjpy   # specific pair, scalp mode
    python backtest.py --all           # all active pairs, scalp mode
    python backtest.py --all --long    # all active pairs, long mode
    python backtest.py --seed          # seed data then run
    python backtest.py --by-day        # split results per trading day (Mon–Fri)
"""

import argparse
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from ta.trend import EMAIndicator
from rich.console import Console
from rich.table import Table
from rich import box

import datalib
import tradelib
import indicator_eurusd
import indicator_gbpusd
import indicator_usdjpy
import indicator_audusd
import indicator_eurjpy

# ── Active pairs ──────────────────────────────────────────────────────────────
# Pairs available for backtesting.  OANDA instrument strings are used only by
# datalib / oanda.py — not here.
PAIR_INDICATORS = {
    "eurusd": indicator_eurusd,
    "gbpusd": indicator_gbpusd,
    "usdjpy": indicator_usdjpy,
    "audusd": indicator_audusd,
    "eurjpy": indicator_eurjpy,   # candidate pair — not in live rotation yet
}

# Per-pair spread in pips (deducted from every trade's P&L)
PAIR_CONFIG: dict[str, dict] = {
    "eurusd": {"spread_scalp": 1.0, "spread_long": 0.8},
    "gbpusd": {"spread_scalp": 1.5, "spread_long": 1.0},
    "usdjpy": {"spread_scalp": 2.0, "spread_long": 1.5},
    "audusd": {"spread_scalp": 1.5, "spread_long": 1.0},
    "eurjpy": {"spread_scalp": 2.0, "spread_long": 1.5},
}

ACTIVE_PAIRS = ["eurusd", "usdjpy", "audusd", "eurjpy"]

console = Console()

COOLDOWN_BARS     = 12     # 12 × 5m = 60 min pause after a loss
SESSION_START_UTC = 7      # London open
SESSION_END_UTC   = 16     # NY afternoon / London close
WEEKEND_CLOSE_HOUR = 20    # Friday UTC hour at which positions are force-closed

# Forming-bar simulation: number of completed bars kept in the rolling indicator
# window when recomputing H1 / daily indicators per M5 tick.  Wide enough that
# EMA initialisation error is negligible (<0.5% for EMA50 at 200 bars).
H1_IND_LOOKBACK = 200
D_IND_LOOKBACK  = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if idx.tzinfo is None:
        return idx.tz_localize("UTC")
    return idx.tz_convert("UTC")


def merge_trend(df_h1: pd.DataFrame, df_5m: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill the H1 ATR onto entry bars using merge_asof.

    Each entry bar gets the ATR from the most recently closed trend bar
    (direction="backward").  Both indexes are normalised to UTC.
    """
    h1 = df_h1[["atr"]].copy()
    h1.columns = ["h1_atr"]
    h1.index    = _to_utc(h1.index)
    df_5m       = df_5m.copy()
    df_5m.index = _to_utc(df_5m.index)

    idx_name = df_5m.index.name or "datetime"
    h1.index.name = idx_name

    merged = pd.merge_asof(
        df_5m.reset_index(),
        h1.reset_index(),
        on=idx_name,
        direction="backward",
    )
    merged.set_index(idx_name, inplace=True)
    return merged


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_data(
    pair: str, ind, *, update: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Scalp mode: incrementally update parquet store then load bars.

    Returns (df_h1, df_4h, df_5m, df_m1, df_h1_raw, df_1d_raw).
      df_h1    — H1 bars with indicators; used only by merge_trend for ATR forward-fill
      df_4h    — H4 bars with indicators + ema_4h, Measure 4 filter
      df_5m    — M5 bars with indicators, entry signal evaluation
      df_m1    — M1 bars (OHLCV only); within-bar simulation and forming-bar construction
      df_h1_raw — H1 OHLCV only (no indicators); run_backtest appends the forming H1
                  bar at each M5 tick so assess_h1_bias sees a partially-formed bar,
                  mirroring the live daemon's view exactly
      df_1d_raw — OANDA native daily bars (no indicators); used directly as the daemon
                  uses datalib.load("D") — no forming-bar construction for daily
    """
    if update:
        datalib.update(pair)

    df_m1     = datalib.load(pair, "M1")
    df_h1_raw = datalib.resample(df_m1, "H1")
    df_1d_raw = datalib.load(pair, "D")          # OANDA native daily bars — same source as daemon

    df_h1 = ind.compute_h1_indicators(df_h1_raw.copy())

    # 4H resampled from M1-derived H1, matching the daemon's data path
    df_4h = df_h1_raw.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)
    df_4h["ema_4h"] = EMAIndicator(
        close=df_4h["close"], window=ind.H4_EMA_PERIOD
    ).ema_indicator()
    if hasattr(ind, "compute_supertrend"):
        df_4h = ind.compute_supertrend(df_4h, period=10, multiplier=3.0)

    # M5 derived from M1 (never stored; always resampled at runtime)
    df_5m = datalib.resample(df_m1, "M5")
    df_5m = ind.compute_m5_indicators(df_5m)

    return df_h1, df_4h, df_5m, df_m1, df_h1_raw, df_1d_raw


def fetch_data_long(
    pair: str, ind, *, update: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Long mode: H4 trend (resampled from stored H1) + H1 entry bars.

    Returns (df_4h, df_1h_entry).
    """
    if update:
        datalib.update(pair, "H1")

    df_h1_raw = datalib.load(pair, "H1")

    df_4h = df_h1_raw.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)

    df_1h_entry = ind.compute_m5_indicators(df_h1_raw.copy())

    return df_4h, df_1h_entry


# ── Backtest engine ───────────────────────────────────────────────────────────

def run_backtest(
    df_h1:       pd.DataFrame,
    df_5m:       pd.DataFrame,
    bar_mins:    int   = 5,
    spread_pips: float = 1.5,
    use_session: bool  = True,
    pair:        str   = "eurusd",
    ind          = None,
    df_4h:       Optional[pd.DataFrame] = None,
    df_1d:       Optional[pd.DataFrame] = None,
    df_m1:       Optional[pd.DataFrame] = None,
    df_h1_raw:   Optional[pd.DataFrame] = None,
    df_1d_raw:   Optional[pd.DataFrame] = None,
    be_only:     Optional[bool] = None,
) -> list[dict]:
    """
    Walk-forward simulation using tradelib.check_position_events() for all
    trade lifecycle events.

    When df_m1 is provided (scalp mode), each open position is evaluated
    bar-by-bar against the M1 bars within each M5 window, resolving the
    chronological order of SL vs TP hits.

    When df_h1_raw and df_1d_raw are also provided (scalp mode), the H1 and
    daily bars used for assess_h1_bias() are rebuilt from M1 at every M5 tick:
    completed bars up to the current hour/day boundary are taken from the raw
    OHLCV frames, and a single forming bar is appended whose OHLCV reflects only
    the M1 data seen so far within that period.  This mirrors the live daemon
    exactly — the daemon always sees a partially-formed H1 and daily bar, never
    the fully-closed version.

    Without df_h1_raw / df_1d_raw (long mode), the legacy pre-computed slices
    are used.
    """
    merged = merge_trend(df_h1, df_5m)
    bars   = merged.reset_index()

    if df_4h is not None:
        df_4h = df_4h.copy()
        df_4h.index = _to_utc(df_4h.index)
    h4_times = df_4h.index if df_4h is not None else None

    # M1 index for within-bar simulation and forming-bar construction
    m1_index: Optional[pd.DatetimeIndex] = None
    if df_m1 is not None and not df_m1.empty:
        df_m1 = df_m1.copy()
        df_m1.index = _to_utc(df_m1.index)
        m1_index = df_m1.index

    # Normalise df_5m index so iloc positions align with merged/bars throughout
    df_5m = df_5m.copy()
    df_5m.index = _to_utc(df_5m.index)

    # Forming-bar path (scalp mode): raw OHLCV frames, UTC-indexed
    if df_h1_raw is not None:
        df_h1_raw = df_h1_raw.copy()
        df_h1_raw.index = _to_utc(df_h1_raw.index)
    if df_1d_raw is not None:
        df_1d_raw = df_1d_raw.copy()
        df_1d_raw.index = _to_utc(df_1d_raw.index)

    # Legacy path (long mode): pre-computed indicator slices
    _df_h1_legacy: Optional[pd.DataFrame] = None
    _h1_times_legacy: Optional[pd.DatetimeIndex] = None
    _df_1d_legacy: Optional[pd.DataFrame] = None
    _d_times_legacy: Optional[pd.DatetimeIndex] = None
    if df_h1_raw is None:
        _df_h1_legacy = df_h1.copy()
        _df_h1_legacy.index = _to_utc(_df_h1_legacy.index)
        _h1_times_legacy = _df_h1_legacy.index
    if df_1d_raw is None and df_1d is not None and "adx" in df_1d.columns:
        _df_1d_legacy = df_1d.copy()
        _df_1d_legacy.index = _to_utc(_df_1d_legacy.index)
        _d_times_legacy = _df_1d_legacy.index

    pv = ind.pip_value(pair)

    trades:         list[dict] = []
    pos:            Optional[tradelib.Position] = None
    cooldown_until: int = 0
    entry_idx:      int = 0
    entry_pattern:  str = ""

    for i in range(30, len(bars)):
        row = bars.iloc[i]
        ts  = row.iloc[0]

        # ── Position management ───────────────────────────────────────────────
        if pos is not None:
            closed = False

            def _process_bar(h: float, l: float) -> Optional[tuple[str, float]]:
                bar_s = pd.Series({"high": h, "low": l})
                for evt_name, evt_price in tradelib.check_position_events(pos, bar_s, ind, be_only=be_only):
                    if evt_name in ("close_tp", "close_sl"):
                        return (evt_name, evt_price)
                return None

            if ts.weekday() == 4 and ts.hour >= WEEKEND_CLOSE_HOUR:
                _record_trade(
                    trades, pos, float(row["open"]), pv,
                    i, entry_idx, bar_mins, entry_pattern, forced=True,
                )
                if trades[-1]["result"] == "LOSS":
                    cooldown_until = i + COOLDOWN_BARS
                pos    = None
                closed = True
            elif m1_index is not None:
                m5_end   = ts + pd.Timedelta(minutes=bar_mins)
                lo       = m1_index.searchsorted(ts,     side="left")
                hi       = m1_index.searchsorted(m5_end, side="left")
                m1_slice = df_m1.iloc[lo:hi]

                for _, m1_bar in m1_slice.iterrows():
                    evt = _process_bar(float(m1_bar["high"]), float(m1_bar["low"]))
                    if evt is not None:
                        _record_trade(
                            trades, pos, evt[1], pv,
                            i, entry_idx, bar_mins, entry_pattern,
                        )
                        if trades[-1]["result"] == "LOSS":
                            cooldown_until = i + COOLDOWN_BARS
                        pos    = None
                        closed = True
                        break
            else:
                evt = _process_bar(float(row["high"]), float(row["low"]))
                if evt is not None:
                    _record_trade(
                        trades, pos, evt[1], pv,
                        i, entry_idx, bar_mins, entry_pattern,
                    )
                    if trades[-1]["result"] == "LOSS":
                        cooldown_until = i + COOLDOWN_BARS
                    pos    = None
                    closed = True

            if pos is not None or closed:
                continue

        # ── Session / cooldown / weekday gate ─────────────────────────────────
        if use_session and not (SESSION_START_UTC <= ts.hour < SESSION_END_UTC):
            continue
        if hasattr(ind, "BLOCKED_DAYS") and ts.weekday() in ind.BLOCKED_DAYS:
            continue
        if i < cooldown_until:
            continue

        # ── Trend bias ────────────────────────────────────────────────────────
        if df_h1_raw is not None and m1_index is not None:
            # Forming-bar path: build the current H1 bar from M1 data up to this
            # M5 bar's close (ts + bar_mins), matching what the live daemon sees.
            h1_floor   = ts.floor("1h")
            h1_raw_end = df_h1_raw.index.searchsorted(h1_floor, side="left")
            if h1_raw_end < 15:
                continue
            h1_base = df_h1_raw.iloc[max(0, h1_raw_end - H1_IND_LOOKBACK):h1_raw_end]
            m1_lo   = m1_index.searchsorted(h1_floor, side="left")
            m1_hi   = m1_index.searchsorted(ts + pd.Timedelta(minutes=bar_mins), side="left")
            m1_h1   = df_m1.iloc[m1_lo:m1_hi]
            if not m1_h1.empty:
                forming_h1 = pd.DataFrame(
                    {
                        "open":   float(m1_h1["open"].iloc[0]),
                        "high":   float(m1_h1["high"].max()),
                        "low":    float(m1_h1["low"].min()),
                        "close":  float(m1_h1["close"].iloc[-1]),
                        "volume": int(m1_h1["volume"].sum()),
                    },
                    index=pd.DatetimeIndex([h1_floor], tz="UTC"),
                )
                h1_for_ind = pd.concat([h1_base, forming_h1])
            else:
                h1_for_ind = h1_base
            df_h1_live = ind.compute_h1_indicators(h1_for_ind)
        else:
            # Legacy path (long mode)
            h1_end = _h1_times_legacy.searchsorted(ts, side="right")
            if h1_end < 3:
                continue
            df_h1_live = _df_h1_legacy.iloc[:h1_end]

        df_4h_slice = None
        if h4_times is not None:
            h4_end      = h4_times.searchsorted(ts, side="right")
            df_4h_slice = df_4h.iloc[:h4_end] if h4_end > 0 else None

        if df_1d_raw is not None and hasattr(ind, "compute_daily_adx"):
            # Use OANDA native daily bars (same source as daemon).  OANDA daily
            # bars open at ~22:00 UTC, so a bar is complete 24h after its open
            # time.  Use bars whose open time is more than 24h before ts.
            d_cutoff  = ts - pd.Timedelta(hours=24)
            d_raw_end = df_1d_raw.index.searchsorted(d_cutoff, side="right")
            d_slice   = df_1d_raw.iloc[max(0, d_raw_end - D_IND_LOOKBACK):d_raw_end].copy()
            df_1d_slice = ind.compute_daily_adx(d_slice) if len(d_slice) >= 30 else None
        elif _d_times_legacy is not None:
            d_end       = _d_times_legacy.searchsorted(ts, side="right")
            df_1d_slice = _df_1d_legacy.iloc[:d_end] if d_end > 0 else None
        else:
            df_1d_slice = None

        if hasattr(ind, "DAILY_ADX_MIN"):
            bias_info = ind.assess_h1_bias(
                df_h1_live, df_4h=df_4h_slice, df_1d=df_1d_slice
            )
        else:
            bias_info = ind.assess_h1_bias(df_h1_live, df_4h=df_4h_slice)

        bias = bias_info["direction"]
        if bias == "FLAT":
            continue

        # ── Entry pattern — forming-bar scan then complete-bar fallback ──────
        # Mirrors the daemon's 60-second M1 polling: for each M1 bar within
        # this M5 period, build the partial bar that the daemon would have seen,
        # recompute M5 indicators, and check for a signal.  The first M1 bar
        # that produces a signal on the current period (bar_time == ts) is used.
        # If the forming scan finds nothing, evaluate the complete bar as before.
        entry_result = None
        ts_str       = str(ts)
        if m1_index is not None:
            m5_end    = ts + pd.Timedelta(minutes=bar_mins)
            m1_lo     = m1_index.searchsorted(ts,     side="left")
            m1_hi     = m1_index.searchsorted(m5_end, side="left")
            m1_in_bar = df_m1.iloc[m1_lo:m1_hi]
            raw_hist  = df_5m.iloc[max(0, i - 100): i][["open", "high", "low", "close", "volume"]]
            for m1_j in range(len(m1_in_bar)):
                m1_partial = m1_in_bar.iloc[: m1_j + 1]
                partial_ohlcv = pd.DataFrame(
                    [{
                        "open":   float(m1_partial["open"].iloc[0]),
                        "high":   float(m1_partial["high"].max()),
                        "low":    float(m1_partial["low"].min()),
                        "close":  float(m1_partial["close"].iloc[-1]),
                        "volume": int(m1_partial["volume"].sum()),
                    }],
                    index=pd.DatetimeIndex([ts], tz="UTC"),
                )
                m5_with_ind = ind.compute_m5_indicators(
                    pd.concat([raw_hist, partial_ohlcv])
                )
                er = ind.find_m5_entry(m5_with_ind.iloc[-30:], bias, use_session=False)
                if er is not None and er["bar_time"] == ts_str:
                    entry_result = er
                    break

        if entry_result is None:
            m5_slice     = merged.iloc[max(0, i - 35): i + 1]
            entry_result = ind.find_m5_entry(m5_slice, bias, use_session=False)
        if entry_result is None or entry_result["bar_time"] != ts_str:
            continue

        # ── Compute SL/TP via the same build_signal path as the daemon ─────────
        # Entry is at the signal bar's close (spread-adjusted), matching the
        # daemon's market-order fill timing.  Spread is embedded in entry_price;
        # _record_trade does NOT deduct it separately.
        signal = ind.build_signal(bias_info, entry_result, pair.upper(),
                                  spread_pips=spread_pips)
        if signal.direction == "FLAT":
            continue

        entry_p = signal.entry_price
        sl      = signal.stop_loss
        tp      = signal.take_profit

        pos = tradelib.Position(
            pair         = pair,
            symbol       = pair.upper(),
            direction    = bias,
            trade_type   = "automated",
            entry_price  = entry_p,
            stop_loss    = sl,
            take_profit  = tp,
            atr          = signal.atr,
            risk_pips    = signal.risk_pips,
            reward_pips  = signal.reward_pips,
            rr_ratio     = signal.rr_ratio,
            opened_at    = str(ts),
            basis        = signal.entry_basis,
            original_tp  = tp,
            best_price   = entry_p,
        )
        entry_idx     = i
        entry_pattern = entry_result.get("pattern", "")

    return trades


def _record_trade(
    trades:     list[dict],
    pos:        tradelib.Position,
    exit_price: float,
    pv:         float,
    bar_idx:    int,
    entry_idx:  int,
    bar_mins:   int,
    pattern:    str,
    forced:     bool = False,
) -> None:
    held     = bar_idx - entry_idx
    # Spread is embedded in entry_price via build_signal (ep_adj); no separate deduction.
    pnl_pips = (
        (exit_price - pos.entry_price) / pv
        * (1 if pos.direction == "BUY" else -1)
    )
    result = "WIN" if pnl_pips > 0 else "LOSS"
    trades.append({
        "entry_time": pos.opened_at,
        "direction":  pos.direction,
        "entry":      round(pos.entry_price, 5),
        "exit":       round(exit_price, 5),
        "sl":         round(pos.stop_loss, 5),
        "tp":         round(pos.take_profit, 5),
        "risk_pips":  round(pos.risk_pips, 1),
        "held_bars":  held,
        "held_mins":  held * bar_mins,
        "pnl_pips":   round(pnl_pips, 1),
        "result":     result,
        "forced":     forced,
        "pattern":    pattern,
        "extended":   pos.tp_extended,
    })


# ── Data-gap detection ───────────────────────────────────────────────────────

def _find_data_gaps(df: pd.DataFrame, bar_mins: int) -> list[tuple]:
    """Return (gap_start, gap_end, duration) tuples for unexpected bar gaps.

    Weekday FX sessions are continuous, so any intra-week gap wider than 1 hour
    (scalp) or 4 hours (long) is flagged.  Fri/Sat→Sun/Mon weekend gaps that
    are >= 2d 1h are normal and suppressed; shorter gaps are still reported.
    """
    idx = _to_utc(df.index)
    if len(idx) < 2:
        return []
    threshold = pd.Timedelta(hours=1 if bar_mins <= 5 else 4)
    gaps: list[tuple] = []
    for i in range(1, len(idx)):
        gap = idx[i] - idx[i - 1]
        if gap <= threshold:
            continue
        d_prev = idx[i - 1].weekday()
        d_curr = idx[i].weekday()
        if d_prev >= 4 and d_curr in (0, 1, 6) and gap >= pd.Timedelta(hours=44):
            continue
        gaps.append((idx[i - 1], idx[i], gap))
    return gaps


# ── Statistics ────────────────────────────────────────────────────────────────

def _compute_stats(trades: list[dict], bar_mins: int) -> dict:
    df = pd.DataFrame(trades)
    wins   = df[df["result"] == "WIN"]
    losses = df[df["result"] == "LOSS"]
    wr     = len(wins) / len(df) * 100
    aw     = wins["pnl_pips"].mean()        if len(wins)   else 0.0
    al     = abs(losses["pnl_pips"].mean()) if len(losses) else 0.0
    exp    = (wr / 100 * aw) - ((1 - wr / 100) * al)
    total  = df["pnl_pips"].sum()
    pf     = (
        wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
        if len(losses) and losses["pnl_pips"].sum() != 0
        else float("inf")
    )
    cum    = df["pnl_pips"].cumsum()
    max_dd = (cum - cum.cummax()).min()

    start_date = end_date = None
    try:
        start_date   = pd.Timestamp(df["entry_time"].iloc[0])
        end_date     = pd.Timestamp(df["entry_time"].iloc[-1])
        trading_days = max(1, (end_date - start_date).days)
    except Exception:
        trading_days = 730 if bar_mins >= 60 else 60

    return dict(
        n=len(df), wins=len(wins), losses=len(losses),
        wr=wr, aw=aw, al=al, exp=exp, total=total, pf=pf,
        max_dd=max_dd, trades_per_day=len(df) / trading_days,
        avg_mins=df["held_mins"].mean(), forced=int(df["forced"].sum()),
        start_date=start_date, end_date=end_date,
    )


def _compute_sizing(
    trades: list[dict], pair: str, account: float, risk_pct: float
) -> tuple[list[float], str]:
    """Return per-trade position sizes (lots) and the unit label."""
    risk_dollars = account * risk_pct / 100
    LOT_SIZE     = 100_000
    is_jpy       = "jpy" in pair.lower()

    pv = 0.01 if is_jpy else 0.0001
    sizes = []
    for t in trades:
        risk_pips = t.get("risk_pips") or abs(t["entry"] - t["sl"]) / pv
        stop_dist = risk_pips * pv
        if stop_dist == 0:
            sizes.append(0.0)
            continue
        if is_jpy:
            sizes.append(risk_dollars * t["entry"] / (stop_dist * LOT_SIZE))
        else:
            sizes.append(risk_dollars / (stop_dist * LOT_SIZE))
    return sizes, "lots"


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(
    trades:     list[dict],
    bar_mins:   int   = 5,
    pair_label: str   = "EURUSD",
    account:    float = 10_000,
    risk_pct:   float = 1.0,
    gaps:       Optional[list] = None,
    df_m1:      Optional[pd.DataFrame] = None,
) -> None:
    """Print a summary table and save the full trade log to CSV."""
    if not trades:
        console.print("[yellow]No trades generated.[/]")
        return

    s = _compute_stats(trades, bar_mins)
    sizes, size_unit = _compute_sizing(trades, pair_label, account, risk_pct)
    avg_size = sum(sizes) / len(sizes) if sizes else 0.0
    min_size = min(sizes) if sizes else 0.0
    max_size = max(sizes) if sizes else 0.0

    # Running balance — pnl_pips already has spread deducted
    is_jpy   = "jpy" in pair_label.lower()
    LOT_SIZE = 100_000
    balance  = account
    for t, size in zip(trades, sizes):
        pip_dollar = (0.01 * LOT_SIZE / t["entry"]) if is_jpy else (0.0001 * LOT_SIZE)
        balance   += t["pnl_pips"] * pip_dollar * size

    if bar_mins >= 60:
        hold_str   = f"{s['avg_mins'] / 60:.1f} hrs"
        mode_label = "H1 bars (long mode)"
    else:
        hold_str   = f"{s['avg_mins']:.0f} min"
        mode_label = "M5 bars + M1 sim (scalp mode)"

    table = Table(
        title=f"Backtest Results — {pair_label}  ({mode_label})",
        box=box.ROUNDED,
    )
    table.add_column("Metric", style="dim")
    table.add_column("Value",  justify="right")

    fmt_date = lambda d: d.strftime("%Y-%m-%d") if d else "—"
    if df_m1 is not None and not df_m1.empty:
        table.add_row("M1 data from",  fmt_date(pd.Timestamp(df_m1.index[0])))
        table.add_row("M1 data to",    fmt_date(pd.Timestamp(df_m1.index[-1])))
        table.add_row("──────────────", "──────────────")
    table.add_row("First trade",   fmt_date(s["start_date"]))
    table.add_row("Last trade",    fmt_date(s["end_date"]))
    table.add_row("──────────────", "──────────────")
    table.add_row("Total trades",  str(s["n"]))
    table.add_row("Trades / day",  f"{s['trades_per_day']:.1f}")
    table.add_row("Wins",          str(s["wins"]))
    table.add_row("Losses",        str(s["losses"]))
    table.add_row("Win rate",      f"{s['wr']:.1f}%")
    table.add_row("Avg win",       f"{s['aw']:.1f} pips")
    table.add_row("Avg loss",      f"{s['al']:.1f} pips")
    table.add_row("Profit factor", f"{s['pf']:.2f}")
    table.add_row("Expectancy",    f"{s['exp']:.1f} pips/trade")
    table.add_row("Total pips",
                  f"[{'green' if s['total'] > 0 else 'red'}]{s['total']:.1f}[/]")
    table.add_row("Max drawdown",  f"[red]{s['max_dd']:.1f} pips[/]")
    table.add_row("Avg hold time", hold_str)
    table.add_row("Forced closes", str(s["forced"]))
    table.add_row("──────────────", "──────────────")
    table.add_row(
        "Account / risk",
        f"${account:,.0f}  ·  {risk_pct:.1f}%  =  ${account * risk_pct / 100:.0f}/trade",
    )
    table.add_row("Avg size",   f"{avg_size:.2f} {size_unit}")
    table.add_row("Size range", f"{min_size:.2f} – {max_size:.2f} {size_unit}")
    bal_color = "green" if balance >= account else "red"
    table.add_row(
        "Final balance",
        f"[{bal_color}]${balance:,.2f}[/]  "
        f"([{bal_color}]{'+' if balance >= account else ''}{balance - account:,.2f}[/])",
    )

    console.print(table)

    if gaps:
        console.print(f"\n[yellow]⚠  {len(gaps)} data gap(s) in bar history:[/]")
        for g_start, g_end, g_dur in gaps[:10]:
            console.print(
                f"  [dim]{g_start.strftime('%Y-%m-%d %H:%M')} → "
                f"{g_end.strftime('%Y-%m-%d %H:%M')}  ({g_dur})[/]"
            )
        if len(gaps) > 10:
            console.print(f"  [dim]… and {len(gaps) - 10} more[/]")

    df = pd.DataFrame(trades)
    df["suggested_size"] = sizes
    df["size_unit"]      = size_unit
    csv_path = f"{pair_label.lower()}_backtest_trades.csv"
    df.to_csv(csv_path, index=False)
    console.print(f"\n[dim]Full trade log saved to {csv_path}[/]")


def report_all(results: list[tuple[str, list[dict]]], bar_mins: int = 5) -> None:
    """Print a combined comparison table for all pairs."""
    mode_label = "H1 bars (long)" if bar_mins >= 60 else "M5 + M1 sim (scalp)"

    table = Table(title=f"All-Pairs Summary  ({mode_label})", box=box.ROUNDED)
    table.add_column("Pair",         style="bold")
    table.add_column("Trades",       justify="right")
    table.add_column("Win %",        justify="right")
    table.add_column("Avg W",        justify="right")
    table.add_column("Avg L",        justify="right")
    table.add_column("Prof. Factor", justify="right")
    table.add_column("Expectancy",   justify="right")
    table.add_column("Total pips",   justify="right")
    table.add_column("Max DD",       justify="right")

    rows = [
        (lbl, _compute_stats(t, bar_mins) if t else None)
        for lbl, t in results
    ]
    rows.sort(
        key=lambda r: r[1]["total"] if r[1] else float("-inf"), reverse=True
    )

    for pair_label, s in rows:
        if s is None:
            table.add_row(pair_label, "[yellow]no trades[/]", *["—"] * 7)
            continue
        pf_str  = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
        pip_col = "green" if s["total"] > 0 else "red"
        table.add_row(
            pair_label,
            str(s["n"]),
            f"{s['wr']:.1f}%",
            f"{s['aw']:.1f}",
            f"{s['al']:.1f}",
            pf_str,
            f"{s['exp']:.1f}",
            f"[{pip_col}]{s['total']:.1f}[/]",
            f"[red]{s['max_dd']:.1f}[/]",
        )

    console.print(table)


def report_compare(
    trail_results: list[tuple[str, list[dict]]],
    be_results:    list[tuple[str, list[dict]]],
    bar_mins:      int = 5,
) -> None:
    """Side-by-side comparison: three-phase trailing vs breakeven-only."""
    mode_label = "H1 bars (long)" if bar_mins >= 60 else "M5 + M1 sim (scalp)"

    table = Table(
        title=f"Trail vs BE-only Comparison  ({mode_label})",
        box=box.ROUNDED,
    )
    table.add_column("Pair",        style="bold")
    table.add_column("Mode",        style="dim")
    table.add_column("Trades",      justify="right")
    table.add_column("Win %",       justify="right")
    table.add_column("Avg W",       justify="right")
    table.add_column("Avg L",       justify="right")
    table.add_column("PF",          justify="right")
    table.add_column("Expect",      justify="right")
    table.add_column("Total pips",  justify="right")
    table.add_column("Max DD",      justify="right")

    be_map = {lbl: t for lbl, t in be_results}
    for pair_label, trail_trades in sorted(trail_results, key=lambda x: x[0]):
        be_trades = be_map.get(pair_label, [])
        for label, trades in [("trail", trail_trades), ("BE-only", be_trades)]:
            if not trades:
                table.add_row(pair_label if label == "trail" else "", label, "[yellow]no trades[/]", *["—"] * 7)
                continue
            s = _compute_stats(trades, bar_mins)
            pf_str  = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
            pip_col = "green" if s["total"] > 0 else "red"
            table.add_row(
                pair_label if label == "trail" else "",
                label,
                str(s["n"]),
                f"{s['wr']:.1f}%",
                f"{s['aw']:.1f}",
                f"{s['al']:.1f}",
                pf_str,
                f"{s['exp']:.1f}",
                f"[{pip_col}]{s['total']:.1f}[/]",
                f"[red]{s['max_dd']:.1f}[/]",
            )
        table.add_section()

    console.print(table)


# ── Period breakdown reporting ────────────────────────────────────────────────

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _period_table(
    df: pd.DataFrame,
    group_keys: list,
    labels: list[str],
    title: str,
) -> None:
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Period",     style="dim")
    table.add_column("Trades",     justify="right")
    table.add_column("Win %",      justify="right")
    table.add_column("PF",         justify="right")
    table.add_column("Total pips", justify="right")
    table.add_column("Avg pips",   justify="right")

    for key, label in zip(group_keys, labels):
        grp    = df[df["_grp"] == key]
        wins   = grp[grp["result"] == "WIN"]
        losses = grp[grp["result"] == "LOSS"]
        wr     = len(wins) / len(grp) * 100 if len(grp) else 0.0
        total  = grp["pnl_pips"].sum()
        avg    = grp["pnl_pips"].mean()
        pf     = (
            wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
            if len(losses) and losses["pnl_pips"].sum() != 0
            else float("inf")
        )
        pf_str  = f"{pf:.2f}" if pf != float("inf") else "∞"
        c       = "green" if total > 0 else "red"
        table.add_row(
            label, str(len(grp)), f"{wr:.1f}%", pf_str,
            f"[{c}]{total:.1f}[/]", f"[{c}]{avg:.1f}[/]",
        )

    console.print(table)


def report_by_pattern(trades: list[dict], pair_label: str, bar_mins: int) -> None:
    """Print a per-entry-pattern breakdown table."""
    if not trades:
        return
    df    = pd.DataFrame(trades)
    mode  = "long" if bar_mins >= 60 else "scalp"
    table = Table(title=f"Pattern Breakdown — {pair_label}  ({mode})", box=box.ROUNDED)
    table.add_column("Pattern",    style="dim")
    table.add_column("Trades",     justify="right")
    table.add_column("Win %",      justify="right")
    table.add_column("Avg W",      justify="right")
    table.add_column("Avg L",      justify="right")
    table.add_column("PF",         justify="right")
    table.add_column("Total pips", justify="right")
    table.add_column("Avg pips",   justify="right")

    for pattern in sorted(df["pattern"].unique()):
        grp    = df[df["pattern"] == pattern]
        wins   = grp[grp["result"] == "WIN"]
        losses = grp[grp["result"] == "LOSS"]
        wr     = len(wins) / len(grp) * 100 if len(grp) else 0.0
        aw     = wins["pnl_pips"].mean()        if len(wins)   else 0.0
        al     = abs(losses["pnl_pips"].mean()) if len(losses) else 0.0
        total  = grp["pnl_pips"].sum()
        avg    = grp["pnl_pips"].mean()
        pf     = (
            wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
            if len(losses) and losses["pnl_pips"].sum() != 0
            else float("inf")
        )
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        c      = "green" if total > 0 else "red"
        table.add_row(
            pattern, str(len(grp)), f"{wr:.1f}%",
            f"{aw:.1f}", f"{al:.1f}", pf_str,
            f"[{c}]{total:.1f}[/]", f"[{c}]{avg:.1f}[/]",
        )

    console.print(table)


def report_weekly_pnl(
    trades:     list[dict],
    pair_label: str,
    bar_mins:   int,
    account:    float = 10_000,
    risk_pct:   float = 1.0,
) -> None:
    """Print weekly pips P&L and running balance for complete ISO weeks only."""
    if not trades:
        return

    sizes, _ = _compute_sizing(trades, pair_label, account, risk_pct)
    LOT_SIZE  = 100_000
    is_jpy    = "jpy" in pair_label.lower()

    df = pd.DataFrame(trades)
    df["_ts"]    = pd.to_datetime(df["entry_time"], utc=True)
    df["_week"]  = df["_ts"].dt.strftime("%G-W%V")
    df["_size"]  = sizes

    all_weeks = sorted(df["_week"].unique())
    if len(all_weeks) < 1:
        return
    partial = {all_weeks[0], all_weeks[-1]} if len(all_weeks) > 1 else set()

    mode = "long" if bar_mins >= 60 else "scalp"
    current_week = date.today().isocalendar().week
    table = Table(
        title=f"Weekly P&L W{current_week:02d} — {pair_label}  ({mode})",
        box=box.ROUNDED,
    )
    table.add_column("Week",     style="dim")
    table.add_column("Trades",   justify="right")
    table.add_column("Pips",     justify="right")
    table.add_column("Balance",  justify="right")

    balance      = account
    total_pips   = 0.0

    # pre-compute dollar P&L per trade
    df["_pv"] = df.apply(
        lambda r: (0.01 * LOT_SIZE / r["entry"]) if is_jpy else (0.0001 * LOT_SIZE),
        axis=1,
    )
    df["_pnl_usd"] = df["pnl_pips"] * df["_pv"] * df["_size"]

    for week in all_weeks:
        grp        = df[df["_week"] == week]
        week_pips  = grp["pnl_pips"].sum()
        week_usd   = grp["_pnl_usd"].sum()
        balance   += week_usd
        total_pips += week_pips
        c = "green" if week_pips >= 0 else "red"
        bal_c = "green" if balance >= account else "red"
        week_label = f"{week} *" if week in partial else week
        table.add_row(
            week_label,
            str(len(grp)),
            f"[{c}]{week_pips:+.1f}[/]",
            f"[{bal_c}]${balance:,.2f}[/]",
        )

    table.add_section()
    c = "green" if total_pips >= 0 else "red"
    bal_c = "green" if balance >= account else "red"
    table.add_row(
        f"Total ({len(all_weeks)} weeks)",
        "",
        f"[{c}]{total_pips:+.1f}[/]",
        f"[{bal_c}]${balance:,.2f}[/]",
    )
    if partial:
        console.print("  [dim]* partial week (backtest boundary)[/]")

    console.print(table)


def report_by_week(
    trades: list[dict],
    pair_label: str,
    bar_mins: int,
    account: float = 10_000,
    risk_pct: float = 1.0,
) -> None:
    """Print a per-ISO-week breakdown table with partial-week markers, pip total, and running balance."""
    if not trades:
        return

    sizes, _ = _compute_sizing(trades, pair_label, account, risk_pct)
    LOT_SIZE  = 100_000
    is_jpy    = "jpy" in pair_label.lower()

    df = pd.DataFrame(trades)
    df["_ts"]   = pd.to_datetime(df["entry_time"], utc=True)
    df["_week"] = df["_ts"].dt.strftime("%G-W%V")
    df["_size"] = sizes
    df["_pv"]   = df.apply(
        lambda r: (0.01 * LOT_SIZE / r["entry"]) if is_jpy else (0.0001 * LOT_SIZE),
        axis=1,
    )
    df["_pnl_usd"] = df["pnl_pips"] * df["_pv"] * df["_size"]

    all_weeks = sorted(df["_week"].unique())
    partial   = {all_weeks[0], all_weeks[-1]} if len(all_weeks) > 1 else set()

    mode         = "long" if bar_mins >= 60 else "scalp"
    current_week = date.today().isocalendar().week

    table = Table(
        title=f"Weekly Breakdown W{current_week:02d} — {pair_label}  ({mode})",
        box=box.ROUNDED,
    )
    table.add_column("Week",       style="dim")
    table.add_column("Trades",     justify="right")
    table.add_column("Win %",      justify="right")
    table.add_column("PF",         justify="right")
    table.add_column("Total pips", justify="right")
    table.add_column("Avg pips",   justify="right")
    table.add_column("Balance",    justify="right")

    balance      = account
    total_pips   = 0.0
    total_trades = 0

    for week in all_weeks:
        grp       = df[df["_week"] == week]
        wins      = grp[grp["result"] == "WIN"]
        losses    = grp[grp["result"] == "LOSS"]
        wr        = len(wins) / len(grp) * 100 if len(grp) else 0.0
        week_pips = grp["pnl_pips"].sum()
        avg_pips  = grp["pnl_pips"].mean()
        balance  += grp["_pnl_usd"].sum()
        total_pips   += week_pips
        total_trades += len(grp)
        pf = (
            wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
            if len(losses) and losses["pnl_pips"].sum() != 0
            else float("inf")
        )
        pf_str     = f"{pf:.2f}" if pf != float("inf") else "∞"
        c          = "green" if week_pips > 0 else "red"
        bal_c      = "green" if balance >= account else "red"
        week_label = f"{week} *" if week in partial else week
        table.add_row(
            week_label, str(len(grp)), f"{wr:.1f}%", pf_str,
            f"[{c}]{week_pips:.1f}[/]", f"[{c}]{avg_pips:.1f}[/]",
            f"[{bal_c}]${balance:,.2f}[/]",
        )

    table.add_section()
    c     = "green" if total_pips > 0 else "red"
    bal_c = "green" if balance >= account else "red"
    table.add_row(
        f"Total ({len(all_weeks)} weeks)", str(total_trades), "", "",
        f"[{c}]{total_pips:+.1f}[/]", "",
        f"[{bal_c}]${balance:,.2f}[/]",
    )
    if partial:
        console.print("  [dim]* partial week (backtest boundary)[/]")
    console.print(table)


def report_by_day(trades: list[dict], pair_label: str, bar_mins: int) -> None:
    """Print a Mon–Fri day-of-week breakdown table."""
    if not trades:
        return
    df = pd.DataFrame(trades)
    df["_ts"]  = pd.to_datetime(df["entry_time"], utc=True)
    df["_grp"] = df["_ts"].dt.dayofweek               # 0 = Mon
    present    = sorted(df["_grp"].unique())
    labels     = [_WEEKDAY_NAMES[d] for d in present]
    mode       = "long" if bar_mins >= 60 else "scalp"
    _period_table(df, present, labels, f"Day-of-Week Breakdown — {pair_label}  ({mode})")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FX Scalper — walk-forward backtest")
    parser.add_argument(
        "--long", action="store_true",
        help="Run on H1 bars (~730 days) instead of M5 bars (~90 days)",
    )
    parser.add_argument(
        "--pair", default="eurusd",
        choices=list(PAIR_INDICATORS.keys()),
        help="Currency pair to backtest (default: eurusd)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run every active pair and show a combined comparison table",
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="Force a full data seed before running (use for first-time setup)",
    )
    parser.add_argument(
        "--no-update", action="store_true",
        help="Skip incremental data update (use stored data as-is)",
    )
    parser.add_argument(
        "--account", type=float, default=10_000,
        help="Account size in USD for position sizing (default: 10000)",
    )
    parser.add_argument(
        "--risk", type=float, default=1.0,
        help="Risk per trade as %% of account (default: 1.0)",
    )
    parser.add_argument(
        "--no-blocked-days", action="store_true",
        help="Ignore BLOCKED_DAYS gate (use to compare with/without Friday block)",
    )
    parser.add_argument(
        "--by-day", action="store_true",
        help="Print Mon–Fri day-of-week breakdown after the main summary",
    )
    parser.add_argument(
        "--by-pattern", action="store_true",
        help="Print per-entry-pattern (A/C/D/E) breakdown after the main summary",
    )
    parser.add_argument(
        "--be-only", action="store_true",
        help="Use breakeven-only mode: move SL to entry at threshold, then hold for TP (no trailing, no TP extension)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Run both three-phase trailing and BE-only modes side by side",
    )
    args = parser.parse_args()

    do_update = not args.no_update

    if args.seed:
        console.print("[bold cyan]Seeding OANDA data library (this may take a few minutes)...[/]")
        datalib.update_all()
        do_update = False

    target_pairs = ACTIVE_PAIRS if args.all else [args.pair]
    bar_mins     = 60 if args.long else 5
    mode_desc    = "long mode · H1 bars" if args.long else "scalp mode · M5 + M1 sim"
    all_results:    list[tuple[str, list[dict]]] = []
    all_be_results: list[tuple[str, list[dict]]] = []

    for pair_key in target_pairs:
        ind        = PAIR_INDICATORS[pair_key]
        cfg        = PAIR_CONFIG[pair_key]
        pair_label = pair_key.upper()
        use_sess   = cfg.get("use_session", True)

        if args.no_blocked_days and hasattr(ind, "BLOCKED_DAYS"):
            ind.BLOCKED_DAYS = frozenset()

        if args.compare:
            run_modes = [False, True]   # explicit override: trail then BE-only
        elif args.be_only:
            run_modes = [True]          # explicit override: force BE-only
        else:
            run_modes = [None]          # read USE_TRAIL from the indicator

        fetched = None   # cache fetched data across both modes for --compare

        for be_only in run_modes:
            effective_be = be_only if be_only is not None else not tradelib.trail_enabled(ind)
            mode_tag     = "BE-only" if effective_be else "trailing"
            console.print(f"[bold cyan]Running {pair_label} ({mode_desc}, {mode_tag})...[/]")

            if args.long:
                if fetched is None:
                    fetched = fetch_data_long(pair_key, ind, update=do_update)
                    do_update = False   # skip redundant network fetch on second pass
                df_trend, df_entry = fetched
                gaps   = _find_data_gaps(df_entry, 60)
                trades = run_backtest(
                    df_trend, df_entry, bar_mins=60,
                    spread_pips=cfg["spread_long"], use_session=False,
                    pair=pair_key, ind=ind, be_only=be_only,
                )
                df_m1_report = None
            else:
                if fetched is None:
                    fetched = fetch_data(pair_key, ind, update=do_update)
                    do_update = False
                df_h1, df_4h, df_5m, df_m1, df_h1_raw, df_1d_raw = fetched
                _gap_src = df_m1 if (df_m1 is not None and not df_m1.empty) else df_5m
                gaps     = _find_data_gaps(_gap_src, 1 if (df_m1 is not None and not df_m1.empty) else 5)
                trades   = run_backtest(
                    df_h1, df_5m, bar_mins=5,
                    spread_pips=cfg["spread_scalp"], use_session=use_sess,
                    pair=pair_key, ind=ind,
                    df_4h=df_4h, df_m1=df_m1,
                    df_h1_raw=df_h1_raw, df_1d_raw=df_1d_raw,
                    be_only=be_only,
                )
                df_m1_report = df_m1

            if not args.compare:
                report(trades, bar_mins=bar_mins, pair_label=pair_label,
                       account=args.account, risk_pct=args.risk, gaps=gaps,
                       df_m1=df_m1_report)
                report_by_week(trades, pair_label=pair_label, bar_mins=bar_mins,
                               account=args.account, risk_pct=args.risk)
                if args.by_day:
                    report_by_day(trades, pair_label=pair_label, bar_mins=bar_mins)
                if args.by_pattern:
                    report_by_pattern(trades, pair_label=pair_label, bar_mins=bar_mins)

            if be_only:
                all_be_results.append((pair_label, trades))
            else:
                all_results.append((pair_label, trades))

        fetched = None   # don't carry data between pairs

    if args.compare:
        report_compare(all_results, all_be_results, bar_mins=bar_mins)
    elif args.all:
        report_all(all_results, bar_mins=bar_mins)
