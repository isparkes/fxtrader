#!/usr/bin/env python3
"""
forward_test_fx.py — Summarise fx_trades.jsonl as a forward-test table.

Usage:
    python forward_test_fx.py [path/to/fx_trades.jsonl]

Columns match the backtest summary table in README.md.
Prints one table per ISO week followed by an overall total table.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rich import box
from rich.console import Console
from rich.table import Table

PAIR_ORDER = ["eurusd", "gbpusd", "usdjpy", "audusd", "btcusd"]
BTC_PAIRS  = {"btcusd"}

console = Console()


def parse_opened_at(opened_at: str) -> datetime:
    """Parse the 'opened_at' field, e.g. '2026-04-27 07:26 UTC'."""
    return datetime.strptime(opened_at, "%Y-%m-%d %H:%M %Z").replace(tzinfo=timezone.utc)


def load_closed_trades(path: Path, month_filter: tuple[int, int] | None = None) -> list[dict]:
    trades = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("event") != "close":
                continue
            if month_filter is not None:
                opened_at = parse_opened_at(ev["opened_at"])
                if (opened_at.year, opened_at.month) != month_filter:
                    continue
            trades.append({
                "pair":     ev["pair"].lower(),
                "ts":       ev["ts"],
                "pnl_pips": float(ev["pnl_pips"]),
                "result":   "WIN" if float(ev["pnl_pips"]) > 0 else "LOSS",
            })
    return trades


def compute_stats(trades: list[dict]) -> dict:
    df = pd.DataFrame(trades)
    wins   = df[df["result"] == "WIN"]
    losses = df[df["result"] == "LOSS"]
    wr     = len(wins) / len(df) * 100
    aw     = wins["pnl_pips"].mean()        if len(wins)   else 0.0
    al     = abs(losses["pnl_pips"].mean()) if len(losses) else 0.0
    exp    = (wr / 100 * aw) - ((1 - wr / 100) * al)
    total  = df["pnl_pips"].sum()
    pf     = (wins["pnl_pips"].sum() / abs(losses["pnl_pips"].sum())
              if len(losses) and losses["pnl_pips"].sum() != 0 else float("inf"))
    cum    = df["pnl_pips"].cumsum()
    max_dd = (cum - cum.cummax()).min()
    return dict(n=len(df), wins=len(wins), losses=len(losses),
                wr=wr, aw=aw, al=al, exp=exp, total=total, pf=pf, max_dd=max_dd)


def fmt_date(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d")


def week_key(ts: str) -> str:
    dt  = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def print_table(title: str, by_pair: dict[str, list[dict]]) -> None:
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Pair",         style="bold")
    table.add_column("Trades",       justify="right")
    table.add_column("Win %",        justify="right")
    table.add_column("Avg Win",      justify="right")
    table.add_column("Avg Loss",     justify="right")
    table.add_column("Prof. Factor", justify="right")
    table.add_column("Expectancy",   justify="right")
    table.add_column("Total",        justify="right")
    table.add_column("Max DD",       justify="right")
    table.add_column("Unit",         justify="left")

    pairs_seen  = [p for p in PAIR_ORDER if p in by_pair]
    pairs_seen += sorted(p for p in by_pair if p not in PAIR_ORDER)

    for pair in pairs_seen:
        s       = compute_stats(by_pair[pair])
        unit    = "USD" if pair in BTC_PAIRS else "pips"
        pf_str  = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
        pip_col = "green" if s["total"] > 0 else "red"
        table.add_row(
            pair.upper(),
            str(s["n"]),
            f"{s['wr']:.1f}%",
            f"{s['aw']:.1f}",
            f"{s['al']:.1f}",
            f"[bold]{pf_str}[/]",
            f"{s['exp']:+.1f}",
            f"[{pip_col}]{s['total']:+.1f}[/]",
            f"[red]{s['max_dd']:.1f}[/]",
            unit,
        )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise fx_trades.jsonl as a forward-test table.", prog="forward_test_fx.py")
    parser.add_argument("file", nargs="?", default="fx_trades.jsonl", help="Path to trades JSONL file")
    parser.add_argument("--month", metavar="YYYY-MM", help="Only include trades opened in this month, e.g. 2026-04")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    month_filter: tuple[int, int] | None = None
    if args.month:
        try:
            dt = datetime.strptime(args.month, "%Y-%m")
            month_filter = (dt.year, dt.month)
        except ValueError:
            print(f"Invalid --month format '{args.month}', expected YYYY-MM", file=sys.stderr)
            sys.exit(1)

    all_trades = load_closed_trades(path, month_filter)
    if not all_trades:
        print("No closed trades found.", file=sys.stderr)
        sys.exit(1)

    timestamps = [t["ts"] for t in all_trades]
    period     = f"{fmt_date(min(timestamps))} → {fmt_date(max(timestamps))}"

    # ── Weekly tables ─────────────────────────────────────────────────────────
    by_week: dict[str, list[dict]] = defaultdict(list)
    for t in all_trades:
        by_week[week_key(t["ts"])].append(t)

    for wk in sorted(by_week.keys()):
        year, num = int(wk[:4]), int(wk[6:])
        mon = datetime.fromisocalendar(year, num, 1)
        sun = datetime.fromisocalendar(year, num, 7)
        title = f"{wk}  ({mon.strftime('%b %d')} – {sun.strftime('%b %d')})"
        by_pair: dict[str, list[dict]] = defaultdict(list)
        for t in by_week[wk]:
            by_pair[t["pair"]].append(t)
        print_table(title, by_pair)

    # ── Overall total ─────────────────────────────────────────────────────────
    by_pair_all: dict[str, list[dict]] = defaultdict(list)
    for t in all_trades:
        by_pair_all[t["pair"]].append(t)

    print_table(f"Total  ({period})", by_pair_all)


if __name__ == "__main__":
    main()
