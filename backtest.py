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

Both modes delegate all indicator logic to the pair's indicator module and all
trailing-stop logic to tradelib.check_position_events().

Usage
-----
    python backtest.py                 # scalp mode, default pair (eurusd)
    python backtest.py --long          # long mode
    python backtest.py --pair usdjpy   # specific pair, scalp mode
    python backtest.py --all           # all active pairs, scalp mode
    python backtest.py --all --long    # all active pairs, long mode
    python backtest.py --seed          # seed data then run
"""

import argparse
from datetime import datetime, timezone
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

ACTIVE_PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd"]

console = Console()

COOLDOWN_BARS     = 12     # 12 × 5m = 60 min pause after a loss
SESSION_START_UTC = 7      # London open
SESSION_END_UTC   = 16     # NY afternoon / London close


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
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Scalp mode: incrementally update parquet store then load bars.

    Returns (df_h1, df_4h, df_5m, df_1d, df_m1).
      df_h1  — H1 bars with indicators, used for trend bias
      df_4h  — H4 bars with indicators + ema_4h, Measure 4 filter
      df_5m  — M5 bars with indicators, entry signal evaluation
      df_1d  — Daily bars with ADX gate
      df_m1  — M1 bars (OHLCV only), used for within-bar simulation
    """
    if update:
        datalib.update(pair)

    df_m1      = datalib.load(pair, "M1")
    df_h1_raw  = datalib.resample(df_m1, "H1")
    df_1d_raw  = datalib.load(pair, "D")

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

    df_1d = df_1d_raw.copy()
    if hasattr(ind, "compute_daily_adx"):
        df_1d = ind.compute_daily_adx(df_1d)

    return df_h1, df_4h, df_5m, df_1d, df_m1


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
) -> list[dict]:
    """
    Walk-forward simulation using tradelib.check_position_events() for all
    trade lifecycle events.

    When df_m1 is provided (scalp mode), each open position is evaluated
    bar-by-bar against the M1 bars within each M5 window, resolving the
    chronological order of SL vs TP hits.

    Signal generation (bias assessment and entry pattern detection) remains
    on the M5 / H1 timeframes.
    """
    merged = merge_trend(df_h1, df_5m)
    bars   = merged.reset_index()

    df_h1 = df_h1.copy()
    df_h1.index = _to_utc(df_h1.index)
    h1_times = df_h1.index

    if df_4h is not None:
        df_4h = df_4h.copy()
        df_4h.index = _to_utc(df_4h.index)
    h4_times = df_4h.index if df_4h is not None else None

    if df_1d is not None and "adx" in df_1d.columns:
        df_1d = df_1d.copy()
        df_1d.index = _to_utc(df_1d.index)
    else:
        df_1d = None
    d_times = df_1d.index if df_1d is not None else None

    # M1 index for within-bar simulation (scalp mode only)
    m1_index: Optional[pd.DatetimeIndex] = None
    if df_m1 is not None and not df_m1.empty:
        df_m1 = df_m1.copy()
        df_m1.index = _to_utc(df_m1.index)
        m1_index = df_m1.index

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

            if m1_index is not None:
                # Step through M1 bars within this M5 window
                m5_end = ts + pd.Timedelta(minutes=bar_mins)
                lo = m1_index.searchsorted(ts,    side="left")
                hi = m1_index.searchsorted(m5_end, side="left")
                m1_slice = df_m1.iloc[lo:hi]

                for _, m1_bar in m1_slice.iterrows():
                    # Carry the M5 HA columns into the M1 bar for Phase 3 gate
                    m1_row = m1_bar.copy()
                    if "ha_close" in row.index:
                        m1_row["ha_close"] = row["ha_close"]
                        m1_row["ha_open"]  = row["ha_open"]

                    events = tradelib.check_position_events(pos, m1_row, ind)
                    for evt_name, evt_price in events:
                        if evt_name in ("close_tp", "close_sl"):
                            _record_trade(
                                trades, pos, evt_price, pv, spread_pips,
                                i, entry_idx, bar_mins, entry_pattern,
                            )
                            if trades[-1]["result"] == "LOSS":
                                cooldown_until = i + COOLDOWN_BARS
                            pos    = None
                            closed = True
                            break
                    if closed:
                        break
            else:
                # No M1 data — evaluate against M5 bar directly
                events = tradelib.check_position_events(pos, row, ind)
                for evt_name, evt_price in events:
                    if evt_name in ("close_tp", "close_sl"):
                        _record_trade(
                            trades, pos, evt_price, pv, spread_pips,
                            i, entry_idx, bar_mins, entry_pattern,
                        )
                        if trades[-1]["result"] == "LOSS":
                            cooldown_until = i + COOLDOWN_BARS
                        pos    = None
                        closed = True
                        break

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
        h1_end = h1_times.searchsorted(ts, side="right")
        if h1_end < 3:
            continue

        df_4h_slice = None
        if h4_times is not None:
            h4_end      = h4_times.searchsorted(ts, side="right")
            df_4h_slice = df_4h.iloc[:h4_end] if h4_end > 0 else None

        df_1d_slice = None
        if d_times is not None:
            d_end       = d_times.searchsorted(ts, side="right")
            df_1d_slice = df_1d.iloc[:d_end] if d_end > 0 else None

        if hasattr(ind, "DAILY_ADX_MIN"):
            bias_info = ind.assess_h1_bias(
                df_h1.iloc[:h1_end], df_4h=df_4h_slice, df_1d=df_1d_slice
            )
        else:
            bias_info = ind.assess_h1_bias(
                df_h1.iloc[:h1_end], df_4h=df_4h_slice
            )

        bias = bias_info["direction"]
        if bias == "FLAT":
            continue

        # ── Entry pattern ─────────────────────────────────────────────────────
        m5_slice     = merged.iloc[max(0, i - 35): i + 1]
        entry_result = ind.find_m5_entry(m5_slice, bias, use_session=False)
        if entry_result is None:
            continue
        if entry_result["bar_time"] != str(ts):
            continue

        # ── Compute SL/TP and open position ───────────────────────────────────
        h1_atr = row.get("h1_atr")
        atr    = float(h1_atr) if not pd.isna(h1_atr) else bias_info["atr"]
        spread = spread_pips * pv

        sl_tp = ind.compute_sl_tp(entry_result, bias, atr, spread, pv)
        if sl_tp is None:
            continue
        entry_p, sl, tp = sl_tp

        # Advance entry to next bar's open: the live daemon places the order
        # after the signal bar closes, so it fills at the following bar's open.
        if i + 1 >= len(merged):
            continue
        next_open    = float(merged.iloc[i + 1]["open"])
        sl_pips_dist = abs(entry_p - sl) / pv
        tp_pips_dist = abs(tp - entry_p) / pv
        if bias == "BUY":
            entry_p = next_open
            sl      = entry_p - sl_pips_dist * pv
            tp      = entry_p + tp_pips_dist * pv
            if next_open <= sl:
                continue
        else:
            entry_p = next_open
            sl      = entry_p + sl_pips_dist * pv
            tp      = entry_p - tp_pips_dist * pv
            if next_open >= sl:
                continue

        risk_pips   = abs(entry_p - sl) / pv
        reward_pips = abs(tp - entry_p) / pv
        rr_ratio    = reward_pips / risk_pips if risk_pips > 0 else 0.0

        pos = tradelib.Position(
            pair         = pair,
            symbol       = pair.upper(),
            direction    = bias,
            trade_type   = "automated",
            entry_price  = entry_p,
            stop_loss    = sl,
            take_profit  = tp,
            atr          = atr,
            risk_pips    = risk_pips,
            reward_pips  = reward_pips,
            rr_ratio     = rr_ratio,
            opened_at    = str(ts),
            basis        = entry_result.get("pattern", ""),
            original_tp  = tp,
        )
        entry_idx     = i
        entry_pattern = entry_result.get("pattern", "")

    return trades


