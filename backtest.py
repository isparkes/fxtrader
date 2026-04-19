"""
EURUSD Scalper — Walk-forward backtest
=======================================
Simulates the indicator.py strategy against historical data.
Supports two modes selectable via --long:

  Default (scalp mode)
    Trend : 1h bars
    Entry : 5m bars   (~60 days of history from Yahoo Finance)
    Spread: 1.5 pips

  Long mode  (--long)
    Trend : 4h bars resampled from 1h
    Entry : 1h bars   (~730 days of history from Yahoo Finance)
    Spread: 1.0 pip
    The same indicator logic and entry patterns are applied at the larger
    timeframe. ATR-based stops and targets scale automatically so the R:R
    structure is preserved. Use this mode for a statistically larger sample.

In both modes the two datasets are joined with merge_asof so each entry bar
carries the most recently completed trend bar's values forward-filled.

Simulation rules
----------------
  - Entry and trend logic mirrors indicator.py exactly (see its docstring
    for a full description of the filters).
  - One trade at a time; no new entries while a position is open.
  - Cooldown after any losing trade (COOLDOWN_BARS × bar size).
  - Session filter (07:00-16:00 UTC) applies to entries in scalp mode only.
  - No maximum hold duration; trailing stop and hard SL are the sole exits.
  - Spread deducted from every trade's P&L.

Exit hierarchy (checked in order each bar)
-------------------------------------------
  1. Take profit hit  — exit at TP price
  2. Stop loss hit    — exit at trailing_sl
  3. Neither          — hold; update trailing stop if applicable

Trailing stop — two phases
--------------------------
  Phase 1 — breakeven trigger:
    Once price reaches TRAIL_ACTIVATE_FRAC (80%) of the initial TP distance
    the stop is moved to entry price. Risk drops to zero (minus spread).

  Phase 2 — active trail:
    From that point the stop trails ATR x ATR_SL_MULT behind the running
    best price. There is no fixed TP ceiling — the trade runs until the
    trail is hit. The wide ATR_TP_MULT acts only as an absolute cap against
    instant gap moves.

Usage
-----
    python backtest.py            # scalp mode  (~60 days, 5m bars)
    python backtest.py --long     # long mode   (~730 days, 1h bars)
"""

import argparse

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

import indicator_eurusd
import indicator_gbpusd
import indicator_usdjpy
import indicator_audusd
from indicator_eurusd import pip_value

PAIRS: dict[str, str] = {
    "eurusd": "EURUSD=X",
    "gbpusd": "GBPUSD=X",
    "usdjpy": "USDJPY=X",
    "audusd": "AUDUSD=X",
}

PAIR_INDICATORS = {
    "eurusd": indicator_eurusd,
    "gbpusd": indicator_gbpusd,
    "usdjpy": indicator_usdjpy,
    "audusd": indicator_audusd,
}

# ── Per-pair spread defaults ──────────────────────────────────────────────────
# spread_scalp: typical spread in pips for 5m scalp mode
# spread_long:  slightly tighter spread assumed for 1h long mode
PAIR_CONFIG: dict[str, dict] = {
    "eurusd": {"spread_scalp": 1.5, "spread_long": 1.0},
    "gbpusd": {"spread_scalp": 1.8, "spread_long": 1.2},
    "usdjpy": {"spread_scalp": 1.5, "spread_long": 1.0},
    "audusd": {"spread_scalp": 1.8, "spread_long": 1.2},
    "usdcad": {"spread_scalp": 2.0, "spread_long": 1.5},
    "usdchf": {"spread_scalp": 2.0, "spread_long": 1.5},
    "nzdusd": {"spread_scalp": 2.5, "spread_long": 2.0},
    "eurgbp": {"spread_scalp": 1.5, "spread_long": 1.0},
}

console = Console()

SPREAD_PIPS         = 1.5    # typical scalper spread
COOLDOWN_BARS       = 6      # 6 × 5m = 30 min pause after a loss before re-entering
SESSION_START_UTC   = 7      # London open
SESSION_END_UTC     = 16     # NY afternoon / London close
TRAIL_ACTIVATE_FRAC = 0.8    # move SL to breakeven once 80 % of the way to TP


# ─────────────────────────────────────────────────────────────────────────────

