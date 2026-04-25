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
carries the most recently started trend bar's values forward-filled.

Simulation rules
----------------
  - Trend bias and entry patterns are evaluated by calling the indicator
    module directly (ind.assess_h1_bias, ind.find_m5_entry, ind.compute_sl_tp).
    No indicator logic is reimplemented here.
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
from typing import Optional

import pandas as pd
import yfinance as yf
from ta.trend import EMAIndicator
from rich.console import Console
from rich.table import Table
from rich import box

import indicator_eurusd
import indicator_gbpusd
import indicator_usdjpy
import indicator_audusd
import indicator_btcusd

PAIRS: dict[str, str] = {
    "eurusd": "EURUSD=X",
    "gbpusd": "GBPUSD=X",
    "usdjpy": "USDJPY=X",
    "audusd": "AUDUSD=X",
    "btcusd": "BTC-USD",
}

PAIR_INDICATORS = {
    "eurusd": indicator_eurusd,
    "gbpusd": indicator_gbpusd,
    "usdjpy": indicator_usdjpy,
    "audusd": indicator_audusd,
    "btcusd": indicator_btcusd,
}

# ── Per-pair spread defaults ──────────────────────────────────────────────────
# spread_scalp: typical spread in pips for 5m scalp mode
# spread_long:  slightly tighter spread assumed for 1h long mode
# use_session:  False for 24/7 instruments like BTC
PAIR_CONFIG: dict[str, dict] = {
    "eurusd": {"spread_scalp": 1.5, "spread_long": 1.0},
    "gbpusd": {"spread_scalp": 1.8, "spread_long": 1.2},
    "usdjpy": {"spread_scalp": 1.5, "spread_long": 1.0},
    "audusd": {"spread_scalp": 1.8, "spread_long": 1.2},
    "usdcad": {"spread_scalp": 2.0, "spread_long": 1.5},
    "usdchf": {"spread_scalp": 2.0, "spread_long": 1.5},
    "nzdusd": {"spread_scalp": 2.5, "spread_long": 2.0},
    "eurgbp": {"spread_scalp": 1.5, "spread_long": 1.0},
    # BTC: spread in dollars (pip_value=1.0); no session gate
    "btcusd": {"spread_scalp": 20, "spread_long": 15, "use_session": False},
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


def _to_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if idx.tzinfo is None:
        return idx.tz_localize("UTC")
    return idx.tz_convert("UTC")


def merge_trend(df_h1: pd.DataFrame, df_5m: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill the trend bar's ATR onto entry bars using merge_asof.

    Each entry bar receives the ATR from the most recently started trend bar
    (direction="backward"). Both indexes are normalised to UTC before merging.
    The column added to the entry bars is:
        h1_atr  — trend ATR, used for SL/TP sizing
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


def fetch_data(symbol: str, ind) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Scalp mode: 1h trend + 4h filter (Measure 4) + 5m entry bars (~60 days)."""
    df_h1 = yf.download(symbol, interval="1h", period="60d", progress=False, auto_adjust=True)
    df_h1 = flatten_columns(df_h1)
    df_h1.dropna(inplace=True)
    df_h1 = ind.compute_h1_indicators(df_h1)

    df_4h = df_h1.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)
    df_4h["ema_4h"] = EMAIndicator(close=df_4h["close"], window=ind.H4_EMA_PERIOD).ema_indicator()

    df_5m = yf.download(symbol, interval="5m", period="60d", progress=False, auto_adjust=True)
    df_5m = flatten_columns(df_5m)
    df_5m.dropna(inplace=True)
    df_5m = ind.compute_m5_indicators(df_5m)

    return df_h1, df_4h, df_5m


def fetch_data_long(symbol: str, ind) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long mode: 4h trend (resampled) + 1h entry bars (~730 days)."""
    df_1h = yf.download(symbol, interval="1h", period="730d", progress=False, auto_adjust=True)
    df_1h = flatten_columns(df_1h)
    df_1h.dropna(inplace=True)

    df_4h = df_1h.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)

    df_1h_entry = ind.compute_m5_indicators(df_1h.copy())

    return df_4h, df_1h_entry


def run_backtest(df_h1: pd.DataFrame, df_5m: pd.DataFrame,
                 bar_mins: int = 5, spread_pips: float = SPREAD_PIPS,
                 use_session: bool = True, symbol: str = "EURUSD=X",
                 ind=None, df_4h: Optional[pd.DataFrame] = None) -> list[dict]:
    """
    Walk forward through the merged entry bars, simulating trades.

    Bias and entry evaluation are fully delegated to the indicator module:
        ind.assess_h1_bias(slice)      — trend direction and ATR
        ind.find_m5_entry(slice, bias) — entry pattern detection
        ind.compute_sl_tp(...)         — SL/TP calculation

    Args:
        df_h1:        Trend-context bars with indicators already computed.
        df_5m:        Entry bars with indicators already computed.
        bar_mins:     Duration of one entry bar in minutes.
        spread_pips:  Spread cost deducted from every trade's P&L.
        use_session:  If True, entries are restricted to 07:00–16:00 UTC.

    Returns a list of trade dicts.
    """
    # Forward-fill trend ATR onto entry bars; normalises both indexes to UTC
    merged = merge_trend(df_h1, df_5m)
    bars   = merged.reset_index()

    # Keep df_h1 UTC-normalised for slicing inside the loop
    df_h1 = df_h1.copy()
    df_h1.index = _to_utc(df_h1.index)
    h1_times = df_h1.index

    # Normalise 4h index for Measure 4 slicing (None = gate disabled)
    if df_4h is not None:
        df_4h = df_4h.copy()
        df_4h.index = _to_utc(df_4h.index)
    h4_times = df_4h.index if df_4h is not None else None

    pv = ind.pip_value(symbol)

    trades         = []
    in_trade       = False
    cooldown_until = 0
    trailing_sl    = None
    trail_distance = None
    be_activated   = False
    direction = entry_p = sl = tp = entry_idx = atr = None
    trail_activate_at = None

    for i in range(30, len(bars)):
        row = bars.iloc[i]
        ts  = row.iloc[0]   # UTC-aware timestamp (from merge_trend normalisation)

        if in_trade:
            high = float(row["high"])
            low  = float(row["low"])
            held = i - entry_idx

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

            hit_sl = (direction == "BUY"  and low  <= trailing_sl) or \
                     (direction == "SELL" and high >= trailing_sl)
            hit_tp = (direction == "BUY"  and high >= tp) or \
                     (direction == "SELL" and low  <= tp)

            if hit_tp or hit_sl:
                exit_p   = tp if hit_tp else trailing_sl
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
                    "forced":    False,
                })
                if result == "LOSS":
                    cooldown_until = i + COOLDOWN_BARS
                in_trade = False
            continue

        if use_session and not (SESSION_START_UTC <= ts.hour < SESSION_END_UTC):
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
        bias_info = ind.assess_h1_bias(df_h1.iloc[:h1_end], df_4h=df_4h_slice)
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

        # ── Sizing ────────────────────────────────────────────────────────────
        h1_atr = row.get("h1_atr")
        atr    = float(h1_atr) if not pd.isna(h1_atr) else bias_info["atr"]
        spread = spread_pips * pv

        sl_tp = ind.compute_sl_tp(entry_result, bias, atr, spread, pv)
        if sl_tp is None:
            continue
        entry_p, sl, tp = sl_tp

        in_trade          = True
        direction         = bias
        entry_idx         = i
        be_activated      = False
        trailing_sl       = sl
        trail_distance    = atr * ind.ATR_SL_MULT
        tp_distance_pips  = abs(tp - entry_p) / pv
        trail_frac        = getattr(ind, "TRAIL_ACTIVATE_FRAC", TRAIL_ACTIVATE_FRAC)
        trail_activate_at = tp_distance_pips * trail_frac

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


