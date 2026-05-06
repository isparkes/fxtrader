#!/usr/bin/env python3
"""
forward_test.py — Summarise fx_trades.jsonl as a forward-test table.

Usage:
    python forward_test.py [path/to/fx_trades.jsonl]

Columns match the backtest summary table in README.md.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rich import box
from rich.console import Console
from rich.table import Table

PAIR_ORDER = ["eurusd", "gbpusd", "usdjpy", "audusd", "btcusd"]
BTC_PAIRS  = {"btcusd"}


def load_closed_trades(path: Path) -> list[dict]:
    trades = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("event") != "close":
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


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fx_trades.jsonl")
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    all_trades = load_closed_trades(path)
    if not all_trades:
        print("No closed trades found.", file=sys.stderr)
        sys.exit(1)

    timestamps = [t["ts"] for t in all_trades]
    period = f"{fmt_date(min(timestamps))} → {fmt_date(max(timestamps))}"

    by_pair: dict[str, list[dict]] = {}
    for t in all_trades:
        by_pair.setdefault(t["pair"], []).append(t)

    console = Console()
    table = Table(title=f"Forward Test  ({period})", box=box.ROUNDED)
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

    pairs_seen = [p for p in PAIR_ORDER if p in by_pair]
    pairs_seen += sorted(p for p in by_pair if p not in PAIR_ORDER)

    for pair in pairs_seen:
        s    = compute_stats(by_pair[pair])
        unit = "USD" if pair in BTC_PAIRS else "pips"
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


if __name__ == "__main__":
    main()