def _record_trade(
    trades:       list[dict],
    pos:          tradelib.Position,
    exit_price:   float,
    pv:           float,
    spread_pips:  float,
    bar_idx:      int,
    entry_idx:    int,
    bar_mins:     int,
    pattern:      str,
) -> None:
    held     = bar_idx - entry_idx
    pnl_pips = (
        (exit_price - pos.entry_price) / pv
        * (1 if pos.direction == "BUY" else -1)
    ) - spread_pips
    result = "WIN" if pnl_pips > 0 else "LOSS"
    trades.append({
        "entry_time": pos.opened_at,
        "direction":  pos.direction,
        "entry":      round(pos.entry_price, 5),
        "exit":       round(exit_price, 5),
        "sl":         round(pos.stop_loss, 5),
        "tp":         round(pos.take_profit, 5),
        "held_bars":  held,
        "held_mins":  held * bar_mins,
        "pnl_pips":   round(pnl_pips, 1),
        "result":     result,
        "forced":     False,
        "pattern":    pattern,
        "extended":   pos.tp_extended,
    })


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

    # Derive trading days from actual trade timestamps if available
    try:
        first = pd.Timestamp(df["entry_time"].iloc[0])
        last  = pd.Timestamp(df["entry_time"].iloc[-1])
        trading_days = max(1, (last - first).days)
    except Exception:
        trading_days = 730 if bar_mins >= 60 else 60

    return dict(
        n=len(df), wins=len(wins), losses=len(losses),
        wr=wr, aw=aw, al=al, exp=exp, total=total, pf=pf,
        max_dd=max_dd, trades_per_day=len(df) / trading_days,
        avg_mins=df["held_mins"].mean(), forced=int(df["forced"].sum()),
    )


