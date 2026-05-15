#!/usr/bin/env python3
"""
Analyses fx_trades.jsonl and crypto_trades.jsonl, producing backtest-style
performance tables: overall (per pair), monthly, weekly, daily, by regime,
and by pattern.

Usage:
    python trade_review.py
    python trade_review.py --fx path/to/fx_trades.jsonl --crypto path/to/crypto_trades.jsonl
"""

import json
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional

from rich.console import Console
from rich.table import Table
from rich import box

BASE = Path(__file__).parent
console = Console()

FX_PAIRS = {"eurusd", "usdjpy", "audusd", "gbpusd"}
PAIR_ORDER = ["eurusd", "usdjpy", "audusd", "gbpusd", "btcusd"]

_PAT_ORDER = ["A — EMA cross", "C — MACD flip", "D — HA pullback", "E — Supertrend", "?"]
_PAT_KWS = [
    ("HA pullback",     "D — HA pullback"),
    ("Supertrend flip", "E — Supertrend"),
    ("MACD flip",       "C — MACD flip"),
    ("EMA8/21 cross",   "A — EMA cross"),
    ("EMA cross",       "A — EMA cross"),
]


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Trade:
    pair: str
    direction: str
    pnl: float
    reason: str       # close_sl | close_tp | close_manual
    pattern: str      # A — EMA cross | C — MACD flip | D — HA pullback | E — Supertrend | ?
    regime: str       # TREND_UP | TREND_DOWN | ?
    opened_ts: datetime
    closed_ts: datetime
    hold_mins: float
    unit: str         # pips | USD
    rr: float


# ─── Parsing ──────────────────────────────────────────────────────────────────

def _extract_pattern(basis: str) -> str:
    for kw, label in _PAT_KWS:
        if kw in basis:
            return label
    return "?"


def _extract_regime(basis: str) -> str:
    if "above EMA50" in basis:
        return "TREND_UP"
    if "below EMA50" in basis:
        return "TREND_DOWN"
    return "?"


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(path: Path) -> list[Trade]:
    if not path.exists():
        return []
    opens: dict[tuple, dict] = {}
    result: list[Trade] = []
    with path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            ev = json.loads(raw)
            key = (ev["pair"], ev["opened_at"])
            if ev["event"] == "open":
                opens[key] = ev
            elif ev["event"] == "close":
                op = opens.pop(key, None)
                if op is None:
                    continue
                opened = _ts(op["ts"])
                closed = _ts(ev["ts"])
                result.append(Trade(
                    pair=ev["pair"],
                    direction=op.get("direction", "?"),
                    pnl=ev.get("pnl_pips", 0.0),
                    reason=ev.get("reason", "?"),
                    pattern=_extract_pattern(op.get("basis", "")),
                    regime=_extract_regime(op.get("basis", "")),
                    opened_ts=opened,
                    closed_ts=closed,
                    hold_mins=(closed - opened).total_seconds() / 60,
                    unit="USD" if ev["pair"] == "btcusd" else "pips",
                    rr=op.get("rr", 0.0),
                ))
    return result


def find_open_positions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    opens: dict[tuple, dict] = {}
    with path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            ev = json.loads(raw)
            key = (ev["pair"], ev["opened_at"])
            if ev["event"] == "open":
                opens[key] = ev
            elif ev["event"] == "close":
                opens.pop(key, None)
    return list(opens.values())


# ─── Statistics ───────────────────────────────────────────────────────────────

def calc(trades: list[Trade]) -> Optional[dict]:
    if not trades:
        return None
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    n   = len(trades)
    gp  = sum(t.pnl for t in wins)
    gl  = abs(sum(t.pnl for t in losses))
    wr  = len(wins) / n
    aw  = gp / len(wins)   if wins   else 0.0
    al  = gl / len(losses) if losses else 0.0
    pf  = gp / gl if gl else float("inf")
    ex  = wr * aw - (1 - wr) * al
    tot = sum(t.pnl for t in trades)
    cum = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: x.closed_ts):
        cum += t.pnl
        peak = max(peak, cum)
        dd   = max(dd, peak - cum)
    return dict(
        n=n,
        wins=len(wins), losses=len(losses),
        bes=n - len(wins) - len(losses),
        wr=wr, aw=aw, al=al, pf=pf, ex=ex,
        total=tot, dd=dd,
        hold=sum(t.hold_mins for t in trades) / n,
    )


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _v(s: Optional[dict], key: str, fmt: Callable) -> str:
    return fmt(s[key]) if s else "—"