def _compute_sizing(trades: list[dict], pair: str, account: float, risk_pct: float) -> tuple[list[float], str]:
    """
    Return per-trade position sizes and the unit label ("BTC" or "lots").

    Sizing formula: size = risk_dollars / stop_dollars_per_unit
      BTC      : stop is already in USD, so size = risk / stop_dist  (BTC)
      JPY pairs: quote is JPY, so stop_dist / entry converts to USD per unit
                 lots = risk * entry / (stop_dist * 100_000)
      USD pairs: quote is USD, lots = risk / (stop_dist * 100_000)
    """
    risk_dollars = account * risk_pct / 100
    LOT_SIZE     = 100_000
    is_btc = "BTC" in pair.upper()
    is_jpy = "JPY" in pair.upper()

    sizes = []
    for t in trades:
        stop_dist = abs(t["entry"] - t["sl"])
        if stop_dist == 0:
            sizes.append(0.0)
            continue
        if is_btc:
            sizes.append(risk_dollars / stop_dist)
        elif is_jpy:
            sizes.append(risk_dollars * t["entry"] / (stop_dist * LOT_SIZE))
        else:
            sizes.append(risk_dollars / (stop_dist * LOT_SIZE))

    unit = "BTC" if is_btc else "lots"
    return sizes, unit


