"""
FX Scalper Daemon
=================
Monitors currency pairs continuously, caches market data incrementally,
and sends email alerts on three events:

  OPEN   — a new scalp signal fires (entry, SL, TP details)
  BE     — stop-loss moved to breakeven (position still live)
  CLOSE  — trade closed at TP or SL (with P&L in pips)

Data efficiency
---------------
Initial fetch uses compact windows (7 d of 1h, 2 d of 5m) rather than the
60 d / 5 d used by the indicator CLI.  Every subsequent poll fetches only the
most recent bars from Yahoo Finance and merges them with the in-memory cache,
deduplicating by timestamp.  Old bars beyond H1_MAX_BARS / M5_MAX_BARS are
trimmed to cap memory use.

Configuration
-------------
Copy .env.example to .env and fill in your SMTP credentials.

Usage
-----
    python daemon.py                    # monitor all pairs, poll every 5 min
    python daemon.py --pair eurusd      # single pair
    python daemon.py --interval 60      # poll every 60 s (useful for testing)
    python daemon.py --dry-run          # log events, do not send emails

Running as a background process (macOS / Linux)
------------------------------------------------
    nohup python daemon.py >> fxtrader.log 2>&1 &
    echo $! > fxtrader.pid              # save PID to stop later
    kill $(cat fxtrader.pid)            # stop the daemon
"""

import os
import sys
import signal
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from indicator import (
    PAIRS,
    ATR_SL_MULT, ATR_TP_MULT,
    compute_h1_indicators, compute_m5_indicators,
    assess_h1_bias, find_m5_entry, build_signal,
)
from mailer import send_email

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fxtrader.daemon")

# ── Constants ─────────────────────────────────────────────────────────────────
PIP_VALUE           = 0.0001
TRAIL_ACTIVATE_FRAC = 0.80   # mirrors backtest.py
COOLDOWN_MINS       = 30     # post-loss lockout

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
    be_activated: bool = False


@dataclass
class PairState:
    """All mutable per-pair state held in memory for the lifetime of the daemon."""
    cache_h1:        Optional[pd.DataFrame] = None
    cache_5m:        Optional[pd.DataFrame] = None
    position:        Optional[Position]     = None
    cooldown_until:  Optional[datetime]     = None
    last_signal_bar: Optional[str]          = None  # prevents duplicate entry on same bar


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


def _merge_into_cache(cached: pd.DataFrame, new: pd.DataFrame,
                      max_bars: int) -> pd.DataFrame:
    """Concatenate new bars onto cache, dedup by timestamp, trim to max_bars."""
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined.tail(max_bars)


def refresh_data(symbol: str, state: PairState) -> PairState:
    """
    Update the in-memory OHLCV cache for `symbol`.

    First call: compact initial fetch (7d of 1h, 2d of 5m).
    Subsequent calls: fetch only the most recent bars starting just before
    the last cached bar and merge — avoids re-downloading the full history.
    """
    if state.cache_h1 is None:
        log.info("Initial fetch for %s …", symbol)
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

    new_h1 = _fetch_raw(symbol, "1h", start=h1_start)
    new_5m = _fetch_raw(symbol, "5m", start=m5_start)

    if not new_h1.empty:
        state.cache_h1 = _merge_into_cache(state.cache_h1, new_h1, H1_MAX_BARS)
    if not new_5m.empty:
        state.cache_5m = _merge_into_cache(state.cache_5m, new_5m, M5_MAX_BARS)

    return state


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
        tp_dist_pips  = abs(pos.take_profit - pos.entry_price) / PIP_VALUE
        activate_pips = tp_dist_pips * TRAIL_ACTIVATE_FRAC
        progress = (
            (high - pos.entry_price) if pos.direction == "BUY"
            else (pos.entry_price - low)
        ) / PIP_VALUE
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

def _email_open(pos: Position) -> tuple[str, str]:
    arrow   = "UP" if pos.direction == "BUY" else "DOWN"
    subject = (
        f"[{pos.pair.upper()}] {arrow} {pos.direction} — "
        f"Entry {pos.entry_price:.5f}"
    )
    body = "\n".join([
        f"Trade Opened : {pos.pair.upper()} {pos.direction}",
        f"Timestamp    : {pos.opened_at}",
        "",
        f"Entry        : {pos.entry_price:.5f}",
        f"Stop Loss    : {pos.stop_loss:.5f}  ({pos.risk_pips:.1f} pips)",
        f"Take Profit  : {pos.take_profit:.5f}  ({pos.reward_pips:.1f} pips)",
        f"R:R          : 1 : {pos.rr_ratio:.2f}",
        f"ATR(14) 1h   : {pos.atr:.5f}",
        "",
        f"Basis: {pos.basis}",
    ])
    return subject, body


def _email_be(pos: Position) -> tuple[str, str]:
    subject = f"[{pos.pair.upper()}] {pos.direction} — Stop Moved to Breakeven"
    body = "\n".join([
        f"Breakeven triggered on {pos.pair.upper()} {pos.direction}",
        "",
        f"Entry        : {pos.entry_price:.5f}",
        f"New SL       : {pos.entry_price:.5f}  (breakeven — risk now zero)",
        f"TP still live: {pos.take_profit:.5f}  ({pos.reward_pips:.1f} pips remaining)",
    ])
    return subject, body