def _pf(x: float) -> str:
    return "∞" if x == float("inf") else f"{x:.2f}"


def _hold(m: float) -> str:
    h, mn = divmod(int(m), 60)
    return f"{h}h {mn:02d}m" if h else f"{mn}m"


pct  = lambda x: f"{x:.1%}"
f1   = lambda x: f"{x:.1f}"
pm   = lambda x: f"{x:+.1f}"
dds  = lambda x: f"-{x:.1f}" if x > 0 else "0"


# ─── Full stats table (overall / regime / pattern) ────────────────────────────

def _full_table(
    title: str,
    rows: list[tuple[str, list[Trade], str]],
    show_hold: bool = True,
) -> Table:
    t = Table(title=title, box=box.SIMPLE_HEAD,
              title_style="bold", header_style="bold cyan",
              show_footer=False, padding=(0, 1))
    t.add_column("",              style="bold", no_wrap=True)
    t.add_column("Trades",        justify="right")
    t.add_column("B/E",           justify="right")
    t.add_column("Win %",         justify="right")
    t.add_column("Avg Win",       justify="right")
    t.add_column("Avg Loss",      justify="right")
    t.add_column("Prof. Factor",  justify="right")
    t.add_column("Expectancy",    justify="right")
    t.add_column("Total",         justify="right")
    t.add_column("Max DD",        justify="right")
    if show_hold:
        t.add_column("Avg Hold",  justify="right")
    t.add_column("Unit",          style="dim")

    for label, trades, unit in rows:
        s = calc(trades)
        row = [
            label,
            _v(s, "n",    str),
            _v(s, "bes",  str),
            _v(s, "wr",   pct),
            _v(s, "aw",   f1),
            _v(s, "al",   f1),
            _v(s, "pf",   _pf),
            _v(s, "ex",   pm),
            _v(s, "total",pm),
            _v(s, "dd",   dds),
        ]
        if show_hold:
            row.append(_v(s, "hold", _hold) if s else "—")
        row.append(unit)
        t.add_row(*row)
    return t


# ─── Period table (day / week / month) ───────────────────────────────────────

def _period_row(label: str, ts: list[Trade]) -> list[str]:
    fx  = [t for t in ts if t.unit == "pips"]
    btc = [t for t in ts if t.unit == "USD"]
    fs, bs = calc(fx), calc(btc)
    return [
        label,
        _v(fs, "n",     str), _v(fs, "wr", pct), _v(fs, "pf", _pf),
        _v(fs, "total", pm),  _v(fs, "dd", dds),
        _v(bs, "n",     str), _v(bs, "wr", pct), _v(bs, "pf", _pf),
        _v(bs, "total", pm),  _v(bs, "dd", dds),
    ]


def _period_table(title: str, rows: list[list[str]]) -> Table:
    t = Table(title=title, box=box.SIMPLE_HEAD,
              title_style="bold", header_style="bold cyan",
              show_footer=False, padding=(0, 1))
    t.add_column("Period", style="bold", no_wrap=True)
    for col in ("FX Trades", "FX Win%", "FX PF", "FX Pips", "FX Max DD"):
        t.add_column(col, justify="right")
    for col in ("BTC Trades", "BTC Win%", "BTC PF", "BTC USD", "BTC Max DD"):
        t.add_column(col, justify="right")
    for row in rows:
        t.add_row(*row)
    return t


# ─── Section printers ─────────────────────────────────────────────────────────

def print_overall(trades: list[Trade]) -> None:
    rows: list[tuple] = []
    fx_all: list[Trade] = []
    for p in PAIR_ORDER:
        if p not in FX_PAIRS:
            continue
        pt = [t for t in trades if t.pair == p]
        if pt:
            rows.append((p.upper(), pt, "pips"))
            fx_all.extend(pt)
    if fx_all:
        rows.append(("── FX total ──", fx_all, "pips"))
    btc = [t for t in trades if t.pair == "btcusd"]
    if btc:
        rows.append(("BTCUSD", btc, "USD"))
    console.print(_full_table("Overall Performance", rows))