def _compute_sizing(
    trades: list[dict], pair: str, account: float, risk_pct: float
) -> tuple[list[float], str]:
    """Return per-trade position sizes (lots) and the unit label."""
    risk_dollars = account * risk_pct / 100
    LOT_SIZE     = 100_000
    is_jpy       = "jpy" in pair.lower()

    sizes = []
    for t in trades:
        stop_dist = abs(t["entry"] - t["sl"])
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

    console.print(table)

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
    args = parser.parse_args()

    do_update = not args.no_update

    if args.seed:
        console.print("[bold cyan]Seeding OANDA data library (this may take a few minutes)...[/]")
        datalib.update_all()
        do_update = False

    target_pairs = ACTIVE_PAIRS if args.all else [args.pair]
    bar_mins     = 60 if args.long else 5
    mode_desc    = "long mode · H1 bars" if args.long else "scalp mode · M5 + M1 sim"
    all_results: list[tuple[str, list[dict]]] = []

    for pair_key in target_pairs:
        ind        = PAIR_INDICATORS[pair_key]
        cfg        = PAIR_CONFIG[pair_key]
        pair_label = pair_key.upper()
        use_sess   = cfg.get("use_session", True)

        if args.no_blocked_days and hasattr(ind, "BLOCKED_DAYS"):
            ind.BLOCKED_DAYS = frozenset()

        console.print(f"[bold cyan]Running {pair_label} ({mode_desc})...[/]")

        if args.long:
            df_trend, df_entry = fetch_data_long(pair_key, ind, update=do_update)
            trades = run_backtest(
                df_trend, df_entry, bar_mins=60,
                spread_pips=cfg["spread_long"], use_session=False,
                pair=pair_key, ind=ind,
            )
        else:
            df_h1, df_4h, df_5m, df_1d, df_m1 = fetch_data(
                pair_key, ind, update=do_update
            )
            trades = run_backtest(
                df_h1, df_5m, bar_mins=5,
                spread_pips=cfg["spread_scalp"], use_session=use_sess,
                pair=pair_key, ind=ind,
                df_4h=df_4h, df_1d=df_1d, df_m1=df_m1,
            )

        report(trades, bar_mins=bar_mins, pair_label=pair_label,
               account=args.account, risk_pct=args.risk)
        all_results.append((pair_label, trades))

    if args.all:
        report_all(all_results, bar_mins=bar_mins)