def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and flatten MultiIndex columns returned by newer yfinance versions."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df


def fetch_data(symbol: str, ind) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scalp mode: 1h trend + 5m entry bars (~60 days)."""
    df_h1 = yf.download(symbol, interval="1h", period="60d", progress=False, auto_adjust=True)
    df_h1 = flatten_columns(df_h1)
    df_h1.dropna(inplace=True)
    df_h1 = ind.compute_h1_indicators(df_h1)

    df_5m = yf.download(symbol, interval="5m", period="60d", progress=False, auto_adjust=True)
    df_5m = flatten_columns(df_5m)
    df_5m.dropna(inplace=True)
    df_5m = ind.compute_m5_indicators(df_5m)

    return df_h1, df_5m


def fetch_data_long(symbol: str, ind) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long mode: 4h trend (resampled) + 1h entry bars (~730 days)."""
    df_1h = yf.download(symbol, interval="1h", period="730d", progress=False, auto_adjust=True)
    df_1h = flatten_columns(df_1h)
    df_1h.dropna(inplace=True)

    # Resample 1h → 4h for trend context
    df_4h = df_1h.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)

    # 1h bars as entry timeframe — same indicator set, different scale
    df_1h_entry = ind.compute_m5_indicators(df_1h.copy())

    return df_4h, df_1h_entry


