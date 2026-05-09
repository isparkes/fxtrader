"""
FX Scalper Daemon
=================
Monitors FX currency pairs (EURUSD, GBPUSD, USDJPY, AUDUSD) continuously,
caches market data incrementally, and sends email alerts on four events:

  OPEN   — a new scalp signal fires (entry, SL, TP details)
  BE     — stop-loss moved to breakeven (position still live)
  CLOSE  — trade closed at TP, SL, weekend auto-close, or manual close
  SUMMARY — twice-daily status email (08:00 and 20:00 UTC)

For BTCUSD see daemon_crypto.py.

Data efficiency
---------------
Initial fetch uses compact windows (7 d of 1h, 2 d of 5m) rather than the
60 d / 5 d used by the indicator CLI.  Every subsequent poll fetches only the
most recent bars from Yahoo Finance and merges them with the in-memory cache,
deduplicating by timestamp.  Old bars beyond H1_MAX_BARS / M5_MAX_BARS are
trimmed to cap memory use.

Configuration
-------------
Copy .env.example to .env and fill in your credentials.

Trading mode is controlled by env vars (or the equivalent CLI flags):

  FX_LIVE=false        Paper mode (default) — signals detected, emails sent, no orders placed.
  FX_LIVE=true         Live mode — Oanda market orders placed on every signal.
  FX_DRY_RUN=true      Dry-run — signals detected, no emails sent, no orders placed.
  FX_OCCULT_STOPS=true Occult stops — SL/TP are NOT sent to the broker; the daemon
                       monitors price and closes the trade itself when levels are hit.
                       Defends against stop-hunting by keeping stop levels invisible.
  FX_CTRL_PORT=9876    TCP port for the real-time control console (default 9876).

CLI flags override the env vars:

  --live             same as FX_LIVE=true
  --dry-run          same as FX_DRY_RUN=true
  --occult-stops     same as FX_OCCULT_STOPS=true

Usage
-----
    python daemon_fx.py                         # paper mode — all pairs, poll every 5 min
    python daemon_fx.py --live                  # live mode — place Oanda orders
    python daemon_fx.py --pair eurusd           # single pair
    python daemon_fx.py --interval 60           # poll every 60 s (useful for testing)
    python daemon_fx.py --dry-run               # log events only, no emails or orders

Running as a background process (macOS / Linux)
------------------------------------------------
    nohup python daemon_fx.py >> fxtrader.log 2>&1 &
    echo $! > fxtrader.pid              # save PID to stop later
    kill $(cat fxtrader.pid)            # stop the daemon

Real-time control console
--------------------------
While the daemon is running, connect via telnet to issue commands:

    telnet localhost 9876

Commands:
  status          — running mode, open positions, pause state, occult status
  pause / resume  — suspend/resume both entries and exits
  pause_entry / resume_entry  — control new position entries independently
  pause_exit  / resume_exit   — control automatic position exits independently
  materialise_sl  — place real broker SL orders for all occult-stops positions
  materialise_tp  — place real broker TP orders for all occult-stops positions
  be              — move all open SLs to breakeven (entry price)
  close           — close all open positions at market
  help / quit

For scripted / one-liner use: python fxctl.py status
"""

import os
import sys
import signal
import time
import threading
import socket as _socket
import logging
import argparse
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from ta.trend import EMAIndicator

import indicator_eurusd
import indicator_gbpusd
import indicator_usdjpy
import indicator_audusd
import oanda
import logsetup

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
from mailer import send_email
import tradelog

load_dotenv()

OANDA_RISK_PCT  = float(os.getenv("OANDA_RISK_PCT", "1"))    # percent of account, e.g. 1 = 1%, 0.8 = 0.8%
FX_DATA_SOURCE  = os.getenv("FX_DATA_SOURCE", "yfinance").lower()
FX_OCCULT_STOPS = os.getenv("FX_OCCULT_STOPS", "false").lower() == "true"

# logsetup.configure() is called in __main__ once the CLI args are parsed,
# so that --log-level can override the LOG_LEVEL env var before any logging happens.
log = logging.getLogger("fxtrader.daemon")

# ── Constants ─────────────────────────────────────────────────────────────────
TRAIL_ACTIVATE_FRAC = 0.80   # mirrors backtest.py
COOLDOWN_MINS       = 30     # post-loss lockout
CONTROL_PORT        = int(os.getenv("FX_CTRL_PORT", "9876"))

_GRANULARITY_MAP = {"1h": "H1", "5m": "M5"}  # yfinance → Oanda granularity strings

# Typical spread for each pair during normal liquid hours (pips).
# Entry is rejected when the live spread exceeds 2× this value.
STANDARD_SPREADS: dict[str, float] = {
    "eurusd": 1.0,
    "gbpusd": 1.5,
    "usdjpy": 2.0,
    "audusd": 1.5,
}

# Close all open positions at this UTC hour on Friday before the weekend spread blows out.
WEEKEND_CLOSE_HOUR = 20

# Minimum bars needed for indicator warmup:
#   EMA50 → 50, MACD(12/26/9) → 26, RSI(14) → 14  → ~70 bars safe floor
# We keep a generous buffer well above that.
H1_MAX_BARS = 300   # ~12.5 days of 1h bars
M5_MAX_BARS = 600   # ~50 hours of 5m bars

# How far back to look on each incremental fetch
H1_LOOKBACK = pd.Timedelta(hours=3)    # overlap ensures no gap at bar boundaries
M5_LOOKBACK = pd.Timedelta(minutes=15) # same rationale


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Position:
    pair:         str    # "eurusd"
    symbol:       str    # "EURUSD=X"
    direction:    str    # "BUY" | "SELL"
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    atr:          float
    risk_pips:    float
    reward_pips:  float
    rr_ratio:     float
    opened_at:    str    # UTC timestamp string
    basis:        str    # entry basis description
    be_activated:  bool = False
    trade_id:      Optional[str] = None  # Oanda trade ID once the order is filled
    occult_stops:  bool = False          # True → no broker-side SL/TP; daemon closes explicitly
    sl_materialised: bool = False        # occult SL placed as a real broker order
    tp_materialised: bool = False        # occult TP placed as a real broker order
    signal_price:  Optional[float] = None  # indicator's intended entry; entry_price is the fill