def _email_close(pos: Position, event: str, exit_price: float) -> tuple[str, str]:
    pnl_pips = (
        (exit_price - pos.entry_price) if pos.direction == "BUY"
        else (pos.entry_price - exit_price)
    ) / PIP_VALUE
    result   = "WIN" if pnl_pips > 0 else "LOSS"
    reason   = "Take Profit" if event == "close_tp" else "Stop Loss"
    sign     = "+" if pnl_pips >= 0 else ""
    subject  = (
        f"[{pos.pair.upper()}] {pos.direction} Closed — "
        f"{result} {sign}{pnl_pips:.1f} pips"
    )
    body = "\n".join([
        f"Trade Closed : {pos.pair.upper()} {pos.direction}",
        f"Exit Reason  : {reason} Hit",
        "",
        f"Entry        : {pos.entry_price:.5f}",
        f"Exit         : {exit_price:.5f}",
        f"P&L          : {sign}{pnl_pips:.1f} pips",
        f"Result       : {result}",
    ])
    return subject, body


# ── Core tick ─────────────────────────────────────────────────────────────────

def tick(pair: str, symbol: str, state: PairState, dry_run: bool) -> PairState:
    """
    One polling cycle for a single pair:
      1. Refresh cached data (incremental fetch).
      2. If a position is open, check the latest bar for BE / SL / TP events.
      3. Otherwise look for a new entry signal.
      4. Send emails (or log them in dry-run mode) for any events found.
    """
    now = datetime.now(timezone.utc)

    try:
        state = refresh_data(symbol, state)
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
    df_h1 = compute_h1_indicators(state.cache_h1.copy())
    df_5m = compute_m5_indicators(state.cache_5m.copy())

    # ── Manage open position ──────────────────────────────────────────────────
    if state.position is not None:
        pos    = state.position
        latest = df_5m.iloc[-1]   # most recent (possibly still-forming) bar
        events = check_position_events(pos, latest)
        closed = False

        for event, price in events:
            if event == "be":
                log.info("%s  BE triggered — SL moved to %.5f", pair.upper(), pos.entry_price)
                subj, body = _email_be(pos)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

            elif event in ("close_tp", "close_sl"):
                pnl = (
                    (price - pos.entry_price) if pos.direction == "BUY"
                    else (pos.entry_price - price)
                ) / PIP_VALUE
                log.info(
                    "%s  CLOSE %s — %s @ %.5f  P&L %.1f pips",
                    pair.upper(), pos.direction, event, price, pnl,
                )
                subj, body = _email_close(pos, event, price)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

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
    if state.cooldown_until and now < state.cooldown_until:
        log.debug("%s  in cooldown until %s",
                  pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
        return state

    h1_bias = assess_h1_bias(df_h1)
    entry   = find_m5_entry(df_5m, h1_bias["direction"])

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

    signal = build_signal(h1_bias, entry)
    if signal.direction == "FLAT":
        return state

    pos = Position(
        pair        = pair,
        symbol      = symbol,
        direction   = signal.direction,
        entry_price = signal.entry_price,
        stop_loss   = signal.stop_loss,
        take_profit = signal.take_profit,
        atr         = signal.atr,
        risk_pips   = signal.risk_pips,
        reward_pips = signal.reward_pips,
        rr_ratio    = signal.rr_ratio,
        opened_at   = signal.timestamp,
        basis       = signal.entry_basis,
    )
    state.position        = pos
    state.last_signal_bar = entry["bar_time"]

    log.info(
        "%s  OPEN %s @ %.5f  SL=%.5f  TP=%.5f  (%.1f/%.1f pips  R:R 1:%.2f)",
        pair.upper(), pos.direction, pos.entry_price,
        pos.stop_loss, pos.take_profit,
        pos.risk_pips, pos.reward_pips, pos.rr_ratio,
    )

    subj, body = _email_open(pos)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    return state


# ── Daemon loop ───────────────────────────────────────────────────────────────

def daemon_loop(pairs: list[tuple[str, str]], interval: int, dry_run: bool) -> None:
    """Poll all watched pairs in sequence, sleep, repeat."""
    states: dict[str, PairState] = {sym: PairState() for _, sym in pairs}

    log.info(
        "Daemon started — %d pair(s): %s — poll interval %ds%s",
        len(pairs),
        ", ".join(p.upper() for p, _ in pairs),
        interval,
        "  [DRY-RUN]" if dry_run else "",
    )

    while True:
        for pair, symbol in pairs:
            try:
                states[symbol] = tick(pair, symbol, states[symbol], dry_run)
            except Exception as exc:
                log.exception("%s  unexpected error in tick: %s", pair.upper(), exc)

        time.sleep(interval)


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
        "--dry-run",
        action="store_true",
        help="Log events but do not send emails",
    )
    args = parser.parse_args()

    pairs_to_watch = (
        [(args.pair, PAIRS[args.pair])]
        if args.pair
        else list(PAIRS.items())
    )

    daemon_loop(pairs_to_watch, args.interval, args.dry_run)