def print_monthly(trades: list[Trade]) -> None:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[t.closed_ts.strftime("%Y-%m")].append(t)
    rows = [
        _period_row(datetime.strptime(k, "%Y-%m").strftime("%b %Y"), v)
        for k, v in sorted(groups.items())
    ]
    console.print(_period_table("Monthly Breakdown", rows))


def print_weekly(trades: list[Trade]) -> None:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        iso = t.closed_ts.isocalendar()
        groups[f"{iso.year}-W{iso.week:02d}"].append(t)
    rows = [_period_row(k, v) for k, v in sorted(groups.items())]
    console.print(_period_table("Weekly Breakdown", rows))


def print_daily(trades: list[Trade]) -> None:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[t.closed_ts.strftime("%Y-%m-%d")].append(t)
    rows = [_period_row(k, v) for k, v in sorted(groups.items())]
    console.print(_period_table("Daily Breakdown", rows))


def print_regime(trades: list[Trade]) -> None:
    for label, subset, unit in [
        ("FX pairs", [t for t in trades if t.unit == "pips"], "pips"),
        ("BTCUSD",   [t for t in trades if t.unit == "USD"],  "USD"),
    ]:
        if not subset:
            continue
        rows = [
            (regime, [t for t in subset if t.regime == regime], unit)
            for regime in ("TREND_UP", "TREND_DOWN", "?")
            if any(t.regime == regime for t in subset)
        ]
        console.print(_full_table(f"By Regime — {label} ({unit})", rows, show_hold=False))


def print_pattern(trades: list[Trade]) -> None:
    fx = [t for t in trades if t.unit == "pips"]
    if not fx:
        return
    present = sorted(
        set(t.pattern for t in fx),
        key=lambda p: _PAT_ORDER.index(p) if p in _PAT_ORDER else 99,
    )
    rows = [(p, [t for t in fx if t.pattern == p], "pips") for p in present]
    console.print(_full_table("By Pattern — FX pairs (pips)", rows, show_hold=True))


# ─── Open positions notice ────────────────────────────────────────────────────

def report_open(fx_path: Path, crypto_path: Path) -> None:
    open_pos = find_open_positions(fx_path) + find_open_positions(crypto_path)
    if open_pos:
        console.print(
            f"[yellow]  {len(open_pos)} position(s) still open "
            f"(excluded from all stats):[/yellow]"
        )
        for op in open_pos:
            console.print(f"    {op['pair'].upper():8s}  {op['direction']}  "
                          f"opened {op['opened_at']}")
        console.print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse live trade logs.")
    parser.add_argument("--fx",     default=str(BASE / "fx_trades.jsonl"),
                        help="Path to fx_trades.jsonl (default: %(default)s)")
    parser.add_argument("--crypto", default=str(BASE / "crypto_trades.jsonl"),
                        help="Path to crypto_trades.jsonl (default: %(default)s)")
    args = parser.parse_args()

    fx_path     = Path(args.fx)
    crypto_path = Path(args.crypto)

    trades = load(fx_path) + load(crypto_path)
    trades.sort(key=lambda t: t.closed_ts)

    if not trades:
        console.print("[red]No closed trades found.[/red]")
        return

    ts_start = trades[0].closed_ts.strftime("%Y-%m-%d")
    ts_end   = trades[-1].closed_ts.strftime("%Y-%m-%d")
    n_fx  = sum(1 for t in trades if t.unit == "pips")
    n_btc = sum(1 for t in trades if t.unit == "USD")

    console.print()
    console.rule("[bold]Live Trade Analysis[/bold]")
    console.print(
        f"  {ts_start} → {ts_end}  ·  "
        f"{n_fx} FX trades  ·  {n_btc} BTC trades\n"
    )

    report_open(fx_path, crypto_path)
    print_overall(trades)
    print_monthly(trades)
    print_weekly(trades)
    print_daily(trades)
    print_regime(trades)
    print_pattern(trades)


if __name__ == "__main__":
    main()