@dataclass
class PairState:
    """All mutable per-pair state held in memory for the lifetime of the daemon."""
    cache_h1:        Optional[pd.DataFrame] = None
    cache_5m:        Optional[pd.DataFrame] = None
    position:        Optional[Position]     = None
    cooldown_until:  Optional[datetime]     = None
    last_signal_bar: Optional[str]          = None  # prevents duplicate entry on same bar
    month_pips:      float                  = 0.0   # cumulative closed-trade pips this calendar month


class ControlState:
    """Shared state between the main daemon loop and the control socket server."""
    def __init__(self):
        self.pause_entry:            bool            = False
        self.pause_exit:             bool            = False
        self.pending_be:             bool            = False
        self.pending_close_all:      bool            = False
        self.pending_materialise_sl: bool            = False
        self.pending_materialise_tp: bool            = False
        # Signals the main loop to wake early and process a pending command.
        self.wake_event:             threading.Event = threading.Event()


# ── Data helpers ──────────────────────────────────────────────────────────────

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and flatten MultiIndex columns returned by some yfinance versions."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee the DatetimeIndex is UTC-aware."""
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def _fetch_raw(symbol: str, interval: str, **kwargs) -> pd.DataFrame:
    """Download OHLCV data, normalise columns and index timezone."""
    df = yf.download(symbol, interval=interval, progress=False,
                     auto_adjust=True, **kwargs)
    if df.empty:
        return df
    df = _flatten(df)
    df.dropna(inplace=True)
    df = _ensure_utc(df)
    return df


