#!/usr/bin/env python3
"""
BT vs Daemon trade comparison
==============================
Side-by-side view of backtest and live daemon trades for a given period,
showing entry time, direction, entry price, exit time, exit price, P&L,
and exit reason.

Usage
-----
    python validate_convergence.py                        # yesterday, all active pairs
    python validate_convergence.py --date 2026-05-27      # specific date
    python validate_convergence.py --days 7               # last N days
    python validate_convergence.py --pair eurusd usdjpy   # specific pairs
"""

import argparse
import json
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")

ACTIVE_PAIRS  = ["eurusd", "usdjpy", "audusd"]
FX_TRADES_LOG = Path("fx_trades.jsonl")
console       = Console(width=180)


def _parse_ts(ts_str: str) -> pd.Timestamp:
    return pd.Timestamp(ts_str.replace("Z", "+00:00")).tz_convert("UTC")


def _fmt_price(val) -> str:
    if val is None:
        return "—"
    # JPY pairs: price > 10, use 3 dp; others use 5 dp
    return f"{val:.3f}" if float(val) > 10 else f"{val:.5f}"


def load_live_trades(pair: str, start: date, end: date) -> list[dict]:
    """Load closed automated trades whose open date falls within [start, end]."""
    opens:  dict = {}
    trades: list = []

    if not FX_TRADES_LOG.exists():
        return []

    with FX_TRADES_LOG.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if rec.get("pair") != pair or rec.get("trade_type") != "automated":
                continue

            if rec["event"] == "open":
                opens[rec.get("trade_id")] = rec

            elif rec["event"] == "close":
                tid      = rec.get("trade_id")
                open_rec = opens.pop(tid, None)
                if open_rec is None:
                    continue
                open_date = _parse_ts(open_rec["ts"]).date()
                if not (start <= open_date <= end):
                    continue
                trades.append({
                    "source":      "daemon",
                    "entry_time":  _parse_ts(open_rec["ts"]),
                    "direction":   open_rec["direction"],
                    "entry_price": open_rec.get("entry"),
                    "exit_time":   _parse_ts(rec["ts"]),
                    "exit_price":  rec.get("exit"),
                    "pnl_pips":    rec["pnl_pips"],
                    "exit_reason": rec.get("reason", ""),
                })

    return sorted(trades, key=lambda t: t["entry_time"])


def load_backtest_trades(pair: str, start: date, end: date) -> list[dict]:
    """Load rows from the pair's backtest CSV whose entry_time falls in [start, end]."""
    csv = Path(f"{pair}_backtest_trades.csv")
    if not csv.exists():
        return []

    df = pd.read_csv(csv)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    mask = (df["entry_time"].dt.date >= start) & (df["entry_time"].dt.date <= end)

    trades = []
    for _, row in df[mask].iterrows():
        held      = int(row.get("held_mins", 0))
        exit_time = row["entry_time"] + pd.Timedelta(minutes=held)

        if row.get("forced", False):
            exit_reason = "forced"
        elif row["result"] == "WIN":
            exit_reason = "TP"
        else:
            exit_reason = "SL"

        trades.append({
            "source":      "BT",
            "entry_time":  row["entry_time"],
            "direction":   row["direction"],
            "entry_price": row.get("entry"),
            "exit_time":   exit_time,
            "exit_price":  row.get("exit"),
            "pnl_pips":    row["pnl_pips"],
            "exit_reason": exit_reason,
        })
    return sorted(trades, key=lambda t: t["entry_time"])


def display_pair(pair: str, bt_rows: list[dict], live_rows: list[dict]) -> None:
    all_rows = sorted(bt_rows + live_rows, key=lambda r: r["entry_time"])
    title = f"{pair.upper()}  —  BT: {len(bt_rows)}    Daemon: {len(live_rows)}"
    table = Table(title=title, box=box.SIMPLE_HEAVY, show_lines=False,
                  title_style="bold")

    table.add_column("Src",                          min_width=6)
    table.add_column("Entry (UTC)",  no_wrap=True,   min_width=16)
    table.add_column("Dir",          justify="center", min_width=5)
    table.add_column("Entry Px",     justify="right",  min_width=9)
    table.add_column("Exit (UTC)",   no_wrap=True,   min_width=16)
    table.add_column("Exit Px",      justify="right",  min_width=9)
    table.add_column("P&L",          justify="right",  min_width=7)
    table.add_column("Exit Reason",  style="dim",    min_width=12)

    _DIR_STYLE = {"BUY": "green", "SELL": "red"}

    for r in all_rows:
        pnl     = r["pnl_pips"]
        pnl_str = f"+{pnl:.1f}" if pnl > 0 else f"{pnl:.1f}"
        pnl_col = f"[{'green' if pnl > 0 else 'red'}]{pnl_str}[/]"
        dir_col = f"[{_DIR_STYLE.get(r['direction'], '')}]{r['direction']}[/]"
        src_col = r["source"]

        entry_t = r["entry_time"].strftime("%Y-%m-%d %H:%M")
        exit_t  = r["exit_time"].strftime("%Y-%m-%d %H:%M")

        table.add_row(
            src_col,
            entry_t,
            dir_col,
            _fmt_price(r["entry_price"]),
            exit_t,
            _fmt_price(r["exit_price"]),
            pnl_col,
            r["exit_reason"],
        )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare backtest vs daemon trades",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD",
                        help="Single date to analyse (default: yesterday)")
    parser.add_argument("--days", type=int, default=1, metavar="N",
                        help="Number of past days to analyse (default: 1 = yesterday)")
    parser.add_argument("--pair", nargs="+", metavar="PAIR",
                        help=f"Pairs to check (default: all active — {', '.join(ACTIVE_PAIRS)})")
    args = parser.parse_args()

    if args.date:
        end_date   = date.fromisoformat(args.date)
        start_date = end_date - timedelta(days=args.days - 1)
    else:
        end_date   = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=args.days - 1)

    pairs = [p.lower() for p in args.pair] if args.pair else ACTIVE_PAIRS

    console.rule(
        f"[bold]BT vs Daemon  {start_date} → {end_date}[/]"
        if start_date != end_date else
        f"[bold]BT vs Daemon  {end_date}[/]"
    )

    for pair in pairs:
        bt_rows   = load_backtest_trades(pair, start_date, end_date)
        live_rows = load_live_trades(pair, start_date, end_date)
        if bt_rows or live_rows:
            display_pair(pair, bt_rows, live_rows)
        else:
            console.print(f"[dim]{pair.upper()}: no trades found.[/]\n")


if __name__ == "__main__":
    main()