def merge_trend(df_h1: pd.DataFrame, df_5m: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill trend-bar columns onto entry bars using merge_asof.

    Each entry bar receives the values from the most recently completed
    trend bar (direction="backward"). This prevents look-ahead bias: a
    5m bar at 09:37 gets the 09:00 1h bar's values, not the 10:00 bar.

    Both indexes are normalised to UTC before merging to avoid timezone
    comparison errors. The following columns are added to the entry bars:
        h1_macd_hist      — trend MACD histogram
        h1_prev_macd_hist — previous trend bar's MACD histogram (for building check)
        h1_ema_trend      — trend EMA50
        h1_atr            — trend ATR (used for SL/TP sizing)
        h1_close          — trend bar close
        h1_rsi            — trend RSI(14)
    """
    # Pull only the columns we need from 1h; add previous-bar MACD for building check
    h1 = df_h1[["macd_hist", "ema_trend", "atr", "close", "rsi"]].copy()
    h1.columns = ["h1_macd_hist", "h1_ema_trend", "h1_atr", "h1_close", "h1_rsi"]
    h1["h1_prev_macd_hist"] = h1["h1_macd_hist"].shift(1)

    # Normalise both indexes to UTC-aware for safe comparison
    def to_utc(idx):
        if idx.tzinfo is None:
            return idx.tz_localize("UTC")
        return idx.tz_convert("UTC")

    h1.index  = to_utc(h1.index)
    df_5m     = df_5m.copy()
    df_5m.index = to_utc(df_5m.index)

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


def h1_direction(row: pd.Series) -> str:
    """
    Derive the trend bias for a single entry bar from its forward-filled
    trend columns. Mirrors the three-gate logic in assess_h1_bias():

        1. Price above/below h1_ema_trend
        2. h1_macd_hist positive/negative AND larger than h1_prev_macd_hist
        3. h1_rsi above/below 50

    Returns "BUY", "SELL", or "FLAT". Returns "FLAT" if any required
    column is NaN (e.g. during indicator warmup at the start of the data).
    """
    h1_close     = row.get("h1_close")
    h1_ema       = row.get("h1_ema_trend")
    h1_macd      = row.get("h1_macd_hist")
    h1_prev_macd = row.get("h1_prev_macd_hist")
    h1_rsi       = row.get("h1_rsi")

    if any(pd.isna(v) for v in [h1_close, h1_ema, h1_macd, h1_prev_macd, h1_rsi]):
        return "FLAT"

    above = float(h1_close) > float(h1_ema)
    below = float(h1_close) < float(h1_ema)
    # MACD building + RSI confirming momentum direction
    bull  = float(h1_macd) > 0 and float(h1_macd) > float(h1_prev_macd) and float(h1_rsi) > 50
    bear  = float(h1_macd) < 0 and float(h1_macd) < float(h1_prev_macd) and float(h1_rsi) < 50

    if above and bull:
        return "BUY"
    if below and bear:
        return "SELL"
    return "FLAT"


def bar_hour_utc(row: pd.Series) -> int:
    """Extract UTC hour from the first column of a reset-index bar row."""
    ts = row.iloc[0]
    if hasattr(ts, "hour"):
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("UTC")
        return ts.hour
    return -1   # unknown — don't filter


def check_entry(bars: pd.DataFrame, i: int, direction: str, atr_min: float) -> float | None:
    """
    Evaluate entry patterns on bar i, given the trend direction.
    Mirrors find_m5_entry() exactly so backtest and live signal use
    identical logic.

    Pre-conditions checked before pattern evaluation:
        - All required indicator columns are non-NaN.
        - 5m ATR >= M5_ATR_MIN (market has enough volatility).

    Pattern A — EMA cross:
        BUY:  EMA8 crosses above EMA21; RSI 52-75; Stoch %K > %D and < 80.
        SELL: EMA8 crosses below EMA21; RSI 25-48; Stoch %K < %D and > 20.

    Pattern C — MACD histogram flip:
        BUY:  MACD hist crosses zero upward; price above EMA21;
              RSI 52-72; Stoch conditions as above.
        SELL: MACD hist crosses zero downward; price below EMA21;
              RSI 28-48; Stoch conditions as above.

    Returns the bar's close price on a match, or None if no pattern fires.
    """
    if i < 3:
        return None

    bar  = bars.iloc[i]
    prev = bars.iloc[i - 1]

    close    = float(bar["close"])
    ema_fast = bar.get("ema_fast")
    ema_slow = bar.get("ema_slow")
    prev_ef  = prev.get("ema_fast")
    prev_es  = prev.get("ema_slow")
    rsi      = bar.get("rsi")
    hist     = bar.get("macd_hist")
    prev_h   = prev.get("macd_hist")
    stoch_k  = bar.get("stoch_k")
    stoch_d  = bar.get("stoch_d")
    atr_m5   = bar.get("atr")

    if any(pd.isna(v) for v in [ema_fast, ema_slow, prev_ef, prev_es, rsi, hist, prev_h,
                                  stoch_k, stoch_d, atr_m5]):
        return None

    ema_fast = float(ema_fast)
    ema_slow = float(ema_slow)
    prev_ef  = float(prev_ef)
    prev_es  = float(prev_es)
    rsi      = float(rsi)
    hist     = float(hist)
    prev_h   = float(prev_h)
    stoch_k  = float(stoch_k)
    stoch_d  = float(stoch_d)
    atr_m5   = float(atr_m5)

    # ATR filter: skip if market is too flat to reach the target
    if atr_m5 < atr_min:
        return None

    if direction == "BUY":
        stoch_ok = stoch_k > stoch_d and stoch_k < 80
        # A: EMA8 crosses above EMA21, RSI and Stochastic confirm
        if ema_fast > ema_slow and prev_ef <= prev_es and 52 < rsi < 75 and stoch_ok:
            return close
        # C: MACD histogram flips positive, RSI and Stochastic confirm
        if hist > 0 and prev_h <= 0 and close > ema_slow and 52 < rsi < 72 and stoch_ok:
            return close

    elif direction == "SELL":
        stoch_ok = stoch_k < stoch_d and stoch_k > 20
        # A: EMA8 crosses below EMA21, RSI and Stochastic confirm
        if ema_fast < ema_slow and prev_ef >= prev_es and 25 < rsi < 48 and stoch_ok:
            return close
        # C: MACD histogram flips negative, RSI and Stochastic confirm
        if hist < 0 and prev_h >= 0 and close < ema_slow and 28 < rsi < 48 and stoch_ok:
            return close

    return None


def run_backtest(df_h1: pd.DataFrame, df_5m: pd.DataFrame,
                 bar_mins: int = 5, spread_pips: float = SPREAD_PIPS,
                 use_session: bool = True, symbol: str = "EURUSD=X",
                 ind=None) -> list[dict]:
    """
    Walk forward through the merged entry bars, simulating trades.

    Args:
        df_h1:        Trend-context bars with indicators already computed.
        df_5m:        Entry bars with indicators already computed.
        bar_mins:     Duration of one entry bar in minutes (5 for scalp
                      mode, 60 for long mode). Used to calculate held_mins.
        spread_pips:  Spread cost deducted from every trade's P&L.
        use_session:  If True, entries are restricted to SESSION_START_UTC
                      through SESSION_END_UTC. Set False for long mode where
                      the 1h bars already smooth out thin periods.

    Returns a list of trade dicts, each containing:
        direction, entry, exit, sl, tp, held_bars, held_mins,
        pnl_pips, result ("WIN"/"LOSS"), forced (always False).
    """
    merged = merge_trend(df_h1, df_5m)
    bars   = merged.reset_index()
    pv     = pip_value(symbol)

    trades         = []
    in_trade       = False
    cooldown_until = 0
    trailing_sl    = None    # live stop level — starts as hard SL, moves to BE, then trails
    trail_distance = None    # distance to trail behind best price once BE is active
    be_activated   = False   # True once the breakeven stop has been triggered
    direction = entry_p = sl = tp = entry_idx = None

    for i in range(30, len(bars)):
        row  = bars.iloc[i]
        hour = bar_hour_utc(row)

        if in_trade:
            high  = float(row["high"])
            low   = float(row["low"])
            held  = i - entry_idx

            # ── Breakeven trigger → active trail ────────────────────────────
            # Phase 1 (be_activated is False):
            #   Once price reaches TRAIL_ACTIVATE_FRAC of the TP distance,
            #   move SL to entry (breakeven). Risk is now zero.
            # Phase 2 (be_activated is True):
            #   Trail the stop behind the running best price at trail_distance.
            #   No fixed TP ceiling — the trail exits when the move exhausts.
            if direction == "BUY":
                if not be_activated:
                    if (high - entry_p) / pv >= trail_activate_at:
                        trailing_sl  = entry_p
                        be_activated = True
                else:
                    new_trail = high - trail_distance
                    if new_trail > trailing_sl:
                        trailing_sl = new_trail
            else:
                if not be_activated:
                    if (entry_p - low) / pv >= trail_activate_at:
                        trailing_sl  = entry_p
                        be_activated = True
                else:
                    new_trail = low + trail_distance
                    if new_trail < trailing_sl:
                        trailing_sl = new_trail

            # ── Exit conditions ──────────────────────────────────────────────
            hit_sl = (direction == "BUY"  and low  <= trailing_sl) or \
                     (direction == "SELL" and high >= trailing_sl)
            hit_tp = (direction == "BUY"  and high >= tp) or \
                     (direction == "SELL" and low  <= tp)
            force = False  # no forced exits — trailing stop and SL/TP handle duration

            if hit_tp or hit_sl or force:
                exit_p   = tp if hit_tp else (trailing_sl if hit_sl else float(row["close"]))
                pnl_pips = ((exit_p - entry_p) / pv) * (1 if direction == "BUY" else -1)
                pnl_pips -= spread_pips

                result = "WIN" if pnl_pips > 0 else "LOSS"
                trades.append({
                    "direction": direction,
                    "entry":     round(entry_p, 5),
                    "exit":      round(exit_p, 5),
                    "sl":        round(trailing_sl, 5),
                    "tp":        round(tp, 5),
                    "held_bars": held,
                    "held_mins": held * bar_mins,
                    "pnl_pips":  round(pnl_pips, 1),
                    "result":    result,
                    "forced":    force and not hit_tp and not hit_sl,
                })
                if result == "LOSS":
                    cooldown_until = i + COOLDOWN_BARS
                in_trade = False
            continue   # don't look for new entries while in trade

        # ── Session filter: only enter during London/NY overlap ──────────────
        if use_session and not (SESSION_START_UTC <= hour < SESSION_END_UTC):
            continue

        if i < cooldown_until:
            continue

        bias = h1_direction(row)
        if bias == "FLAT":
            continue

        atr_sl = ind.ATR_SL_MULT
        atr_tp = ind.ATR_TP_MULT

        ep = check_entry(bars, i, bias, ind.M5_ATR_MIN)
        if ep is None:
            continue

        h1_atr = row.get("h1_atr")
        atr    = float(h1_atr) if not pd.isna(h1_atr) else 0.001
        spread = SPREAD_PIPS * pv

        if bias == "BUY":
            entry_p    = ep + spread
            sl         = entry_p - atr * atr_sl
            tp         = entry_p + atr * atr_tp
        else:
            entry_p    = ep - spread
            sl         = entry_p + atr * atr_sl
            tp         = entry_p - atr * atr_tp

        in_trade          = True
        direction         = bias
        entry_idx         = i
        be_activated      = False
        trailing_sl       = sl                # starts as the hard stop
        trail_distance    = atr * atr_sl      # distance to trail behind best price
        # Pip distance needed before triggering breakeven (80 % of initial TP distance)
        tp_distance_pips  = abs(tp - entry_p) / pv
        trail_activate_at = tp_distance_pips * TRAIL_ACTIVATE_FRAC

    return trades


def _compute_stats(trades: list[dict], bar_mins: int) -> dict:
    """Compute summary statistics for a list of trades. Returns a dict."""
    df = pd.DataFrame(trades)
    wins   = df[df["result"] == "WIN"]
    losses = df[df["result"] == "LOSS"]
    wr     = len(wins) / len(df) * 100
    aw     = wins["pnl_pips"].mean()            if len(wins)   else 0.0
    al     = abs(losses["pnl_pips"].mean())     if len(losses) else 0.0
    exp    = (wr / 100 * aw) - ((1 - wr / 100) * al)
    total  = df["pnl_pips"].sum()
    pf     = (wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
              if len(losses) and losses["pnl_pips"].sum() != 0 else float("inf"))
    cum    = df["pnl_pips"].cumsum()
    max_dd = (cum - cum.cummax()).min()
    trading_days = 730 if bar_mins >= 60 else 60
    return dict(
        n=len(df), wins=len(wins), losses=len(losses),
        wr=wr, aw=aw, al=al, exp=exp, total=total, pf=pf,
        max_dd=max_dd, trades_per_day=len(df) / trading_days,
        avg_mins=df["held_mins"].mean(), forced=int(df["forced"].sum()),
    )


def report(trades: list[dict], bar_mins: int = 5, pair_label: str = "EURUSD") -> None:
    """
    Print a summary table of backtest results and save the full trade log.

    Computes and displays: trade count, trades/day, win rate, avg win/loss,
    profit factor, expectancy, total pips, max drawdown, avg hold time,
    and forced close count.

    Hold time is displayed in minutes for scalp mode (bar_mins=5) and in
    hours for long mode (bar_mins=60). The trading_days denominator used
    to calculate trades/day is inferred from the mode.

    Saves the full trade-by-trade DataFrame to {pair_label}_backtest_trades.csv.
    """
    if not trades:
        console.print("[yellow]No trades generated.[/]")
        return

    s = _compute_stats(trades, bar_mins)

    if bar_mins >= 60:
        hold_str   = f"{s['avg_mins'] / 60:.1f} hrs"
        mode_label = "730d · 1h bars"
    else:
        hold_str   = f"{s['avg_mins']:.0f} min"
        mode_label = "60d · 5m bars"

    table = Table(
        title=f"Backtest Results — {pair_label} Scalper  ({mode_label})",
        box=box.ROUNDED,
    )
    table.add_column("Metric", style="dim")
    table.add_column("Value",  justify="right")

    table.add_row("Total trades",     str(s["n"]))
    table.add_row("Trades / day",     f"{s['trades_per_day']:.1f}")
    table.add_row("Wins",             str(s["wins"]))
    table.add_row("Losses",           str(s["losses"]))
    table.add_row("Win rate",         f"{s['wr']:.1f}%")
    table.add_row("Avg win",          f"{s['aw']:.1f} pips")
    table.add_row("Avg loss",         f"{s['al']:.1f} pips")
    table.add_row("Profit factor",    f"{s['pf']:.2f}")
    table.add_row("Expectancy",       f"{s['exp']:.1f} pips/trade")
    table.add_row("Total pips",       f"[{'green' if s['total'] > 0 else 'red'}]{s['total']:.1f}[/]")
    table.add_row("Max drawdown",     f"[red]{s['max_dd']:.1f} pips[/]")
    table.add_row("Avg hold time",    hold_str)
    table.add_row("Forced closes",    str(s["forced"]))

    console.print(table)

    csv_path = f"{pair_label.lower()}_backtest_trades.csv"
    pd.DataFrame(trades).to_csv(csv_path, index=False)
    console.print(f"\n[dim]Full trade log saved to {csv_path}[/]")


def report_all(results: list[tuple[str, list[dict]]], bar_mins: int = 5) -> None:
    """
    Print a single comparison table covering every pair that was run.

    Columns: Pair | Trades | Win% | Avg W | Avg L | PF | Expectancy | Total pips | Max DD
    Rows are sorted by total pips descending so the best pair floats to the top.
    """
    if bar_mins >= 60:
        mode_label = "730d · 1h bars"
    else:
        mode_label = "60d · 5m bars"

    table = Table(
        title=f"All-Pairs Summary  ({mode_label})",
        box=box.ROUNDED,
    )
    table.add_column("Pair",        style="bold")
    table.add_column("Trades",      justify="right")
    table.add_column("Win %",       justify="right")
    table.add_column("Avg W",       justify="right")
    table.add_column("Avg L",       justify="right")
    table.add_column("Prof. Factor",justify="right")
    table.add_column("Expectancy",  justify="right")
    table.add_column("Total pips",  justify="right")
    table.add_column("Max DD",      justify="right")

    rows = []
    for pair_label, trades in results:
        if not trades:
            rows.append((pair_label, None))
        else:
            rows.append((pair_label, _compute_stats(trades, bar_mins)))

    rows.sort(key=lambda r: r[1]["total"] if r[1] else float("-inf"), reverse=True)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FX Scalper — walk-forward backtest")
    parser.add_argument("--long", action="store_true",
                        help="Run on 1h bars (~730 days) instead of 5m bars (~60 days)")
    parser.add_argument(
        "--pair",
        default="eurusd",
        choices=list(PAIRS.keys()),
        help="Currency pair to backtest (default: eurusd)",
    )
    parser.add_argument("--all", action="store_true",
                        help="Run every pair and show a combined comparison table")
    args = parser.parse_args()

    if args.all:
        bar_mins   = 60 if args.long else 5
        mode_desc  = "long mode · 730d · 1h bars" if args.long else "scalp mode · 60d · 5m bars"
        console.print(f"[bold cyan]Running all pairs ({mode_desc})...[/]")
        all_results: list[tuple[str, list[dict]]] = []
        for pair_key in PAIRS:
            symbol     = PAIRS[pair_key]
            pair_label = pair_key.upper()
            cfg        = PAIR_CONFIG[pair_key]
            ind        = PAIR_INDICATORS[pair_key]
            console.print(f"  [dim]Fetching {pair_label}...[/]")
            if args.long:
                df_trend, df_entry = fetch_data_long(symbol, ind)
                trades = run_backtest(df_trend, df_entry, bar_mins=60,
                                      spread_pips=cfg["spread_long"], use_session=False,
                                      symbol=symbol, ind=ind)
                report(trades, bar_mins=60, pair_label=pair_label)
            else:
                df_trend, df_entry = fetch_data(symbol, ind)
                trades = run_backtest(df_trend, df_entry, bar_mins=5,
                                      spread_pips=cfg["spread_scalp"], use_session=True,
                                      symbol=symbol, ind=ind)
                report(trades, bar_mins=5, pair_label=pair_label)
            all_results.append((pair_label, trades))
        report_all(all_results, bar_mins=bar_mins)
    else:
        symbol     = PAIRS[args.pair]
        pair_label = args.pair.upper()
        cfg        = PAIR_CONFIG[args.pair]
        ind        = PAIR_INDICATORS[args.pair]

        if args.long:
            console.print(f"[bold cyan]Running {pair_label} Scalper backtest (long mode · 730d · 1h bars)...[/]")
            df_trend, df_entry = fetch_data_long(symbol, ind)
            trades = run_backtest(df_trend, df_entry, bar_mins=60,
                                  spread_pips=cfg["spread_long"], use_session=False,
                                  symbol=symbol, ind=ind)
            report(trades, bar_mins=60, pair_label=pair_label)
        else:
            console.print(f"[bold cyan]Running {pair_label} Scalper backtest (scalp mode · 60d · 5m bars)...[/]")
            df_trend, df_entry = fetch_data(symbol, ind)
            trades = run_backtest(df_trend, df_entry, bar_mins=5,
                                  spread_pips=cfg["spread_scalp"], use_session=True,
                                  symbol=symbol, ind=ind)
            report(trades, bar_mins=5, pair_label=pair_label)