def _fetch_oanda(pair: str, granularity: str, count: int = 200,
                 start: datetime | None = None) -> pd.DataFrame:
    """Fetch OHLCV from Oanda and return a UTC-indexed DataFrame matching _fetch_raw output."""
    candles = oanda.get_candles(
        pair,
        granularity=_GRANULARITY_MAP[granularity],
        count=count,
        from_time=start,
    )
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df.index = pd.to_datetime(df["time"], utc=True)
    df.drop(columns=["time"], inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def _merge_into_cache(cached: pd.DataFrame, new: pd.DataFrame,
                      max_bars: int) -> pd.DataFrame:
    """Concatenate new bars onto cache, dedup by timestamp, trim to max_bars."""
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined.tail(max_bars)


def refresh_data(pair: str, symbol: str, state: PairState) -> PairState:
    """
    Update the in-memory OHLCV cache for `symbol`.

    First call: compact initial fetch (7d of 1h, 2d of 5m for yfinance;
    H1_MAX_BARS / M5_MAX_BARS for Oanda).
    Subsequent calls: fetch only the most recent bars and merge.
    Data source is controlled by FX_DATA_SOURCE in .env.
    """
    use_oanda = FX_DATA_SOURCE == "oanda"

    if state.cache_h1 is None:
        log.info("Initial fetch for %s via %s …", symbol, FX_DATA_SOURCE)
        if use_oanda:
            state.cache_h1 = _fetch_oanda(pair, "1h", count=H1_MAX_BARS)
            state.cache_5m = _fetch_oanda(pair, "5m", count=M5_MAX_BARS)
        else:
            state.cache_h1 = _fetch_raw(symbol, "1h", period="7d")
            state.cache_5m = _fetch_raw(symbol, "5m", period="2d")
        log.info(
            "%s  cache seeded: %d × 1h bars, %d × 5m bars",
            symbol, len(state.cache_h1), len(state.cache_5m),
        )
        return state

    # Incremental refresh — fetch from slightly before the last cached bar
    h1_start = (state.cache_h1.index[-1] - H1_LOOKBACK).to_pydatetime()
    m5_start = (state.cache_5m.index[-1] - M5_LOOKBACK).to_pydatetime()

    if use_oanda:
        new_h1 = _fetch_oanda(pair, "1h", start=h1_start)
        new_5m = _fetch_oanda(pair, "5m", start=m5_start)
    else:
        new_h1 = _fetch_raw(symbol, "1h", start=h1_start)
        new_5m = _fetch_raw(symbol, "5m", start=m5_start)

    if not new_h1.empty:
        state.cache_h1 = _merge_into_cache(state.cache_h1, new_h1, H1_MAX_BARS)
    if not new_5m.empty:
        state.cache_5m = _merge_into_cache(state.cache_5m, new_5m, M5_MAX_BARS)

    return state


# ── Spread guard ─────────────────────────────────────────────────────────────

def _spread_ok(pair: str) -> tuple[bool, float]:
    """
    Return (ok, spread_pips).  ok is False when the live spread exceeds 2× the
    standard spread for this pair (news events, thin liquidity).
    Returns (True, 0.0) on any API error so transient hiccups don't block trades.
    """
    try:
        price       = oanda.get_price(pair)
        pv          = PAIR_INDICATORS[pair].pip_value(pair)
        spread_pips = (price["ask"] - price["bid"]) / pv
        threshold   = STANDARD_SPREADS[pair] * 2
        ok          = spread_pips <= threshold
        log.debug("%s  spread %.1f pips (threshold %.1f) — %s",
                  pair.upper(), spread_pips, threshold, "OK" if ok else "BLOCKED")
        return ok, spread_pips
    except Exception as exc:
        log.warning("%s  spread check failed (%s) — allowing entry", pair.upper(), exc)
        return True, 0.0


# ── Position management ───────────────────────────────────────────────────────

def check_position_events(pos: Position, bar: pd.Series) -> list[tuple[str, float]]:
    """
    Evaluate the latest 5m bar against the open position.

    Returns an ordered list of (event, price) tuples:
        "be"       — stop moved to breakeven; position remains open
        "close_tp" — take profit hit; position closed
        "close_sl" — stop loss hit;   position closed

    BE is checked first.  If BE and SL are both triggered on the same bar
    (e.g. a volatile spike), BE is reported before the close.
    """
    events = []
    high = float(bar["high"])
    low  = float(bar["low"])

    # Phase 1 — breakeven trigger (80 % of the way to TP)
    if not pos.be_activated:
        pv            = PAIR_INDICATORS[pos.pair].pip_value(pos.pair)
        tp_dist_pips  = abs(pos.take_profit - pos.entry_price) / pv
        trail_frac    = getattr(PAIR_INDICATORS[pos.pair], "TRAIL_ACTIVATE_FRAC", TRAIL_ACTIVATE_FRAC)
        activate_pips = tp_dist_pips * trail_frac
        progress = (
            (high - pos.entry_price) if pos.direction == "BUY"
            else (pos.entry_price - low)
        ) / pv
        if progress >= activate_pips:
            pos.stop_loss    = pos.entry_price
            pos.be_activated = True
            events.append(("be", pos.entry_price))

    # Phase 2 — TP / SL exit
    hit_tp = (
        (pos.direction == "BUY"  and high >= pos.take_profit) or
        (pos.direction == "SELL" and low  <= pos.take_profit)
    )
    hit_sl = (
        (pos.direction == "BUY"  and low  <= pos.stop_loss) or
        (pos.direction == "SELL" and high >= pos.stop_loss)
    )

    if hit_tp:
        events.append(("close_tp", pos.take_profit))
    elif hit_sl:
        events.append(("close_sl", pos.stop_loss))

    return events


# ── Email body builders ───────────────────────────────────────────────────────

def _fmt(pos: Position) -> tuple[str, str]:
    return ".5f", "pips"


def _email_open(pos: Position) -> tuple[str, str]:
    pfmt, unit = _fmt(pos)
    arrow   = "UP" if pos.direction == "BUY" else "DOWN"
    subject = (
        f"[FX] [{pos.pair.upper()}] {arrow} {pos.direction} — "
        f"Fill {pos.entry_price:{pfmt}}"
    )
    stops_note = "occult (daemon-managed)" if pos.occult_stops else "broker order"
    lines = [
        f"Trade Opened : {pos.pair.upper()} {pos.direction}",
        f"Timestamp    : {pos.opened_at}",
        "",
    ]
    if pos.signal_price is not None and pos.signal_price != pos.entry_price:
        lines.append(f"Signal Entry : {pos.signal_price:{pfmt}}")
    lines += [
        f"Fill         : {pos.entry_price:{pfmt}}",
        f"Stop Loss    : {pos.stop_loss:{pfmt}}  ({pos.risk_pips:.1f} {unit})  [{stops_note}]",
        f"Take Profit  : {pos.take_profit:{pfmt}}  ({pos.reward_pips:.1f} {unit})  [{stops_note}]",
        f"R:R          : 1 : {pos.rr_ratio:.2f}",
        f"ATR(14) 1h   : {pos.atr:{pfmt}}",
        "",
        f"Basis: {pos.basis}",
    ]
    return subject, "\n".join(lines)


def _email_be(pos: Position) -> tuple[str, str]:
    pfmt, unit = _fmt(pos)
    subject = f"[FX] [{pos.pair.upper()}] {pos.direction} — Stop Moved to Breakeven"
    body = "\n".join([
        f"Breakeven triggered on {pos.pair.upper()} {pos.direction}",
        "",
        f"Entry        : {pos.entry_price:{pfmt}}",
        f"New SL       : {pos.entry_price:{pfmt}}  (breakeven — risk now zero)",
        f"TP still live: {pos.take_profit:{pfmt}}  ({pos.reward_pips:.1f} {unit} remaining)",
    ])
    return subject, body


def _email_close(pos: Position, event: str, exit_price: float) -> tuple[str, str]:
    pfmt, unit = _fmt(pos)
    pnl_pips = (
        (exit_price - pos.entry_price) if pos.direction == "BUY"
        else (pos.entry_price - exit_price)
    ) / PAIR_INDICATORS[pos.pair].pip_value(pos.pair)
    result   = "WIN" if pnl_pips > 0 else "LOSS"
    if event == "close_tp":
        reason = "Take Profit"
    elif event == "close_weekend":
        reason = "Weekend Close (pre-market)"
    elif event == "close_manual":
        reason = "Manual Close (console command)"
    else:
        reason = "Stop Loss"
    sign     = "+" if pnl_pips >= 0 else ""
    subject  = (
        f"{result} — [FX] [{pos.pair.upper()}] {pos.direction} Closed "
        f"{sign}{pnl_pips:.1f} {unit}"
    )
    body = "\n".join([
        f"Trade Closed : {pos.pair.upper()} {pos.direction}",
        f"Exit Reason  : {reason} Hit",
        "",
        f"Entry        : {pos.entry_price:{pfmt}}",
        f"Exit         : {exit_price:{pfmt}}",
        f"P&L          : {sign}{pnl_pips:.1f} {unit}",
        f"Result       : {result}",
    ])
    return subject, body


# ── Startup / summary emails ──────────────────────────────────────────────────

def _email_startup(
    pairs: list[tuple[str, str]],
    restored: list["Position"],
    live: bool,
    occult_stops: bool = False,
) -> tuple[str, str]:
    subject = "[FX Trader] Daemon started"
    if live:
        mode_str = "LIVE (orders enabled)"
        if occult_stops:
            mode_str += " — OCCULT STOPS (no broker-side SL/TP; daemon closes explicitly)"
    else:
        mode_str = "PAPER (signal alerts only — no orders placed)"
    lines = [
        "FX Trader daemon has started successfully.",
        "",
        f"Monitoring {len(pairs)} pair(s): {', '.join(p.upper() for p, _ in pairs)}",
        f"Started at : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Mode       : {mode_str}",
        "",
        "You will receive alerts for OPEN, BE, and CLOSE events.",
    ]
    if restored:
        lines += ["", f"Restored {len(restored)} open position(s) from trade log:"]
        for pos in restored:
            lines += [
                "",
                f"  {pos.pair.upper()} {pos.direction}",
                f"    Opened      : {pos.opened_at}",
                f"    Entry       : {pos.entry_price:.5f}",
                f"    Stop Loss   : {pos.stop_loss:.5f}",
                f"    Take Profit : {pos.take_profit:.5f}",
                f"    Breakeven   : {'activated' if pos.be_activated else 'pending'}",
            ]
    else:
        lines += ["", "No open positions restored from trade log."]
    return subject, "\n".join(lines)


def _email_daily_summary(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    month_pips: float,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    subject = f"[FX Trader] Daily Summary — {now.strftime('%Y-%m-%d')}"

    sign = "+" if month_pips >= 0 else ""

    try:
        acct = oanda.get_account_summary()
        balance      = float(acct["balance"])
        unrealized   = float(acct["unrealizedPL"])
        nav          = float(acct["NAV"])
        acct_line    = f"Account Balance   : ${balance:,.2f}  (NAV ${nav:,.2f})"
        unreal_sign  = "+" if unrealized >= 0 else ""
        open_pnl_line = f"Open Trade P&L    : {unreal_sign}${unrealized:,.2f}"
    except Exception as exc:
        log.warning("Could not fetch account summary for daily email: %s", exc)
        acct_line     = "Account Balance   : unavailable"
        open_pnl_line = "Open Trade P&L    : unavailable"

    lines = [
        f"Daily Status Summary — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Monitoring : {', '.join(p.upper() for p, _ in pairs)}",
        acct_line,
        open_pnl_line,
        f"Month-to-date pips : {sign}{month_pips:.1f}  (resets each calendar month)",
        "",
    ]

    open_positions = [
        states[sym].position for _, sym in pairs if states[sym].position is not None
    ]

    if open_positions:
        lines.append(f"Open Positions ({len(open_positions)}):")
        for pos in open_positions:
            lines.extend([
                "",
                f"  {pos.pair.upper()} {pos.direction}",
                f"    Opened      : {pos.opened_at}",
                f"    Entry       : {pos.entry_price:.5f}",
                f"    Stop Loss   : {pos.stop_loss:.5f}",
                f"    Take Profit : {pos.take_profit:.5f}",
                f"    R:R         : 1 : {pos.rr_ratio:.2f}",
                f"    Breakeven   : {'activated' if pos.be_activated else 'pending'}",
            ])
    else:
        lines.append("Open Positions : None")

    # Pairs in cooldown
    in_cooldown = [
        f"{pair.upper()} (until {states[sym].cooldown_until.strftime('%H:%M UTC')})"
        for pair, sym in pairs
        if states[sym].cooldown_until and datetime.now(timezone.utc) < states[sym].cooldown_until
    ]
    if in_cooldown:
        lines.extend(["", "In Cooldown : " + ", ".join(in_cooldown)])

    return subject, "\n".join(lines)


# ── Position management helpers ───────────────────────────────────────────────

def _close_all_positions(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    live: bool,
    dry_run: bool,
    reason: str = "close_manual",
) -> int:
    """Close every open position at market. Returns the number of positions closed."""
    count = 0
    for pair, symbol in pairs:
        pos = states[symbol].position
        if pos is None:
            continue
        try:
            price_data = oanda.get_price(pair)
            exit_price = (price_data["bid"] + price_data["ask"]) / 2
        except Exception as exc:
            log.warning("%s  could not fetch price for close (%s): %s", pair.upper(), reason, exc)
            exit_price = pos.entry_price  # fallback — P&L will show 0

        pv  = PAIR_INDICATORS[pair].pip_value(pair)
        pnl = (
            (exit_price - pos.entry_price) if pos.direction == "BUY"
            else (pos.entry_price - exit_price)
        ) / pv

        log.info(
            "%s  %s — %s @ %.5f  P&L %.1f pips",
            pair.upper(), reason, pos.direction, exit_price, pnl,
        )

        if live and pos.trade_id:
            try:
                oanda.close_trade(pos.trade_id)
                log.info("%s  Oanda trade %s closed (%s)", pair.upper(), pos.trade_id, reason)
            except Exception as exc:
                log.error("%s  Oanda close failed (%s): %s", pair.upper(), reason, exc)

        tradelog.log_close(pos, reason, exit_price, pnl)
        subj, body = _email_close(pos, reason, exit_price)
        if dry_run:
            log.info("[DRY-RUN] %s", subj)
        else:
            send_email(subj, body)

        states[symbol].month_pips += pnl
        states[symbol].position    = None
        count += 1

    return count


def _set_all_breakeven(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    live: bool,
    dry_run: bool,
) -> int:
    """Move every open SL to entry price. Returns the number of positions updated."""
    count = 0
    for pair, symbol in pairs:
        pos = states[symbol].position
        if pos is None or pos.be_activated:
            continue
        pos.stop_loss    = pos.entry_price
        pos.be_activated = True
        log.info("%s  manual BE — SL moved to %.5f", pair.upper(), pos.entry_price)
        tradelog.log_be(pos)
        if live and pos.trade_id and (not pos.occult_stops or pos.sl_materialised):
            try:
                oanda.modify_trade_sl(pos.trade_id, pos.entry_price, pair)
                log.info("%s  Oanda SL moved to breakeven — trade_id=%s", pair.upper(), pos.trade_id)
            except Exception as exc:
                log.warning("%s  Oanda BE move failed: %s", pair.upper(), exc)
        subj, body = _email_be(pos)
        if dry_run:
            log.info("[DRY-RUN] %s", subj)
        else:
            send_email(subj, body)
        count += 1

    return count


def _materialise_all_sl(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    live: bool,
) -> int:
    """Place real broker SL orders for all open occult-stops positions. Returns count placed."""
    count = 0
    for pair, symbol in pairs:
        pos = states[symbol].position
        if pos is None or not pos.occult_stops or pos.sl_materialised:
            continue
        if live and pos.trade_id:
            try:
                oanda.modify_trade_sl(pos.trade_id, pos.stop_loss, pair)
                pos.sl_materialised = True
                log.info("%s  SL materialised at %.5f — trade_id=%s",
                         pair.upper(), pos.stop_loss, pos.trade_id)
                count += 1
            except Exception as exc:
                log.error("%s  SL materialise failed: %s", pair.upper(), exc)
        else:
            log.info("%s  SL materialise skipped (not live or no trade_id)", pair.upper())
    return count


def _materialise_all_tp(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    live: bool,
) -> int:
    """Place real broker TP orders for all open occult-stops positions. Returns count placed."""
    count = 0
    for pair, symbol in pairs:
        pos = states[symbol].position
        if pos is None or not pos.occult_stops or pos.tp_materialised:
            continue
        if live and pos.trade_id:
            try:
                oanda.modify_trade_tp(pos.trade_id, pos.take_profit, pair)
                pos.tp_materialised = True
                log.info("%s  TP materialised at %.5f — trade_id=%s",
                         pair.upper(), pos.take_profit, pos.trade_id)
                count += 1
            except Exception as exc:
                log.error("%s  TP materialise failed: %s", pair.upper(), exc)
        else:
            log.info("%s  TP materialise skipped (not live or no trade_id)", pair.upper())
    return count


# ── Weekend position management ───────────────────────────────────────────────

def _close_positions_for_weekend(
    pairs: list[tuple[str, str]],
    states: dict[str, "PairState"],
    live: bool,
    dry_run: bool,
) -> None:
    """Close every open position ahead of the weekend spread blow-out."""
    _close_all_positions(pairs, states, live, dry_run, reason="close_weekend")


# ── Control server ────────────────────────────────────────────────────────────

def _ctrl_status(ctrl: ControlState, states: dict, pairs: list) -> str:
    """Build a human-readable status string for the 'status' command."""
    now   = datetime.now(timezone.utc)
    lines = ["=== FX Trader Daemon Status ==="]
    entry_str = "PAUSED" if ctrl.pause_entry else "Active"
    exit_str  = "PAUSED" if ctrl.pause_exit  else "Active"
    lines.append(f"Entries : {entry_str}  |  Exits : {exit_str}")
    lines.append("")
    open_count = 0
    for pair, symbol in pairs:
        st = states[symbol]
        if st.position:
            open_count += 1
            pos = st.position
            be  = "active" if pos.be_activated else "pending"
            if pos.occult_stops:
                sl_side = "broker" if pos.sl_materialised else "daemon"
                tp_side = "broker" if pos.tp_materialised else "daemon"
                occult_tag = f"  occult[SL={sl_side},TP={tp_side}]"
            else:
                occult_tag = ""
            lines.append(
                f"  {pair.upper():<6}  {pos.direction}  "
                f"entry={pos.entry_price:.5f}  SL={pos.stop_loss:.5f}  "
                f"TP={pos.take_profit:.5f}  BE={be}{occult_tag}"
            )
        elif st.cooldown_until and now < st.cooldown_until:
            lines.append(
                f"  {pair.upper():<6}  [cooldown until "
                f"{st.cooldown_until.strftime('%H:%M UTC')}]"
            )
        else:
            lines.append(f"  {pair.upper():<6}  [no position]")
    lines.append("")
    lines.append(f"Open positions: {open_count}")
    return "\n".join(lines)


def _handle_ctrl_cmd(
    cmd: str,
    ctrl: ControlState,
    states: dict,
    pairs: list,
) -> str:
    """Dispatch a control command and return a response string."""
    cmd = cmd.strip().lower()

    if cmd == "pause":
        ctrl.pause_entry = True
        ctrl.pause_exit  = True
        return "Daemon paused — entries and exits both suspended."

    if cmd == "resume":
        ctrl.pause_entry = False
        ctrl.pause_exit  = False
        return "Daemon resumed — entries and exits both re-enabled."

    if cmd == "pause_entry":
        ctrl.pause_entry = True
        return "Entry paused — no new positions will be opened."

    if cmd == "resume_entry":
        ctrl.pause_entry = False
        return "Entry resumed — new positions re-enabled."

    if cmd == "pause_exit":
        ctrl.pause_exit = True
        return "Exit paused — daemon will not close positions automatically."

    if cmd == "resume_exit":
        ctrl.pause_exit = False
        return "Exit resumed — automatic position closing re-enabled."

    if cmd == "materialise_sl":
        ctrl.pending_materialise_sl = True
        ctrl.wake_event.set()
        return "SL materialise queued — will place broker SL orders for all occult positions."

    if cmd == "materialise_tp":
        ctrl.pending_materialise_tp = True
        ctrl.wake_event.set()
        return "TP materialise queued — will place broker TP orders for all occult positions."

    if cmd in ("be", "breakeven"):
        ctrl.pending_be = True
        ctrl.wake_event.set()
        return "Breakeven queued — daemon will move all open SLs to entry."

    if cmd in ("close", "close_all"):
        ctrl.pending_close_all = True
        ctrl.wake_event.set()
        return "Close-all queued — daemon will close all open positions at market."

    if cmd == "status":
        return _ctrl_status(ctrl, states, pairs)

    if cmd in ("help", "?", ""):
        return (
            "Commands:\n"
            "  status          Show daemon status and open positions\n"
            "  pause           Pause both entries and exits\n"
            "  resume          Resume both entries and exits\n"
            "  pause_entry     Pause new trade entries only\n"
            "  resume_entry    Resume new trade entries\n"
            "  pause_exit      Pause automatic position exits only\n"
            "  resume_exit     Resume automatic position exits\n"
            "  materialise_sl  Place real broker SL orders for occult positions\n"
            "  materialise_tp  Place real broker TP orders for occult positions\n"
            "  be              Move all open SLs to breakeven (entry price)\n"
            "  close           Close all open positions at market\n"
            "  help            Show this help"
        )

    return f"Unknown command: '{cmd}' — type 'help' for the command list."


def _start_control_server(
    ctrl: ControlState,
    states: dict,
    pairs: list,
) -> None:
    """
    Start a background thread that listens on TCP for control commands.
    Binds to 0.0.0.0:CONTROL_PORT so Docker port-mapping works.
    Each connection receives exactly one command and gets one response, then closes.
    """
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", CONTROL_PORT))
    srv.listen(8)
    srv.settimeout(1.0)  # allows the thread to exit cleanly when the process dies

    log.info("Control server listening on port %d  (telnet localhost %d)", CONTROL_PORT, CONTROL_PORT)

    def _handle_connection(conn: "_socket.socket") -> None:
        conn.sendall(b"FX Trader  |  help=commands  quit=disconnect\r\n\r\n> ")
        f = conn.makefile("rb")
        while True:
            raw = f.readline(256)
            if not raw:
                break
            # Strip telnet control bytes (IAC sequences etc.) — keep printable ASCII only
            cmd = bytes(b for b in raw if 32 <= b < 127).decode().strip()
            if not cmd:
                conn.sendall(b"> ")
                continue
            if cmd.lower() in ("quit", "exit", "q"):
                conn.sendall(b"Bye.\r\n")
                break
            resp = _handle_ctrl_cmd(cmd, ctrl, states, pairs)
            conn.sendall(resp.encode() + b"\r\n\r\n> ")

    def _server() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except _socket.timeout:
                continue
            except OSError:
                break
            try:
                _handle_connection(conn)
            except Exception as exc:
                log.debug("Control connection error: %s", exc)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    t = threading.Thread(target=_server, daemon=True, name="fxtrader-ctrl")
    t.start()


# ── Oanda position sizing ─────────────────────────────────────────────────────

def _calc_units(pair: str, risk_pips: float) -> int:
    """
    Return the number of units to trade so that `risk_pips` of adverse movement
    equals exactly OANDA_RISK_PCT percent of the current account balance.

    For JPY pairs the pip is in JPY, so we convert to USD using the live rate.
    """
    try:
        balance = float(oanda.get_account_summary()["balance"])
    except Exception as exc:
        log.warning("Could not fetch account balance for sizing (%s) — using 10 000 fallback", exc)
        balance = 10_000.0

    risk_usd = balance * OANDA_RISK_PCT / 100
    pip_size = PAIR_INDICATORS[pair].pip_value(pair)

    if pair == "usdjpy":
        try:
            price   = oanda.get_price(pair)
            rate    = (price["bid"] + price["ask"]) / 2
        except Exception:
            rate = 150.0  # conservative fallback
        pip_usd = pip_size / rate
    else:
        pip_usd = pip_size  # quote currency is USD; pip_size already in USD per unit

    return max(int(risk_usd / (risk_pips * pip_usd)), 1)


# ── Core tick ─────────────────────────────────────────────────────────────────

def tick(pair: str, symbol: str, state: PairState, dry_run: bool, live: bool,
         occult_stops: bool = False, pause_entry: bool = False,
         pause_exit: bool = False) -> PairState:
    """
    One polling cycle for a single pair:
      1. Refresh cached data (incremental fetch).
      2. If a position is open, check the latest bar for BE / SL / TP events.
      3. Otherwise look for a new entry signal.
      4. Send emails (or log them in dry-run mode) for any events found.
    """
    now = datetime.now(timezone.utc)

    try:
        state = refresh_data(pair, symbol, state)
    except Exception as exc:
        log.warning("%s  data refresh failed: %s", pair.upper(), exc)
        return state

    if state.cache_h1 is None or len(state.cache_h1) < 30:
        log.debug("%s  insufficient 1h bars — skipping", pair.upper())
        return state
    if state.cache_5m is None or len(state.cache_5m) < 30:
        log.debug("%s  insufficient 5m bars — skipping", pair.upper())
        return state

    # Compute indicators on copies to avoid polluting the cache
    ind   = PAIR_INDICATORS[pair]
    df_h1 = ind.compute_h1_indicators(state.cache_h1.copy())
    df_5m = ind.compute_m5_indicators(state.cache_5m.copy())

    # Build 4h frame for the EMA22 gate (Measure 4) by resampling the 1h cache
    df_4h = state.cache_h1.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)
    df_4h["ema_4h"] = EMAIndicator(close=df_4h["close"], window=ind.H4_EMA_PERIOD).ema_indicator()

    # ── Manage open position ──────────────────────────────────────────────────
    if state.position is not None:
        pos    = state.position
        latest = df_5m.iloc[-1]   # most recent (possibly still-forming) bar
        events = check_position_events(pos, latest)
        closed = False

        for event, price in events:
            if event == "be":
                log.info("%s  BE triggered — SL moved to %.5f", pair.upper(), pos.entry_price)
                tradelog.log_be(pos)
                if live and pos.trade_id and (not pos.occult_stops or pos.sl_materialised):
                    try:
                        oanda.modify_trade_sl(pos.trade_id, pos.entry_price, pair)
                        log.info("%s  Oanda SL moved to breakeven — trade_id=%s",
                                 pair.upper(), pos.trade_id)
                    except Exception as exc:
                        log.warning("%s  Oanda BE move failed: %s", pair.upper(), exc)
                subj, body = _email_be(pos)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

            elif event in ("close_tp", "close_sl"):
                if pause_exit:
                    log.info("%s  %s hit but exit is paused — holding position",
                             pair.upper(), event)
                    continue

                # Occult mode: close the trade explicitly on Oanda and use the
                # actual fill price rather than the theoretical stop/TP level.
                # Skip if the relevant stop has been materialised (broker closes automatically).
                if live and pos.occult_stops and pos.trade_id:
                    already_materialised = (
                        (event == "close_sl" and pos.sl_materialised) or
                        (event == "close_tp" and pos.tp_materialised)
                    )
                    if not already_materialised:
                        try:
                            result = oanda.close_trade(pos.trade_id)
                            fill = result.get("orderFillTransaction", {})
                            if fill.get("price"):
                                price = float(fill["price"])
                            log.info(
                                "%s  Oanda occult close — trade_id=%s  fill=%.5f",
                                pair.upper(), pos.trade_id, price,
                            )
                        except Exception as exc:
                            log.error("%s  Oanda occult close failed: %s", pair.upper(), exc)

                pnl = (
                    (price - pos.entry_price) if pos.direction == "BUY"
                    else (pos.entry_price - price)
                ) / PAIR_INDICATORS[pair].pip_value(pair)
                log.info(
                    "%s  CLOSE %s — %s @ %.5f  P&L %.1f pips",
                    pair.upper(), pos.direction, event, price, pnl,
                )
                tradelog.log_close(pos, event, price, pnl)
                subj, body = _email_close(pos, event, price)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

                state.month_pips += pnl

                if event == "close_sl":
                    state.cooldown_until = now + timedelta(minutes=COOLDOWN_MINS)
                    log.info("%s  cooldown until %s",
                             pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
                state.position = None
                closed = True
                break   # no further processing this tick

        if not closed:
            log.debug(
                "%s  position open: entry=%.5f  SL=%.5f  BE=%s",
                pair.upper(), pos.entry_price, pos.stop_loss,
                "active" if pos.be_activated else "pending",
            )
        return state

    # ── Look for a new entry ──────────────────────────────────────────────────
    if pause_entry:
        log.debug("%s  entry paused — skipping entry check", pair.upper())
        return state

    if state.cooldown_until and now < state.cooldown_until:
        log.debug("%s  in cooldown until %s",
                  pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
        return state

    h1_bias = ind.assess_h1_bias(df_h1, df_4h=df_4h)
    entry   = ind.find_m5_entry(df_5m, h1_bias["direction"])

    if h1_bias["direction"] == "FLAT":
        log.debug("%s  1h bias FLAT", pair.upper())
        return state

    if entry is None:
        log.debug("%s  %s bias, no 5m entry trigger", pair.upper(), h1_bias["direction"])
        return state

    # Prevent re-firing on the same 5m bar across consecutive polls
    if entry["bar_time"] == state.last_signal_bar:
        log.debug("%s  duplicate signal bar (%s) — skipped", pair.upper(), entry["bar_time"])
        return state


    signal = ind.build_signal(h1_bias, entry, symbol)
    if signal.direction == "FLAT":
        return state

    # ── Spread guard ──────────────────────────────────────────────────────────
    spread_ok, spread_pips = _spread_ok(pair)
    if not spread_ok:
        log.info(
            "%s  %s signal skipped — spread %.1f pips exceeds %.1f pip threshold",
            pair.upper(), signal.direction, spread_pips, STANDARD_SPREADS[pair] * 2,
        )
        return state

    # ── Place order on Oanda ──────────────────────────────────────────────────
    trade_id    = None
    signal_entry = signal.entry_price
    entry_price  = signal.entry_price
    stop_loss    = signal.stop_loss
    risk_pips    = signal.risk_pips
    reward_pips = signal.reward_pips
    rr_ratio    = signal.rr_ratio
    if live:
        units = _calc_units(pair, signal.risk_pips)
        try:
            result   = oanda.place_market_order(
                pair         = pair,
                direction    = signal.direction,
                units        = units,
                stop_loss    = signal.stop_loss,
                take_profit  = signal.take_profit,
                occult_stops = occult_stops,
            )
            trade_id = result["orderFillTransaction"]["tradeOpened"]["tradeID"]
            # Use actual fill price so logged risk_pips reflects reality.
            fill_str = result["orderFillTransaction"].get("price")
            if fill_str:
                pv          = PAIR_INDICATORS[pair].pip_value(pair)
                entry_price = round(float(fill_str), 5)
                # Re-anchor SL to fill price if slippage pushes risk past the max pip cap.
                sl_max_pips = getattr(ind, "HA_SL_MAX_PIPS", None)
                if sl_max_pips is not None:
                    raw_sl_pips = abs(entry_price - stop_loss) / pv
                    if raw_sl_pips > sl_max_pips:
                        sl_dist   = sl_max_pips * pv
                        stop_loss = round(
                            (entry_price - sl_dist) if signal.direction == "BUY"
                            else (entry_price + sl_dist),
                            5,
                        )
                        if not occult_stops:
                            try:
                                oanda.modify_trade_sl(trade_id, stop_loss, pair)
                                log.info(
                                    "%s  SL adjusted %.5f → %.5f after slippage "
                                    "(%.1f → %.1f pips from fill)",
                                    pair.upper(), signal.stop_loss, stop_loss,
                                    raw_sl_pips, sl_max_pips,
                                )
                            except Exception as sl_exc:
                                log.warning(
                                    "%s  SL adjustment after slippage failed: %s",
                                    pair.upper(), sl_exc,
                                )
                risk_pips   = round(abs(entry_price - stop_loss) / pv, 1)
                reward_pips = round(abs(signal.take_profit - entry_price) / pv, 1)
                rr_ratio    = round(reward_pips / risk_pips, 2) if risk_pips > 0 else 0.0
            log.info(
                "%s  Oanda order filled — trade_id=%s  units=%d  fill=%.5f%s",
                pair.upper(), trade_id, units, entry_price,
                "  [occult stops]" if occult_stops else "",
            )
        except Exception as exc:
            log.error(
                "%s  Oanda order failed — signal discarded: %s",
                pair.upper(), exc,
            )
            return state  # don't track a position we couldn't open

    pos = Position(
        pair          = pair,
        symbol        = symbol,
        direction     = signal.direction,
        entry_price   = entry_price,
        stop_loss     = stop_loss,
        take_profit   = signal.take_profit,
        atr           = signal.atr,
        risk_pips     = risk_pips,
        reward_pips   = reward_pips,
        rr_ratio      = rr_ratio,
        opened_at     = signal.timestamp,
        basis         = signal.entry_basis,
        trade_id      = trade_id,
        occult_stops  = occult_stops,
        signal_price  = signal_entry,
    )
    state.position        = pos
    state.last_signal_bar = entry["bar_time"]

    log.info(
        "%s  OPEN %s @ %.5f  SL=%.5f  TP=%.5f  (%.1f/%.1f pips  R:R 1:%.2f)",
        pair.upper(), pos.direction, pos.entry_price,
        pos.stop_loss, pos.take_profit,
        pos.risk_pips, pos.reward_pips, pos.rr_ratio,
    )
    tradelog.log_open(pos)

    subj, body = _email_open(pos)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    return state


# ── Daemon loop ───────────────────────────────────────────────────────────────

def daemon_loop(pairs: list[tuple[str, str]], interval: int, dry_run: bool, live: bool,
                occult_stops: bool = False) -> None:
    """Poll all watched pairs in sequence, sleep, repeat."""
    states: dict[str, PairState] = {sym: PairState() for _, sym in pairs}
    ctrl   = ControlState()

    # ── Restore open positions from trade log ─────────────────────────────────
    saved = tradelog.load_state()
    restored_positions: list[Position] = []

    for symbol, data in saved.items():
        if symbol not in states:
            log.warning("Trade log has symbol %s not in current pair list — skipped", symbol)
            continue

        states[symbol].month_pips = data["month_pips"]

        pos_data = data.get("position")
        if pos_data:
            pos = Position(**pos_data)
            pos.occult_stops = occult_stops  # apply current daemon config
            states[symbol].position = pos
            restored_positions.append(pos)

    if restored_positions:
        log.info(
            "Restored %d open position(s) from %s",
            len(restored_positions), tradelog.TRADE_LOG_FILE,
        )
    else:
        log.info("No open positions in trade log")

    _start_control_server(ctrl, states, pairs)

    log.info(
        "Daemon started — %d pair(s): %s — poll interval %ds%s  [%s]",
        len(pairs),
        ", ".join(p.upper() for p, _ in pairs),
        interval,
        "  [DRY-RUN]" if dry_run else "",
        "LIVE" if live else "PAPER",
    )

    # Send a startup email (includes any restored positions)
    subj, body = _email_startup(pairs, restored_positions, live, occult_stops)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    # Track twice-daily summary sends as (date, slot) where slot is "AM" or "PM".
    # AM fires on the first poll at or after 08:00 UTC; PM at or after 20:00 UTC.
    last_summary_slot: Optional[tuple] = None
    current_month: int = datetime.now(timezone.utc).month
    weekend_close_done: Optional[int] = None  # isoweekday of the Friday we last closed

    while True:
        # Sleep until next scheduled poll or until a control command wakes us early.
        ctrl.wake_event.wait(timeout=interval)
        ctrl.wake_event.clear()

        now     = datetime.now(timezone.utc)
        today   = now.date()
        weekday = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun

        # ── Process immediate control commands ────────────────────────────────
        if ctrl.pending_close_all:
            ctrl.pending_close_all = False
            n = _close_all_positions(pairs, states, live, dry_run, reason="close_manual")
            log.info("Manual close-all: %d position(s) closed", n)

        if ctrl.pending_be:
            ctrl.pending_be = False
            n = _set_all_breakeven(pairs, states, live, dry_run)
            log.info("Manual breakeven: %d position(s) updated", n)

        if ctrl.pending_materialise_sl:
            ctrl.pending_materialise_sl = False
            n = _materialise_all_sl(pairs, states, live)
            log.info("SL materialise: %d position(s) updated", n)

        if ctrl.pending_materialise_tp:
            ctrl.pending_materialise_tp = False
            n = _materialise_all_tp(pairs, states, live)
            log.info("TP materialise: %d position(s) updated", n)

        # ── Weekend: skip pair ticks, market is closed ────────────────────────
        if weekday in (5, 6):
            log.debug("Weekend — skipping pair ticks")
        else:
            # ── Friday pre-close: flatten all positions before spread blows out ─
            if weekday == 4 and now.hour >= WEEKEND_CLOSE_HOUR:
                if weekend_close_done != today.isocalendar()[1]:  # ISO week number
                    weekend_close_done = today.isocalendar()[1]
                    any_open = any(states[sym].position is not None for _, sym in pairs)
                    if any_open:
                        log.info("Friday %02d:00 UTC — closing all positions for weekend",
                                 WEEKEND_CLOSE_HOUR)
                        _close_positions_for_weekend(pairs, states, live, dry_run)
                    else:
                        log.info("Friday %02d:00 UTC — no open positions to close",
                                 WEEKEND_CLOSE_HOUR)

            for pair, symbol in pairs:
                try:
                    states[symbol] = tick(pair, symbol, states[symbol], dry_run, live,
                                          occult_stops,
                                          pause_entry=ctrl.pause_entry,
                                          pause_exit=ctrl.pause_exit)
                except Exception as exc:
                    log.exception("%s  unexpected error in tick: %s", pair.upper(), exc)

        # Reset monthly pip totals on calendar month rollover
        if now.month != current_month:
            current_month = now.month
            for state in states.values():
                state.month_pips = 0.0
            log.info("New calendar month — monthly pip totals reset")

        # Twice-daily summary — AM slot (≥ 08:00 UTC) and PM slot (≥ 20:00 UTC)
        if now.hour >= 20:
            slot = (today, "PM")
        elif now.hour >= 8:
            slot = (today, "AM")
        else:
            slot = None

        if slot and last_summary_slot != slot:
            last_summary_slot = slot
            total_month_pips = sum(s.month_pips for s in states.values())
            log.info("Sending %s summary email", slot[1])
            subj, body = _email_daily_summary(pairs, states, total_month_pips)
            if dry_run:
                log.info("[DRY-RUN] %s", subj)
            else:
                send_email(subj, body)


# ── Entry point ───────────────────────────────────────────────────────────────

def _handle_signal(sig, _frame) -> None:
    log.info("Received signal %d — shutting down", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    parser = argparse.ArgumentParser(
        description="FX Scalper Daemon — email alerts on trade OPEN / BE / CLOSE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pair",
        choices=list(PAIRS.keys()),
        help="Single pair to monitor (default: all pairs)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Poll interval in seconds (default: 300 = 5 min)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=os.getenv("FX_LIVE", "false").lower() == "true",
        help="Enable live order execution on Oanda (default: FX_LIVE env var, else paper mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("FX_DRY_RUN", "false").lower() == "true",
        help="Log events but do not send emails or place orders (default: FX_DRY_RUN env var)",
    )
    parser.add_argument(
        "--occult-stops",
        action="store_true",
        default=FX_OCCULT_STOPS,
        help="Do not send SL/TP to broker; daemon closes the trade when levels are hit "
             "(default: FX_OCCULT_STOPS env var)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        metavar="LEVEL",
        help="Console log level (default: INFO or LOG_LEVEL env var). "
             "The log file always captures DEBUG and above.",
    )
    args = parser.parse_args()

    logsetup.configure("fxtrader", level=args.log_level)

    pairs_to_watch = (
        [(args.pair, PAIRS[args.pair])]
        if args.pair
        else list(PAIRS.items())
    )

    daemon_loop(pairs_to_watch, args.interval, args.dry_run, args.live,
                args.occult_stops)