def report(trades: list[dict], bar_mins: int = 5, pair_label: str = "EURUSD",
           account: float = 10_000, risk_pct: float = 1.0) -> None:
    """Print a summary table and save the full trade log to CSV."""
    if not trades:
        console.print("[yellow]No trades generated.[/]")
        return

    s = _compute_stats(trades, bar_mins)
    sizes, size_unit = _compute_sizing(trades, pair_label, account, risk_pct)
    avg_size = sum(sizes) / len(sizes) if sizes else 0.0
    min_size = min(sizes) if sizes else 0.0
    max_size = max(sizes) if sizes else 0.0
    size_fmt = ".4f" if size_unit == "BTC" else ".2f"

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

    table.add_row("Total trades",  str(s["n"]))
    table.add_row("Trades / day",  f"{s['trades_per_day']:.1f}")
    table.add_row("Wins",          str(s["wins"]))
    table.add_row("Losses",        str(s["losses"]))
    table.add_row("Win rate",      f"{s['wr']:.1f}%")
    table.add_row("Avg win",       f"{s['aw']:.1f} pips")
    table.add_row("Avg loss",      f"{s['al']:.1f} pips")
    table.add_row("Profit factor", f"{s['pf']:.2f}")
    table.add_row("Expectancy",    f"{s['exp']:.1f} pips/trade")
    table.add_row("Total pips",    f"[{'green' if s['total'] > 0 else 'red'}]{s['total']:.1f}[/]")
    table.add_row("Max drawdown",  f"[red]{s['max_dd']:.1f} pips[/]")
    table.add_row("Avg hold time", hold_str)
    table.add_row("Forced closes", str(s["forced"]))
    table.add_row("──────────────", "──────────────")
    table.add_row("Account / risk",
                  f"${account:,.0f}  ·  {risk_pct:.1f}%  =  ${account * risk_pct / 100:.0f}/trade")
    table.add_row(f"Avg size",
                  f"{avg_size:{size_fmt}} {size_unit}")
    table.add_row(f"Size range",
                  f"{min_size:{size_fmt}} – {max_size:{size_fmt}} {size_unit}")

    console.print(table)

    df = pd.DataFrame(trades)
    df["suggested_size"] = sizes
    df["size_unit"]      = size_unit
    csv_path = f"{pair_label.lower()}_backtest_trades.csv"
    df.to_csv(csv_path, index=False)
    console.print(f"\n[dim]Full trade log saved to {csv_path}[/]")


def report_all(results: list[tuple[str, list[dict]]], bar_mins: int = 5) -> None:
    """Print a combined comparison table for all pairs."""
    mode_label = "730d · 1h bars" if bar_mins >= 60 else "60d · 5m bars"

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

    rows = [(lbl, _compute_stats(t, bar_mins) if t else None) for lbl, t in results]
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
    parser.add_argument("--account", type=float, default=10_000,
                        help="Account size in USD for position sizing (default: 10000)")
    parser.add_argument("--risk", type=float, default=1.0,
                        help="Risk per trade as %% of account (default: 1.0)")
    args = parser.parse_args()

    if args.all:
        bar_mins  = 60 if args.long else 5
        mode_desc = "long mode · 730d · 1h bars" if args.long else "scalp mode · 60d · 5m bars"
        console.print(f"[bold cyan]Running all pairs ({mode_desc})...[/]")
        all_results: list[tuple[str, list[dict]]] = []
        for pair_key in PAIRS:
            symbol     = PAIRS[pair_key]
            pair_label = pair_key.upper()
            cfg        = PAIR_CONFIG[pair_key]
            ind        = PAIR_INDICATORS[pair_key]
            console.print(f"  [dim]Fetching {pair_label}...[/]")
            use_sess = cfg.get("use_session", True)
            if args.long:
                df_trend, df_entry = fetch_data_long(symbol, ind)
                trades = run_backtest(df_trend, df_entry, bar_mins=60,
                                      spread_pips=cfg["spread_long"], use_session=False,
                                      symbol=symbol, ind=ind)
                report(trades, bar_mins=60, pair_label=pair_label,
                       account=args.account, risk_pct=args.risk)
            else:
                df_trend, df_4h, df_entry = fetch_data(symbol, ind)
                trades = run_backtest(df_trend, df_entry, bar_mins=5,
                                      spread_pips=cfg["spread_scalp"], use_session=use_sess,
                                      symbol=symbol, ind=ind, df_4h=df_4h)
                report(trades, bar_mins=5, pair_label=pair_label,
                       account=args.account, risk_pct=args.risk)
            all_results.append((pair_label, trades))
        report_all(all_results, bar_mins=bar_mins)
    else:
        symbol     = PAIRS[args.pair]
        pair_label = args.pair.upper()
        cfg        = PAIR_CONFIG[args.pair]
        ind        = PAIR_INDICATORS[args.pair]

        use_sess = cfg.get("use_session", True)
        if args.long:
            console.print(f"[bold cyan]Running {pair_label} Scalper backtest (long mode · 730d · 1h bars)...[/]")
            df_trend, df_entry = fetch_data_long(symbol, ind)
            trades = run_backtest(df_trend, df_entry, bar_mins=60,
                                  spread_pips=cfg["spread_long"], use_session=False,
                                  symbol=symbol, ind=ind)
            report(trades, bar_mins=60, pair_label=pair_label,
                   account=args.account, risk_pct=args.risk)
        else:
            console.print(f"[bold cyan]Running {pair_label} Scalper backtest (scalp mode · 60d · 5m bars)...[/]")
            df_trend, df_4h, df_entry = fetch_data(symbol, ind)
            trades = run_backtest(df_trend, df_entry, bar_mins=5,
                                  spread_pips=cfg["spread_scalp"], use_session=use_sess,
                                  symbol=symbol, ind=ind, df_4h=df_4h)
            report(trades, bar_mins=5, pair_label=pair_label,
                   account=args.account, risk_pct=args.risk)
