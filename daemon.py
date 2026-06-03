"""
FX Trader Daemon (unified v2)
==============================
Monitors the four active FX pairs and manages both automated and discretionary
trades from a single process.

Data source
-----------
OANDA only.
An in-memory OHLCV cache per pair is kept topped up via incremental OANDA fetches.

Poll timing
-----------
  Polls every 60 s unconditionally so new M1 bars are evaluated promptly
  regardless of whether any positions are open.

Trade types
-----------
  automated     — opened by the signal engine (entry pattern + bias filter)
  discretionary — opened manually on OANDA and registered via the control console

Both types use the same three-phase trailing stop model from tradelib.py.

Control console (single socket on port 9876)
---------------------------------------------
  telnet localhost 9876

Commands:
  status                     Running mode, open positions, cooldowns
  pause / resume             Suspend/resume entries and exits
  pause_entry / resume_entry Control new entry signals
  pause_exit / resume_exit   Control automatic exits
  register <id>              Put an open OANDA trade under management
  stoploss <id> <sl>         Override SL for a managed discretionary trade
  takeprofit <id> <tp>       Override TP for a managed discretionary trade
  deregister <id>            Stop managing a trade (does NOT close it)
  close [<id>]               Close a specific trade (or all trades if no id)
  be                         Move all open SLs to breakeven
  materialise_sl             Place real broker SL orders for occult positions
  materialise_tp             Place real broker TP orders for occult positions
  apply_defaults <id>        Push calculated SL/TP to broker for a managed trade
  occult_sl                  Remove broker SL orders (daemon manages exits)
  occult_tp                  Remove broker TP orders (daemon manages exits)
  help / quit

Environment variables
---------------------
  FX_LIVE=false          Paper mode (default) — no broker orders
  FX_LIVE=true           Live mode
  FX_DRY_RUN=true        Log only — no emails or orders
  FX_OCCULT_STOPS=true   SL/TP not sent to broker; daemon closes explicitly
  FX_PAIRS=eurusd,usdjpy Restrict to named pairs (default: all four active pairs)
  FX_CTRL_PORT=9876      Control socket port (default 9876)
  OANDA_RISK_PCT=1       Percent of NAV risked per trade (default 1)
  LOG_LEVEL=INFO         Console log level override

Usage
-----
    python daemon.py                  # paper mode
    python daemon.py --live           # live mode
    python daemon.py --pair eurusd    # single pair
    python daemon.py --dry-run        # no emails
"""

import os
import sys
import json
import math
import signal
import threading
import socket as _socket
import logging
import argparse
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from ta.trend import EMAIndicator

import indicator_eurusd
import indicator_gbpusd
import indicator_usdjpy
import indicator_audusd
import indicator_eurjpy
import oanda
import datalib
import logsetup
import tradelib
from mailer import send_email
import tradelog

load_dotenv()

# ── Pair config ───────────────────────────────────────────────────────────────

PAIR_INDICATORS = {
    "eurusd": indicator_eurusd,
    "gbpusd": indicator_gbpusd,
    "usdjpy": indicator_usdjpy,
    "audusd": indicator_audusd,
    "eurjpy": indicator_eurjpy,
}

STANDARD_SPREADS: dict[str, float] = {
    "eurusd": 1.0,
    "gbpusd": 1.5,
    "usdjpy": 2.0,
    "audusd": 1.5,
    "eurjpy": 1.5,
}

# ── Constants ─────────────────────────────────────────────────────────────────

OANDA_RISK_PCT      = float(os.getenv("OANDA_RISK_PCT", "1"))
DRAWDOWN_HALT_PCT   = float(os.getenv("DRAWDOWN_HALT_PCT", "3.0"))
FX_OCCULT_STOPS     = os.getenv("FX_OCCULT_STOPS", "false").lower() == "true"
FX_PAIRS_ENV       = os.getenv("FX_PAIRS", "").strip()
CONTROL_PORT       = int(os.getenv("FX_CTRL_PORT", "9876"))

COOLDOWN_MINS       = 60
WEEKEND_CLOSE_HOUR  = 20
POLL_INTERVAL_SECS  = 60    # fixed 1-minute poll — matches M1 bar cadence

H1_MAX_BARS = 300
M5_MAX_BARS = 600
D1_MAX_BARS = 100
M1_MAX_BARS = 360     # 6-hour rolling M1 window used to resample M5 and H1
H1_LOOKBACK = pd.Timedelta(hours=3)
M5_LOOKBACK = pd.Timedelta(minutes=15)
D1_LOOKBACK = pd.Timedelta(days=2)
M1_LOOKBACK = pd.Timedelta(hours=2)

_TRADE_LOG  = Path("fx_trades.jsonl")
_LOG_LOCK   = threading.Lock()   # serialises concurrent JSONL writes
_STATE_LOCK = threading.Lock()   # guards ctrl/states/managed between control thread and main loop

log = logging.getLogger("fxtrader.daemon")


# ── Per-pair state ────────────────────────────────────────────────────────────

@dataclass
class PairState:
    cache_h1:        Optional[pd.DataFrame]          = None
    cache_5m:        Optional[pd.DataFrame]          = None
    cache_1d:        Optional[pd.DataFrame]          = None
    cache_m1:        Optional[pd.DataFrame]          = None
    position:        Optional[tradelib.Position]     = None   # automated position
    cooldown_until:  Optional[datetime]              = None
    last_signal_bar: Optional[str]                   = None
    month_pips:      float                           = 0.0
    last_bias:       str                             = "FLAT"


class ControlState:
    def __init__(self):
        self.pause_entry:            bool            = False
        self.pause_exit:             bool            = False
        self.drawdown_halt:          bool            = False
        self.session_loss_pct:       float           = 0.0
        self.pending_be:             bool            = False
        self.pending_close_all:      bool            = False
        self.pending_materialise_sl: bool            = False
        self.pending_materialise_tp: bool            = False
        self.pending_apply_defaults: list            = []
        self.pending_occult_sl:      bool            = False
        self.pending_occult_tp:      bool            = False
        self.pending_registers:      list            = []
        self.pending_sl_updates:     list            = []
        self.pending_tp_updates:     list            = []
        self.pending_deregisters:    list            = []
        self.pending_close_one:      list            = []
        self.wake_event:             threading.Event = threading.Event()


# ── Data helpers ──────────────────────────────────────────────────────────────

def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def _fetch_oanda(
    pair: str, granularity: str, count: int = 200,
    start: Optional[datetime] = None,
) -> pd.DataFrame:
    """Fetch OHLCV bars from OANDA. Returns UTC-indexed DataFrame."""
    oanda_gran = {"H1": "H1", "M5": "M5", "M1": "M1", "D": "D"}[granularity]
    candles = oanda.get_candles(pair, granularity=oanda_gran, count=count, from_time=start)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df.index = pd.to_datetime(df["time"], utc=True)
    df.drop(columns=["time"], inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def _merge_cache(cached: pd.DataFrame, new: pd.DataFrame, max_bars: int) -> pd.DataFrame:
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined.tail(max_bars)


def _resample_m1(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Resample M1 bars to M5 or H1, preserving the forming (partial) last bar."""
    freq = {"M5": "5min", "H1": "1h"}[target]
    return (
        df.resample(freq, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open"])
    )


def refresh_data(pair: str, state: PairState) -> PairState:
    """Update in-memory OHLCV caches for one pair.

    Primary path: fetch M1 from OANDA and resample to M5 and H1 so that the
    forming (in-progress) H1 bar is always included.
    Fallback: native H1 and M5 from OANDA when M1 is unavailable.
    """
    if state.cache_h1 is None:
        # ── Warm-start ────────────────────────────────────────────────────────
        try:
            df_m1_full = datalib.load(pair, "M1")
            df_1d      = datalib.load(pair, "D").tail(D1_MAX_BARS)
            if df_m1_full.empty:
                raise ValueError("empty M1 parquet")
            # H1 via resample keeps the forming bar; M5 via datalib drops it
            # (historical M5 bars from parquet are all complete).
            df_h1 = _resample_m1(df_m1_full, "H1").tail(H1_MAX_BARS)
            df_5m = datalib.resample(df_m1_full, "M5").tail(M5_MAX_BARS)
            state.cache_m1 = df_m1_full.tail(M1_MAX_BARS)
            state.cache_h1 = df_h1
            state.cache_5m = df_5m
            state.cache_1d = df_1d
            log.info(
                "%s  warm-started from parquet: %d×H1  %d×M5  %d×D — topping up from OANDA …",
                pair.upper(), len(state.cache_h1), len(state.cache_5m), len(state.cache_1d),
            )
            # Fall through to incremental update to fetch any bars newer than
            # the last parquet entry.
        except Exception as exc:
            log.info("%s  parquet unavailable (%s) — initial fetch from OANDA …", pair.upper(), exc)
            m1  = _fetch_oanda(pair, "M1", count=M1_MAX_BARS)
            h1  = _fetch_oanda(pair, "H1", count=H1_MAX_BARS)
            d1  = _fetch_oanda(pair, "D",  count=D1_MAX_BARS)
            if not m1.empty:
                state.cache_m1 = m1
                state.cache_5m = _resample_m1(m1, "M5").tail(M5_MAX_BARS)
                h1_tail        = _resample_m1(m1, "H1")
                state.cache_h1 = _merge_cache(h1, h1_tail, H1_MAX_BARS) if not h1.empty else h1_tail.tail(H1_MAX_BARS)
            else:
                # M1 unavailable — fall back to native H1/M5 (no forming bar)
                state.cache_h1 = h1
                state.cache_5m = _fetch_oanda(pair, "M5", count=M5_MAX_BARS)
            state.cache_1d = d1
            if not state.cache_h1.empty:
                log.info(
                    "%s  cached: %d×H1  %d×M5  %d×D",
                    pair.upper(), len(state.cache_h1), len(state.cache_5m), len(state.cache_1d),
                )
            return state

    # ── Incremental update ────────────────────────────────────────────────────
    d1_start   = (state.cache_1d.index[-1] - D1_LOOKBACK).to_pydatetime()
    m1_updated = False

    if state.cache_m1 is not None:
        m1_start = (state.cache_m1.index[-1] - M1_LOOKBACK).to_pydatetime()
        new_m1   = _fetch_oanda(pair, "M1", start=m1_start)
        if not new_m1.empty:
            state.cache_m1 = _merge_cache(state.cache_m1, new_m1, M1_MAX_BARS)
            new_h1 = _resample_m1(state.cache_m1, "H1")
            new_5m = _resample_m1(state.cache_m1, "M5")
            state.cache_h1 = _merge_cache(state.cache_h1, new_h1, H1_MAX_BARS)
            state.cache_5m = _merge_cache(state.cache_5m, new_5m, M5_MAX_BARS)
            m1_updated = True

    if not m1_updated:
        # M1 unavailable this tick — fall back to native H1/M5
        h1_start = (state.cache_h1.index[-1] - H1_LOOKBACK).to_pydatetime()
        m5_start = (state.cache_5m.index[-1] - M5_LOOKBACK).to_pydatetime()
        new_h1   = _fetch_oanda(pair, "H1", start=h1_start)
        new_5m   = _fetch_oanda(pair, "M5", start=m5_start)
        if not new_h1.empty:
            state.cache_h1 = _merge_cache(state.cache_h1, new_h1, H1_MAX_BARS)
        if not new_5m.empty:
            state.cache_5m = _merge_cache(state.cache_5m, new_5m, M5_MAX_BARS)

    new_1d = _fetch_oanda(pair, "D", start=d1_start)
    if not new_1d.empty:
        state.cache_1d = _merge_cache(state.cache_1d, new_1d, D1_MAX_BARS)

    try:
        datalib.update(pair)
    except Exception as exc:
        log.warning("%s  datalib update failed: %s", pair.upper(), exc)

    return state


# ── Spread guard ──────────────────────────────────────────────────────────────

def _spread_ok(pair: str) -> tuple[bool, float]:
    try:
        price       = oanda.get_price(pair)
        pv          = PAIR_INDICATORS[pair].pip_value(pair)
        spread_pips = (price["ask"] - price["bid"]) / pv
        threshold   = STANDARD_SPREADS[pair] * 2
        ok          = spread_pips <= threshold
        log.debug("%s  spread %.1f pips (limit %.1f) — %s",
                  pair.upper(), spread_pips, threshold, "OK" if ok else "BLOCKED")
        return ok, spread_pips
    except Exception as exc:
        log.error("%s  spread check failed (%s) — blocking entry", pair.upper(), exc)
        return False, 0.0


# ── Position sizing ───────────────────────────────────────────────────────────

def _calc_units(pair: str, risk_pips: float) -> int:
    try:
        acct = oanda.get_account_summary()
        nav  = float(acct["NAV"])
    except Exception as exc:
        log.warning("NAV fetch failed (%s) — using 10 000 fallback", exc)
        nav = 10_000.0

    jpy_rate = 150.0
    if pair == "usdjpy":
        try:
            price    = oanda.get_price(pair)
            jpy_rate = (price["bid"] + price["ask"]) / 2
        except Exception:
            pass

    return tradelib.calc_units(pair, risk_pips, nav, OANDA_RISK_PCT, jpy_rate)


# ── Trade log ─────────────────────────────────────────────────────────────────

def _log_append(record: dict) -> None:
    with _LOG_LOCK:
        with _TRADE_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")


def _log_open(pos: tradelib.Position) -> None:
    _log_append({
        "event":       "open",
        "ts":          datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_type":  pos.trade_type,
        "trade_id":    pos.trade_id,
        "pair":        pos.pair,
        "symbol":      pos.symbol,
        "direction":   pos.direction,
        "entry":       pos.entry_price,
        "sl":          pos.stop_loss,
        "tp":          pos.take_profit,
        "atr":         pos.atr,
        "risk_pips":   pos.risk_pips,
        "reward_pips": pos.reward_pips,
        "rr":          pos.rr_ratio,
        "opened_at":   pos.opened_at,
        "basis":       pos.basis,
    })


def _log_be(pos: tradelib.Position) -> None:
    _log_append({
        "event":    "be",
        "ts":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_id": pos.trade_id,
        "pair":     pos.pair,
        "sl":       pos.stop_loss,
    })


def _log_extend(pos: tradelib.Position) -> None:
    _log_append({
        "event":    "extend_tp",
        "ts":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_id": pos.trade_id,
        "pair":     pos.pair,
        "sl":       pos.stop_loss,
        "tp":       pos.take_profit,
    })


def _log_close(pos: tradelib.Position, reason: str, exit_price: float, pnl_pips: float) -> None:
    _log_append({
        "event":     "close",
        "ts":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_type": pos.trade_type,
        "trade_id":  pos.trade_id,
        "pair":      pos.pair,
        "direction": pos.direction,
        "entry":     pos.entry_price,
        "exit":      exit_price,
        "pnl_pips":  round(pnl_pips, 1),
        "reason":    reason,
        "extended":  pos.tp_extended,
    })


def _load_state() -> dict:
    """Replay fx_trades.jsonl and return open positions by pair (automated) or trade_id (discretionary)."""
    import json
    if not _TRADE_LOG.exists():
        return {"automated": {}, "discretionary": {}, "month_pips": {}}

    automated: dict[str, dict]    = {}   # pair → position data
    discrete:  dict[str, dict]    = {}   # trade_id → position data
    closed:    set[str]           = set()
    month_pips: dict[str, float]  = {}

    with _TRADE_LOG.open() as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                log.warning("fx_trades.jsonl line %d — malformed (skipped)", lineno)
                continue
            event    = rec.get("event")
            trade_id = rec.get("trade_id")
            pair     = rec.get("pair")
            tt       = rec.get("trade_type", "automated")

            if event == "open":
                if tt == "automated":
                    automated[pair] = rec
                else:
                    if trade_id:
                        discrete[trade_id] = rec
            elif event == "close":
                if tt == "automated" and pair:
                    automated.pop(pair, None)
                elif trade_id:
                    discrete.pop(trade_id, None)
                    closed.add(str(trade_id) if trade_id else "")
                pnl = rec.get("pnl_pips", 0.0)
                if pair:
                    month_pips[pair] = month_pips.get(pair, 0.0) + pnl
            elif event == "deregister" and trade_id:
                discrete.pop(str(trade_id), None)
            elif event == "be":
                if tt == "automated" and pair and pair in automated:
                    automated[pair]["sl"] = automated[pair]["entry"]
                    automated[pair]["be_activated"] = True
                elif trade_id and str(trade_id) in discrete:
                    discrete[str(trade_id)]["sl"] = discrete[str(trade_id)]["entry"]
                    discrete[str(trade_id)]["be_activated"] = True
            elif event == "extend_tp":
                if pair and pair in automated:
                    automated[pair]["sl"] = rec["sl"]
                    automated[pair]["tp"] = rec["tp"]
                    automated[pair]["tp_extended"] = True
                elif trade_id and str(trade_id) in discrete:
                    discrete[str(trade_id)]["sl"] = rec["sl"]
                    discrete[str(trade_id)]["tp"] = rec["tp"]
                    discrete[str(trade_id)]["tp_extended"] = True

    return {"automated": automated, "discretionary": discrete, "month_pips": month_pips}


def _pos_from_record(rec: dict, occult_stops: bool) -> tradelib.Position:
    """Reconstruct a Position from a trade-log open record."""
    known = tradelib.Position.__dataclass_fields__.keys()
    data = {
        "pair":        rec["pair"],
        "symbol":      rec.get("symbol", rec["pair"].upper()),
        "direction":   rec["direction"],
        "trade_type":  rec.get("trade_type", "automated"),
        "entry_price": rec["entry"],
        "stop_loss":   rec["sl"],
        "take_profit": rec["tp"],
        "atr":         rec.get("atr", 0.0),
        "risk_pips":   rec.get("risk_pips", 0.0),
        "reward_pips": rec.get("reward_pips", 0.0),
        "rr_ratio":    rec.get("rr", 0.0),
        "opened_at":   rec.get("opened_at", ""),
        "basis":       rec.get("basis", ""),
        "trade_id":    rec.get("trade_id"),
        "be_activated": rec.get("be_activated", False),
        "tp_extended":  rec.get("tp_extended", False),
        "original_tp": rec.get("original_tp", rec.get("tp", 0.0)),
        "best_price":  rec.get("best_price", rec.get("entry", 0.0)),
        "occult_stops": occult_stops,
    }
    return tradelib.Position(**{k: v for k, v in data.items() if k in known})


# ── Email builders ────────────────────────────────────────────────────────────

def _email_open(pos: tradelib.Position) -> tuple[str, str]:
    tag  = "[FX]" if pos.trade_type == "automated" else "[TM]"
    pfmt = ".5f"
    arrow = "UP" if pos.direction == "BUY" else "DOWN"
    subj  = f"{tag} [{pos.pair.upper()}] {arrow} {pos.direction} — Fill {pos.entry_price:{pfmt}}"
    stops = "occult (daemon-managed)" if pos.occult_stops else "broker order"
    lines = [
        f"Trade Opened  : {pos.pair.upper()} {pos.direction}  [{pos.trade_type}]",
        f"Timestamp     : {pos.opened_at}",
        "",
    ]
    if pos.signal_price and pos.signal_price != pos.entry_price:
        lines.append(f"Signal Entry  : {pos.signal_price:{pfmt}}")
    if pos.trade_id:
        lines.append(f"Trade ID      : {pos.trade_id}")
    lines += [
        f"Fill          : {pos.entry_price:{pfmt}}",
        f"Stop Loss     : {pos.stop_loss:{pfmt}}  ({pos.risk_pips:.1f} pips)  [{stops}]",
        f"Take Profit   : {pos.take_profit:{pfmt}}  ({pos.reward_pips:.1f} pips)  [{stops}]",
        f"R:R           : 1 : {pos.rr_ratio:.2f}",
        f"ATR(14) 1h    : {pos.atr:{pfmt}}",
        "",
        f"Basis: {pos.basis}",
    ]
    return subj, "\n".join(lines)


def _email_be(pos: tradelib.Position) -> tuple[str, str]:
    tag  = "[FX]" if pos.trade_type == "automated" else "[TM]"
    subj = f"{tag} [{pos.pair.upper()}] {pos.direction} — Stop Moved to Breakeven"
    body = "\n".join([
        f"Breakeven triggered : {pos.pair.upper()} {pos.direction}",
        "",
        f"Entry   : {pos.entry_price:.5f}",
        f"New SL  : {pos.entry_price:.5f}  (risk now zero)",
        f"TP live : {pos.take_profit:.5f}  ({pos.reward_pips:.1f} pips remaining)",
    ])
    return subj, body


def _email_extend(pos: tradelib.Position) -> tuple[str, str]:
    tag  = "[FX]" if pos.trade_type == "automated" else "[TM]"
    subj = f"{tag} [{pos.pair.upper()}] {pos.direction} — TP Extended (momentum gate)"
    body = "\n".join([
        f"Phase 3 extension : {pos.pair.upper()} {pos.direction}",
        "",
        f"Entry   : {pos.entry_price:.5f}",
        f"New SL  : {pos.stop_loss:.5f}  (locked at 90% of original TP)",
        f"New TP  : {pos.take_profit:.5f}  (2× original target)",
        f"Trail   : tightened to ATR × SL_MULT × 0.5",
    ])
    return subj, body


def _email_close(pos: tradelib.Position, event: str, exit_price: float) -> tuple[str, str]:
    tag  = "[FX]" if pos.trade_type == "automated" else "[TM]"
    pv   = PAIR_INDICATORS[pos.pair].pip_value(pos.pair)
    pnl  = (
        (exit_price - pos.entry_price) if pos.direction == "BUY"
        else (pos.entry_price - exit_price)
    ) / pv
    result = "WIN" if pnl > 0 else "LOSS"
    reasons = {
        "close_tp":      "Take Profit",
        "close_sl":      "Stop Loss",
        "close_weekend": "Weekend Close (pre-market)",
        "close_manual":  "Manual Close (console)",
    }
    sign = "+" if pnl >= 0 else ""
    subj = f"{result} — {tag} [{pos.pair.upper()}] {pos.direction} Closed {sign}{pnl:.1f} pips"
    lines = [
        f"Trade Closed  : {pos.pair.upper()} {pos.direction}  [{pos.trade_type}]",
        f"Exit Reason   : {reasons.get(event, 'Stop Loss')}",
        "",
        f"Entry  : {pos.entry_price:.5f}",
        f"Exit   : {exit_price:.5f}",
        f"P&L    : {sign}{pnl:.1f} pips",
        f"Result : {result}",
    ]
    if pos.trade_id:
        lines.insert(0, f"Trade ID      : {pos.trade_id}")
    return subj, "\n".join(lines)


def _email_drawdown_halt(loss_pct: float) -> tuple[str, str]:
    subj = f"[FX] CIRCUIT BREAKER — {loss_pct:.1f}% session drawdown — entries halted"
    body = "\n".join([
        f"Session drawdown has reached {loss_pct:.1f}% of estimated NAV.",
        f"Threshold: {DRAWDOWN_HALT_PCT:.1f}%",
        "",
        "New automated entries are HALTED.",
        "Open positions continue to be managed normally.",
        "",
        "To resume intra-day: send 'resume_drawdown' via the control socket.",
        "The circuit breaker resets automatically at UTC midnight.",
    ])
    return subj, body


def _email_startup(
    pairs: list[str],
    auto_restored: list[tradelib.Position],
    disc_restored: list[tradelib.Position],
    live: bool,
    occult_stops: bool,
) -> tuple[str, str]:
    mode = "LIVE" if live else "PAPER"
    if occult_stops:
        mode += " — OCCULT STOPS"
    subj = "[FX Trader] Daemon started"
    lines = [
        "FX Trader daemon (v2) has started.",
        "",
        f"Monitoring : {', '.join(p.upper() for p in pairs)}",
        f"Mode       : {mode}",
        f"Started    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
    ]
    if auto_restored:
        lines += ["", f"Restored {len(auto_restored)} automated position(s):"]
        for pos in auto_restored:
            lines += [f"  {pos.pair.upper()} {pos.direction}  entry={pos.entry_price:.5f}"]
    if disc_restored:
        lines += ["", f"Restored {len(disc_restored)} discretionary position(s):"]
        for pos in disc_restored:
            lines += [f"  {pos.pair.upper()} {pos.direction}  id={pos.trade_id}  entry={pos.entry_price:.5f}"]
    if not auto_restored and not disc_restored:
        lines += ["", "No open positions restored."]
    return subj, "\n".join(lines)


def _email_summary(
    pairs: list[str],
    states: dict[str, PairState],
    managed: dict[str, tradelib.Position],
    month_pips: float,
) -> tuple[str, str]:
    now  = datetime.now(timezone.utc)
    subj = f"[FX Trader] Daily Summary — {now.strftime('%Y-%m-%d')}"
    sign = "+" if month_pips >= 0 else ""
    try:
        acct      = oanda.get_account_summary()
        bal       = float(acct["balance"])
        nav       = float(acct["NAV"])
        unreal    = float(acct["unrealizedPL"])
        us        = "+" if unreal >= 0 else ""
        acct_line = f"Account   : ${bal:,.2f}  (NAV ${nav:,.2f})"
        pnl_line  = f"Open P&L  : {us}${unreal:,.2f}"
    except Exception:
        acct_line = "Account   : unavailable"
        pnl_line  = "Open P&L  : unavailable"

    lines = [
        f"Daily Status — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Pairs      : {', '.join(p.upper() for p in pairs)}",
        acct_line,
        pnl_line,
        f"Month pips : {sign}{month_pips:.1f}",
        "",
    ]

    auto_open = [states[p].position for p in pairs if states[p].position is not None]
    if auto_open:
        lines.append(f"Automated ({len(auto_open)}):")
        for pos in auto_open:
            lines.append(
                f"  {pos.pair.upper()} {pos.direction}  "
                f"SL={pos.stop_loss:.5f}  TP={pos.take_profit:.5f}  "
                f"BE={'on' if pos.be_activated else 'off'}"
            )
    else:
        lines.append("Automated: none open")

    if managed:
        lines.append(f"\nDiscretionary ({len(managed)}):")
        for tid, pos in managed.items():
            lines.append(
                f"  {pos.pair.upper()} {pos.direction}  id={tid}  "
                f"SL={pos.stop_loss:.5f}  TP={pos.take_profit:.5f}  "
                f"BE={'on' if pos.be_activated else 'off'}"
            )

    return subj, "\n".join(lines)


# ── Event processing helper ───────────────────────────────────────────────────

def _process_events(
    pos:      tradelib.Position,
    bar:      pd.Series,
    pair:     str,
    dry_run:  bool,
    live:     bool,
    pause_exit: bool,
) -> tuple[bool, Optional[float]]:
    """
    Run check_position_events on one bar.  Handle BE, extend, and close events.
    Returns (closed, exit_price).  Caller removes position from state on closed=True.
    """
    ind     = PAIR_INDICATORS[pair]
    prev_sl = pos.stop_loss
    events  = tradelib.check_position_events(pos, bar, ind)
    closed  = False
    exit_price: Optional[float] = None

    for event, price in events:
        if event == "be":
            pass  # trailing stop is broker-managed; no action needed

        elif event == "extend_tp":
            log.info(
                "%s  TP EXTENDED — SL=%.5f  TP=%.5f",
                pair.upper(), pos.stop_loss, pos.take_profit,
            )
            _log_extend(pos)
            if live and pos.trade_id:
                try:
                    if not pos.occult_stops or pos.sl_materialised:
                        oanda.modify_trade_sl(pos.trade_id, pos.stop_loss, pair)
                    if not pos.occult_stops or pos.tp_materialised:
                        oanda.modify_trade_tp(pos.trade_id, pos.take_profit, pair)
                except Exception as exc:
                    log.warning("%s  OANDA extend failed: %s", pair.upper(), exc)
            subj, body = _email_extend(pos)
            if dry_run:
                log.info("[DRY-RUN] %s", subj)
            else:
                send_email(subj, body)
            prev_sl = pos.stop_loss

        elif event in ("close_tp", "close_sl"):
            if pause_exit:
                log.info("%s  %s hit but exit paused — holding", pair.upper(), event)
                continue

            actual_price = price
            if live and pos.trade_id:
                # For occult stops: skip if the broker order already materialised
                # (OANDA fired it; it's already closed on the exchange).
                # For non-occult: always attempt — if OANDA's SL/TP already fired
                # the call will fail with 404 (expected; logged as warning).
                already = pos.occult_stops and (
                    (event == "close_sl" and pos.sl_materialised) or
                    (event == "close_tp" and pos.tp_materialised)
                )
                if not already:
                    try:
                        result = oanda.close_trade(pos.trade_id)
                        fill   = result.get("orderFillTransaction", {})
                        if fill.get("price"):
                            actual_price = float(fill["price"])
                    except Exception as exc:
                        if pos.occult_stops:
                            log.error("%s  OANDA close failed: %s", pair.upper(), exc)
                        else:
                            log.warning(
                                "%s  OANDA close attempt (broker SL/TP may have fired): %s",
                                pair.upper(), exc,
                            )

            pv  = PAIR_INDICATORS[pair].pip_value(pair)
            pnl = (
                (actual_price - pos.entry_price) if pos.direction == "BUY"
                else (pos.entry_price - actual_price)
            ) / pv
            log.info(
                "%s  CLOSE %s — %s @ %.5f  P&L %.1f pips",
                pair.upper(), pos.direction, event, actual_price, pnl,
            )
            _log_close(pos, event, actual_price, pnl)
            subj, body = _email_close(pos, event, actual_price)
            if dry_run:
                log.info("[DRY-RUN] %s", subj)
            else:
                send_email(subj, body)

            closed     = True
            exit_price = actual_price
            break

    return closed, exit_price


# ── Automated tick ────────────────────────────────────────────────────────────

def tick(
    pair:         str,
    state:        PairState,
    dry_run:      bool,
    live:         bool,
    occult_stops: bool,
    managed:      dict[str, tradelib.Position],
    ctrl:         ControlState,
) -> PairState:
    """
    One poll cycle for one pair.
    1. Refresh OANDA cache.
    2. If automated position open → check events.
    3. Else → check for new entry signal.
    4. Run event check for any discretionary positions on this pair.
    """
    now = datetime.now(timezone.utc)

    try:
        state = refresh_data(pair, state)
    except Exception as exc:
        log.warning("%s  data refresh failed: %s", pair.upper(), exc)
        return state

    if state.cache_h1 is None or len(state.cache_h1) < 31:
        return state
    if state.cache_5m is None or len(state.cache_5m) < 30:
        return state

    ind   = PAIR_INDICATORS[pair]
    df_h1 = ind.compute_h1_indicators(state.cache_h1.copy())
    df_5m = ind.compute_m5_indicators(state.cache_5m.copy())

    df_4h = state.cache_h1.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    df_4h = ind.compute_h1_indicators(df_4h)
    df_4h["ema_4h"] = EMAIndicator(
        close=df_4h["close"], window=ind.H4_EMA_PERIOD
    ).ema_indicator()
    if hasattr(ind, "compute_supertrend"):
        df_4h = ind.compute_supertrend(df_4h, period=10, multiplier=3.0)

    df_1d = None
    if hasattr(ind, "compute_daily_adx") and state.cache_1d is not None and len(state.cache_1d) >= 14:
        df_1d = ind.compute_daily_adx(state.cache_1d.copy())

    latest = df_5m.iloc[-1]

    # ── Automated position management ────────────────────────────────────────
    if state.position is not None:
        pos    = state.position
        closed, exit_price = _process_events(pos, latest, pair, dry_run, live, ctrl.pause_exit)
        if closed:
            if exit_price is not None:
                pv  = ind.pip_value(pair)
                pnl = (
                    (exit_price - pos.entry_price) if pos.direction == "BUY"
                    else (pos.entry_price - exit_price)
                ) / pv
                state.month_pips  += pnl
                # Drawdown circuit breaker
                if pnl < 0 and pos.risk_pips > 0:
                    loss_pct = abs(pnl) / pos.risk_pips * OANDA_RISK_PCT
                    ctrl.session_loss_pct += loss_pct
                    if ctrl.session_loss_pct >= DRAWDOWN_HALT_PCT and not ctrl.drawdown_halt:
                        ctrl.drawdown_halt = True
                        log.error(
                            "CIRCUIT BREAKER: %.1f%% session drawdown (threshold %.1f%%) — entries halted",
                            ctrl.session_loss_pct, DRAWDOWN_HALT_PCT,
                        )
                        subj, body = _email_drawdown_halt(ctrl.session_loss_pct)
                        if not dry_run:
                            send_email(subj, body)
                # Cooldown only on stop-loss hits
                events_were_sl = pnl < 0
                if events_were_sl:
                    state.cooldown_until = now + timedelta(minutes=COOLDOWN_MINS)
                    log.info("%s  cooldown until %s",
                             pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
            state.position = None
        else:
            log.debug(
                "%s  [auto] open: SL=%.5f  BE=%s  ext=%s",
                pair.upper(), pos.stop_loss,
                "on" if pos.be_activated else "off", pos.tp_extended,
            )

    # ── Entry signal check ───────────────────────────────────────────────────
    elif not ctrl.pause_entry and not ctrl.drawdown_halt:
        if state.cooldown_until and now < state.cooldown_until:
            log.debug("%s  cooldown until %s", pair.upper(),
                      state.cooldown_until.strftime("%H:%M UTC"))
        elif hasattr(ind, "BLOCKED_DAYS") and now.weekday() in ind.BLOCKED_DAYS:
            log.debug("%s  DOW gate — %s blocked", pair.upper(), now.strftime("%A"))
        else:
            bias_info = ind.assess_h1_bias(df_h1, df_4h=df_4h, df_1d=df_1d)
            state.last_bias = bias_info["direction"]

            if bias_info["direction"] != "FLAT":
                entry = ind.find_m5_entry(df_5m, bias_info["direction"])
                if entry and entry["bar_time"] != state.last_signal_bar:
                    signal = ind.build_signal(bias_info, entry, pair.upper(), spread_pips=STANDARD_SPREADS[pair])

                    if signal.direction != "FLAT" and _tp_sane(signal):
                        spread_ok, _ = _spread_ok(pair)
                        if spread_ok:
                            state = _open_automated(
                                pair, signal, state, dry_run, live, occult_stops
                            )
                            if state.position is not None:
                                state.last_signal_bar = entry["bar_time"]
                        else:
                            log.info("%s  signal skipped — spread too wide", pair.upper())
                            state.last_signal_bar = entry["bar_time"]
                    else:
                        state.last_signal_bar = entry["bar_time"]

    # ── Discretionary position management ───────────────────────────────────
    for tid, pos in list(managed.items()):
        if pos.pair != pair:
            continue
        closed, _ = _process_events(pos, latest, pair, dry_run, live, ctrl.pause_exit)
        if closed:
            managed.pop(tid, None)

    return state


def _tp_sane(signal: tradelib.Signal) -> bool:
    return not (
        (signal.direction == "BUY"  and signal.take_profit <= signal.entry_price) or
        (signal.direction == "SELL" and signal.take_profit >= signal.entry_price)
    )


def _open_automated(
    pair:         str,
    signal:       tradelib.Signal,
    state:        PairState,
    dry_run:      bool,
    live:         bool,
    occult_stops: bool,
) -> PairState:
    trade_id    = None
    entry_price = signal.entry_price
    stop_loss   = signal.stop_loss
    take_profit = signal.take_profit
    risk_pips   = signal.risk_pips
    reward_pips = signal.reward_pips
    rr_ratio    = signal.rr_ratio

    if live:
        ind               = PAIR_INDICATORS[pair]
        pv                = ind.pip_value(pair)
        trailing_distance = round(signal.risk_pips * pv, 5)
        units             = _calc_units(pair, signal.risk_pips)
        try:
            result = oanda.place_market_order(
                pair              = pair,
                direction         = signal.direction,
                units             = units,
                trailing_distance = trailing_distance,
                take_profit       = signal.take_profit,
                occult_stops      = occult_stops,
            )
            if "orderFillTransaction" not in result:
                cancel = result.get("orderCancelTransaction", {})
                reject = result.get("orderRejectTransaction", {})
                reason = cancel.get("reason") or reject.get("reason") or "no fill"
                raise RuntimeError(f"Order rejected — {reason}")
            trade_id = result["orderFillTransaction"]["tradeOpened"]["tradeID"]
            fill_str = result["orderFillTransaction"].get("price")
            if fill_str:
                entry_price = round(float(fill_str), 5)
                # Shift TP by fill slippage to preserve the original reward distance
                # from entry.  SL is snapped to HA_SL_MAX_PIPS from fill; without
                # this TP shift, a stale signal filled well above the signal bar close
                # produces a TP only a fraction of a pip above the fill.
                slippage    = entry_price - signal.entry_price
                take_profit = round(signal.take_profit + slippage, 5)
                stop_loss, risk_pips, reward_pips, rr_ratio = tradelib.adjust_sl_for_fill(
                    entry_price, stop_loss, take_profit, signal.direction, ind, pv,
                )
                min_rr = getattr(ind, "HA_MIN_RR", 1.5)
                if rr_ratio < min_rr:
                    log.warning(
                        "%s  post-fill R:R %.2f < %.1f — closing immediately",
                        pair.upper(), rr_ratio, min_rr,
                    )
                    try:
                        oanda.close_trade(trade_id)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Stale-signal fill: R:R {rr_ratio:.2f} < {min_rr} after "
                        f"{slippage/pv:+.1f} pip slippage"
                    )
                if take_profit != signal.take_profit and not occult_stops:
                    try:
                        oanda.modify_trade_tp(trade_id, take_profit, pair)
                    except Exception as exc:
                        log.warning("%s  TP update after fill-slippage failed: %s", pair.upper(), exc)
        except Exception as exc:
            log.error("%s  OANDA order failed — will retry next poll: %s", pair.upper(), exc)
            return state

    pos = tradelib.Position(
        pair         = pair,
        symbol       = pair.upper(),
        direction    = signal.direction,
        trade_type   = "automated",
        entry_price  = entry_price,
        stop_loss    = stop_loss,
        take_profit  = take_profit,
        atr          = signal.atr,
        risk_pips    = risk_pips,
        reward_pips  = reward_pips,
        rr_ratio     = rr_ratio,
        opened_at    = signal.timestamp,
        basis        = signal.entry_basis,
        trade_id     = trade_id,
        occult_stops = occult_stops,
        signal_price = signal.entry_price,
        original_tp  = take_profit,
        best_price   = entry_price,
    )
    state.position = pos
    _log_open(pos)

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

    # Also log to the tradelog module (legacy compatibility)
    try:
        tradelog.log_open(pos)
    except Exception:
        pass

    return state


# ── Discretionary trade registration ─────────────────────────────────────────

def _register_trade(
    trade_id:     str,
    occult_stops: bool,
    live:         bool,
) -> tuple[Optional[tradelib.Position], str]:
    """Fetch trade from OANDA, compute ATR, build Position. Returns (pos, err)."""
    try:
        open_trades = oanda.get_open_trades()
    except Exception as exc:
        return None, f"Could not fetch open trades: {exc}"

    trade = next((t for t in open_trades if str(t.get("id")) == str(trade_id)), None)
    if trade is None:
        ids = [t.get("id") for t in open_trades]
        return None, f"Trade {trade_id} not found. Open IDs: {ids}"

    try:
        entry_price = float(trade["price"])
        direction   = "BUY" if int(trade["currentUnits"]) > 0 else "SELL"
        opened_at   = trade.get("openTime", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        pair        = trade["instrument"].replace("_", "").lower()
    except Exception as exc:
        return None, f"Could not parse trade: {exc}"

    if pair not in PAIR_INDICATORS:
        return None, f"Unsupported pair: {pair}  (supported: {', '.join(PAIR_INDICATORS)})"

    ind = PAIR_INDICATORS[pair]
    pv  = ind.pip_value(pair)

    # ATR from recent H1 bars
    atr = 0.001
    try:
        df_h1 = _fetch_oanda(pair, "H1", count=100)
        if len(df_h1) >= 20:
            df_h1 = ind.compute_h1_indicators(df_h1)
            atr   = float(df_h1.iloc[-1]["atr"])
    except Exception as exc:
        log.warning("%s  ATR fetch failed (%s) — using %.4f", pair.upper(), exc, atr)

    # Catch up if price has moved since entry
    try:
        price_data    = oanda.get_price(pair)
        current_price = (price_data["bid"] + price_data["ask"]) / 2
    except Exception:
        current_price = entry_price

    sl, tp, be_activated, best_price = tradelib.calc_registration_levels(
        direction, entry_price, current_price, atr, ind, pv,
    )
    risk_pips   = abs(entry_price - sl) / pv
    reward_pips = abs(tp - entry_price) / pv
    rr_ratio    = reward_pips / risk_pips if risk_pips > 0 else 0.0

    pos = tradelib.Position(
        pair         = pair,
        symbol       = pair.upper(),
        direction    = direction,
        trade_type   = "discretionary",
        entry_price  = entry_price,
        stop_loss    = sl,
        take_profit  = tp,
        atr          = atr,
        risk_pips    = round(risk_pips, 1),
        reward_pips  = round(reward_pips, 1),
        rr_ratio     = round(rr_ratio, 2),
        opened_at    = opened_at,
        basis        = "discretionary — registered via console",
        trade_id     = str(trade_id),
        occult_stops = occult_stops,
        original_tp  = tp,
        be_activated = be_activated,
        best_price   = best_price,
    )

    if live and not occult_stops:
        try:
            oanda.modify_trade_sl(pos.trade_id, sl, pair)
        except Exception as exc:
            log.warning("%s  broker SL set failed: %s", pair.upper(), exc)
        try:
            oanda.modify_trade_tp(pos.trade_id, tp, pair)
        except Exception as exc:
            log.warning("%s  broker TP set failed: %s", pair.upper(), exc)

    return pos, ""


# ── Bulk position helpers ─────────────────────────────────────────────────────

def _close_all(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
    dry_run: bool,
    reason:  str = "close_manual",
) -> None:
    for pair in pairs:
        pos = states[pair].position
        if pos is not None:
            _close_single(pos, live, dry_run, reason)
            states[pair].position = None

    for tid in list(managed.keys()):
        pos = managed.pop(tid, None)
        if pos:
            _close_single(pos, live, dry_run, reason)


def _close_single(
    pos:     tradelib.Position,
    live:    bool,
    dry_run: bool,
    reason:  str,
) -> None:
    pair = pos.pair
    try:
        price_data  = oanda.get_price(pair)
        exit_price  = (price_data["bid"] + price_data["ask"]) / 2
    except Exception:
        exit_price = pos.entry_price

    if live and pos.trade_id:
        try:
            oanda.close_trade(pos.trade_id)
        except Exception as exc:
            log.error("%s  close failed: %s", pair.upper(), exc)

    pv  = PAIR_INDICATORS[pair].pip_value(pair)
    pnl = (
        (exit_price - pos.entry_price) if pos.direction == "BUY"
        else (pos.entry_price - exit_price)
    ) / pv
    _log_close(pos, reason, exit_price, pnl)
    subj, body = _email_close(pos, reason, exit_price)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)


def _set_all_be(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
    dry_run: bool,
) -> None:
    all_pos = (
        [states[p].position for p in pairs if states[p].position and not states[p].position.be_activated]
        + [pos for pos in managed.values() if not pos.be_activated]
    )
    for pos in all_pos:
        pos.stop_loss    = pos.entry_price
        pos.be_activated = True
        _log_be(pos)
        if live and pos.trade_id and (not pos.occult_stops or pos.sl_materialised):
            try:
                oanda.modify_trade_sl(pos.trade_id, pos.entry_price, pos.pair)
            except Exception as exc:
                log.warning("%s  BE failed: %s", pos.pair.upper(), exc)
        subj, body = _email_be(pos)
        if dry_run:
            log.info("[DRY-RUN] %s", subj)
        else:
            send_email(subj, body)


def _materialise_sl(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
) -> None:
    all_pos = (
        [states[p].position for p in pairs if states[p].position]
        + list(managed.values())
    )
    for pos in all_pos:
        if not pos.occult_stops or pos.sl_materialised or not live or not pos.trade_id:
            continue
        try:
            oanda.modify_trade_sl(pos.trade_id, pos.stop_loss, pos.pair)
            pos.sl_materialised = True
        except Exception as exc:
            log.error("%s  SL materialise failed: %s", pos.pair.upper(), exc)


def _materialise_tp(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
) -> None:
    all_pos = (
        [states[p].position for p in pairs if states[p].position]
        + list(managed.values())
    )
    for pos in all_pos:
        if not pos.occult_stops or pos.tp_materialised or not live or not pos.trade_id:
            continue
        try:
            oanda.modify_trade_tp(pos.trade_id, pos.take_profit, pos.pair)
            pos.tp_materialised = True
        except Exception as exc:
            log.error("%s  TP materialise failed: %s", pos.pair.upper(), exc)


def _apply_trade_defaults(
    tid:     str,
    managed: dict[str, tradelib.Position],
    live:    bool,
) -> None:
    """Push the daemon-calculated SL and TP for a managed trade to the broker."""
    pos = managed.get(str(tid))
    if pos is None:
        log.warning("apply_defaults: trade %s not found in managed positions", tid)
        return
    pair = pos.pair
    if not live or not pos.trade_id:
        pos.sl_materialised = True
        pos.tp_materialised = True
        log.info("%s  [PAPER] defaults noted: SL=%.5f  TP=%.5f  [trade %s]",
                 pair.upper(), pos.stop_loss, pos.take_profit, tid)
        return
    try:
        oanda.modify_trade_sl(pos.trade_id, pos.stop_loss, pair)
        pos.sl_materialised = True
        log.info("%s  SL applied to broker: %.5f  [trade %s]", pair.upper(), pos.stop_loss, tid)
    except Exception as exc:
        log.error("%s  SL apply failed: %s", pair.upper(), exc)
    try:
        oanda.modify_trade_tp(pos.trade_id, pos.take_profit, pair)
        pos.tp_materialised = True
        log.info("%s  TP applied to broker: %.5f  [trade %s]", pair.upper(), pos.take_profit, tid)
    except Exception as exc:
        log.error("%s  TP apply failed: %s", pair.upper(), exc)


def _occult_sl(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
) -> None:
    """Remove broker-side SL orders; daemon will manage exits explicitly."""
    all_pos = (
        [states[p].position for p in pairs if states[p].position]
        + list(managed.values())
    )
    for pos in all_pos:
        if not live or not pos.trade_id:
            continue
        try:
            oanda.cancel_trade_sl(pos.trade_id)
            pos.sl_materialised = False
            pos.occult_stops = True
            log.info("%s  SL occulted — broker order removed  [trade %s]",
                     pos.pair.upper(), pos.trade_id)
        except Exception as exc:
            log.error("%s  SL occult failed: %s", pos.pair.upper(), exc)


def _occult_tp(
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
    live:    bool,
) -> None:
    """Remove broker-side TP orders; daemon will manage exits explicitly."""
    all_pos = (
        [states[p].position for p in pairs if states[p].position]
        + list(managed.values())
    )
    for pos in all_pos:
        if not live or not pos.trade_id:
            continue
        try:
            oanda.cancel_trade_tp(pos.trade_id)
            pos.tp_materialised = False
            pos.occult_stops = True
            log.info("%s  TP occulted — broker order removed  [trade %s]",
                     pos.pair.upper(), pos.trade_id)
        except Exception as exc:
            log.error("%s  TP occult failed: %s", pos.pair.upper(), exc)


# ── Control server ────────────────────────────────────────────────────────────

def _ctrl_status(
    ctrl:    ControlState,
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
) -> str:
    now   = datetime.now(timezone.utc)
    lines = ["=== FX Trader (v2) ==="]
    lines.append(f"Entries: {'PAUSED' if ctrl.pause_entry else 'active'}  |  "
                 f"Exits: {'PAUSED' if ctrl.pause_exit else 'active'}  |  "
                 f"Drawdown: {ctrl.session_loss_pct:.1f}% {'[HALTED]' if ctrl.drawdown_halt else ''}")
    lines.append("")
    lines.append("-- Automated --")
    for pair in pairs:
        st = states[pair]
        if st.position:
            pos = st.position
            be  = "on" if pos.be_activated else "off"
            lines.append(
                f"  {pair.upper():<6}  {pos.direction}  "
                f"entry={pos.entry_price:.5f}  SL={pos.stop_loss:.5f}  "
                f"TP={pos.take_profit:.5f}  BE={be}"
            )
        elif st.cooldown_until and now < st.cooldown_until:
            lines.append(
                f"  {pair.upper():<6}  [cooldown → {st.cooldown_until.strftime('%H:%M UTC')}]"
            )
        else:
            lines.append(f"  {pair.upper():<6}  [no position]")

    if managed:
        lines.append("")
        lines.append("-- Discretionary --")
        for tid, pos in managed.items():
            be = "on" if pos.be_activated else "off"
            lines.append(
                f"  {pos.pair.upper():<6}  {pos.direction}  id={tid}  "
                f"entry={pos.entry_price:.5f}  SL={pos.stop_loss:.5f}  "
                f"TP={pos.take_profit:.5f}  BE={be}"
            )
    return "\n".join(lines)


def _handle_ctrl_cmd(
    cmd:     str,
    ctrl:    ControlState,
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
) -> str:
    parts = cmd.strip().split()
    if not parts:
        return ""
    verb = parts[0].lower()

    if verb == "pause":
        ctrl.pause_entry = ctrl.pause_exit = True
        return "Paused — entries and exits both suspended."
    if verb == "resume":
        ctrl.pause_entry = ctrl.pause_exit = False
        return "Resumed — entries and exits both active."
    if verb == "pause_entry":
        ctrl.pause_entry = True
        return "Entry paused."
    if verb == "resume_entry":
        ctrl.pause_entry = False
        return "Entry resumed."
    if verb == "resume_drawdown":
        ctrl.drawdown_halt    = False
        ctrl.session_loss_pct = 0.0
        return "Drawdown circuit breaker cleared — entries re-enabled."
    if verb == "pause_exit":
        ctrl.pause_exit = True
        return "Exit paused."
    if verb == "resume_exit":
        ctrl.pause_exit = False
        return "Exit resumed."

    if verb == "register":
        if len(parts) != 2:
            return "Usage: register <trade_id>"
        ctrl.pending_registers.append(parts[1])
        ctrl.wake_event.set()
        return f"Register queued for trade {parts[1]}."

    if verb == "stoploss":
        if len(parts) != 3:
            return "Usage: stoploss <trade_id> <sl>"
        try:
            ctrl.pending_sl_updates.append((parts[1], float(parts[2])))
            ctrl.wake_event.set()
            return f"SL update queued for trade {parts[1]}."
        except ValueError:
            return "SL must be a numeric price."

    if verb == "takeprofit":
        if len(parts) != 3:
            return "Usage: takeprofit <trade_id> <tp>"
        try:
            ctrl.pending_tp_updates.append((parts[1], float(parts[2])))
            ctrl.wake_event.set()
            return f"TP update queued for trade {parts[1]}."
        except ValueError:
            return "TP must be a numeric price."

    if verb == "deregister":
        if len(parts) != 2:
            return "Usage: deregister <trade_id>"
        ctrl.pending_deregisters.append(parts[1])
        ctrl.wake_event.set()
        return f"Deregister queued for trade {parts[1]}."

    if verb == "close":
        if len(parts) == 2:
            ctrl.pending_close_one.append(parts[1])
        else:
            ctrl.pending_close_all = True
        ctrl.wake_event.set()
        return "Close queued."

    if verb == "close_all":
        ctrl.pending_close_all = True
        ctrl.wake_event.set()
        return "Close-all queued."

    if verb in ("be", "breakeven"):
        ctrl.pending_be = True
        ctrl.wake_event.set()
        return "Breakeven queued."

    if verb == "materialise_sl":
        ctrl.pending_materialise_sl = True
        ctrl.wake_event.set()
        return "SL materialise queued."

    if verb == "materialise_tp":
        ctrl.pending_materialise_tp = True
        ctrl.wake_event.set()
        return "TP materialise queued."

    if verb == "apply_defaults":
        if len(parts) != 2:
            return "Usage: apply_defaults <trade_id>"
        ctrl.pending_apply_defaults.append(parts[1])
        ctrl.wake_event.set()
        return f"apply_defaults queued for trade {parts[1]}."

    if verb == "occult_sl":
        ctrl.pending_occult_sl = True
        ctrl.wake_event.set()
        return "SL occult queued."

    if verb == "occult_tp":
        ctrl.pending_occult_tp = True
        ctrl.wake_event.set()
        return "TP occult queued."

    if verb == "status":
        return _ctrl_status(ctrl, pairs, states, managed)

    if verb == "trades":
        try:
            open_trades = oanda.get_open_trades()
        except Exception as exc:
            return f"Could not fetch open trades: {exc}"
        if not open_trades:
            return "No open trades on OANDA."
        managed_ids = set(managed.keys())
        lines = [f"=== Open OANDA Trades ({len(open_trades)}) ==="]
        for t in open_trades:
            tid   = str(t.get("id", "?"))
            units = int(t.get("currentUnits", 0))
            tag   = "  [managed]" if tid in managed_ids else ""
            sl_o  = t.get("stopLossOrder") or {}
            tp_o  = t.get("takeProfitOrder") or {}
            sl_str = f"{float(sl_o['price']):.5f}" if sl_o.get("price") else "none"
            tp_str = f"{float(tp_o['price']):.5f}" if tp_o.get("price") else "none"
            lines.append(
                f"  id={tid}  {t.get('instrument')}  "
                f"{'BUY' if units > 0 else 'SELL'}  "
                f"entry={float(t.get('price', 0)):.5f}  "
                f"SL={sl_str}  TP={tp_str}"
                f"{tag}"
            )
        return "\n".join(lines)

    if verb in ("help", "?", ""):
        return (
            "Commands:\n"
            "  status                     Show status and open positions\n"
            "  pause / resume             Pause/resume entries and exits\n"
            "  pause_entry / resume_entry Pause/resume new entries only\n"
            "  pause_exit / resume_exit   Pause/resume automatic exits only\n"
            "  register <id>              Register an open OANDA trade for management\n"
            "  stoploss <id> <sl>         Override SL for a discretionary trade\n"
            "  takeprofit <id> <tp>       Override TP for a discretionary trade\n"
            "  deregister <id>            Stop managing a trade (no close)\n"
            "  close [<id>]               Close one or all positions\n"
            "  be                         Move all SLs to breakeven\n"
            "  materialise_sl             Place broker SL orders (occult mode)\n"
            "  materialise_tp             Place broker TP orders (occult mode)\n"
            "  apply_defaults <id>        Push calculated SL/TP to broker for a trade\n"
            "  occult_sl                  Remove broker SL orders (daemon manages)\n"
            "  occult_tp                  Remove broker TP orders (daemon manages)\n"
            "  trades                     List all open OANDA trades\n"
            "  help                       Show this help"
        )

    return f"Unknown command: '{verb}' — type 'help'."


def _start_control_server(
    ctrl:    ControlState,
    pairs:   list[str],
    states:  dict[str, PairState],
    managed: dict[str, tradelib.Position],
) -> None:
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", CONTROL_PORT))
    srv.listen(8)
    srv.settimeout(1.0)
    log.info("Control server on port %d", CONTROL_PORT)

    def _handle(conn: "_socket.socket") -> None:
        conn.sendall(b"FX Trader v2  |  help=commands  quit=disconnect\r\n\r\n> ")
        f = conn.makefile("rb")
        while True:
            raw = f.readline(256)
            if not raw:
                break
            cmd = bytes(b for b in raw if 32 <= b < 127).decode().strip()
            if not cmd:
                conn.sendall(b"> ")
                continue
            if cmd.lower() in ("quit", "exit", "q"):
                conn.sendall(b"Bye.\r\n")
                break
            with _STATE_LOCK:
                resp = _handle_ctrl_cmd(cmd, ctrl, pairs, states, managed)
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
                _handle(conn)
            except Exception as exc:
                log.debug("Control connection error: %s", exc)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    threading.Thread(target=_server, daemon=True, name="fx-ctrl").start()


# ── Startup data initialisation ───────────────────────────────────────────────

def _startup_init_data(pairs: list[str]) -> dict[str, PairState]:
    """Pre-warm OHLCV caches from parquet/OANDA for all pairs before trade state is restored."""
    states: dict[str, PairState] = {p: PairState() for p in pairs}
    for i, pair in enumerate(pairs, 1):
        log.info("  [%d/%d] %s — loading market data …", i, len(pairs), pair.upper())
        try:
            states[pair] = refresh_data(pair, states[pair])
        except Exception as exc:
            log.warning("  [%d/%d] %s — data init failed: %s", i, len(pairs), pair.upper(), exc)
    return states


# ── Main daemon loop ──────────────────────────────────────────────────────────

def daemon_loop(
    pairs:        list[str],
    dry_run:      bool,
    live:         bool,
    occult_stops: bool,
) -> None:
    """
    Main loop.  Polls every POLL_INTERVAL_SECS (60 s) unconditionally so that
    each new M1 bar is evaluated as soon as it is available.
    """
    managed: dict[str, tradelib.Position]  = {}
    ctrl = ControlState()

    # ── [1/4] Initialise market data ─────────────────────────────────────────
    log.info("Startup [1/4] — initialising market data (%d pair(s)) …", len(pairs))
    states = _startup_init_data(pairs)
    log.info("Startup [1/4] — market data ready")

    # ── [2/4] Restore open positions ─────────────────────────────────────────
    log.info("Startup [2/4] — loading trade state …")
    saved = _load_state()
    auto_count = 0
    disc_count = 0

    for pair, rec in saved["automated"].items():
        if pair in states:
            pos = _pos_from_record(rec, occult_stops)
            states[pair].position = pos
            log.info("  Restored [auto] %s %s @ %.5f", pair.upper(), pos.direction, pos.entry_price)
            auto_count += 1

    for tid, rec in saved["discretionary"].items():
        try:
            pos = _pos_from_record(rec, occult_stops)
            pos.trade_id = tid
            managed[tid] = pos
            log.info("  Restored [disc] %s %s id=%s @ %.5f",
                     pos.pair.upper(), pos.direction, tid, pos.entry_price)
            disc_count += 1
        except Exception as exc:
            log.warning("  Could not restore trade %s: %s", tid, exc)

    for pair, pips in saved["month_pips"].items():
        if pair in states:
            states[pair].month_pips = pips

    # Also restore from tradelog (legacy automated positions)
    try:
        legacy = tradelog.load_state()
        for symbol, data in legacy.items():
            pair_key = symbol.lower().replace("-", "")
            if pair_key in states and states[pair_key].position is None:
                pos_data = data.get("position")
                if pos_data:
                    known = tradelib.Position.__dataclass_fields__.keys()
                    pos_data.setdefault("trade_type", "automated")
                    pos = tradelib.Position(**{k: v for k, v in pos_data.items() if k in known})
                    pos.occult_stops = occult_stops
                    states[pair_key].position = pos
                    log.info("  Restored from tradelog: %s %s @ %.5f",
                             pair_key.upper(), pos.direction, pos.entry_price)
                    auto_count += 1
    except Exception as exc:
        log.debug("tradelog restore failed: %s", exc)

    if auto_count + disc_count == 0:
        log.info("Startup [2/4] — no open positions to restore")
    else:
        log.info("Startup [2/4] — restored %d automated, %d discretionary", auto_count, disc_count)

    auto_restored = [states[p].position for p in pairs if states[p].position]
    disc_restored = list(managed.values())

    # ── [3/4] Start control server ────────────────────────────────────────────
    log.info("Startup [3/4] — starting control server on port %d …", CONTROL_PORT)
    _start_control_server(ctrl, pairs, states, managed)

    # ── [4/4] Ready ───────────────────────────────────────────────────────────
    log.info(
        "Startup [4/4] — daemon ready: %d pair(s) %s  [%s]%s",
        len(pairs), ", ".join(p.upper() for p in pairs),
        "LIVE" if live else "PAPER",
        "  [DRY-RUN]" if dry_run else "",
    )

    subj, body = _email_startup(pairs, auto_restored, disc_restored, live, occult_stops)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    last_summary_slot: Optional[tuple] = None
    current_month: int  = datetime.now(timezone.utc).month
    current_date:  date = datetime.now(timezone.utc).date()
    weekend_close_done: Optional[int]  = None

    while True:
        ctrl.wake_event.wait(timeout=float(POLL_INTERVAL_SECS))
        ctrl.wake_event.clear()

        now     = datetime.now(timezone.utc)
        today   = now.date()
        weekday = now.weekday()

        # ── Process pending control commands ──────────────────────────────────
        with _STATE_LOCK:
            if ctrl.pending_close_all:
                ctrl.pending_close_all = False
                _close_all(pairs, states, managed, live, dry_run)

            if ctrl.pending_be:
                ctrl.pending_be = False
                _set_all_be(pairs, states, managed, live, dry_run)

            if ctrl.pending_materialise_sl:
                ctrl.pending_materialise_sl = False
                _materialise_sl(pairs, states, managed, live)

            if ctrl.pending_materialise_tp:
                ctrl.pending_materialise_tp = False
                _materialise_tp(pairs, states, managed, live)

            if ctrl.pending_occult_sl:
                ctrl.pending_occult_sl = False
                _occult_sl(pairs, states, managed, live)

            if ctrl.pending_occult_tp:
                ctrl.pending_occult_tp = False
                _occult_tp(pairs, states, managed, live)

            while ctrl.pending_apply_defaults:
                tid = ctrl.pending_apply_defaults.pop(0)
                _apply_trade_defaults(tid, managed, live)

            while ctrl.pending_close_one:
                tid = ctrl.pending_close_one.pop(0)
                pos = managed.pop(tid, None)
                if pos is None:
                    # Check automated positions
                    for pair in pairs:
                        if states[pair].position and str(states[pair].position.trade_id) == str(tid):
                            pos = states[pair].position
                            states[pair].position = None
                            break
                if pos:
                    _close_single(pos, live, dry_run, "close_manual")
                else:
                    log.warning("close: trade %s not found", tid)

            while ctrl.pending_registers:
                tid = ctrl.pending_registers.pop(0)
                if tid in managed:
                    continue
                pos, err = _register_trade(tid, occult_stops, live)
                if err:
                    log.error("Register failed for %s: %s", tid, err)
                else:
                    managed[tid] = pos
                    _log_open(pos)
                    log.info("Registered [disc] %s %s @ %.5f  SL=%.5f  TP=%.5f",
                             pos.pair.upper(), pos.direction, pos.entry_price,
                             pos.stop_loss, pos.take_profit)
                    subj, body = _email_open(pos)
                    if dry_run:
                        log.info("[DRY-RUN] %s", subj)
                    else:
                        send_email(subj, body)

            while ctrl.pending_sl_updates:
                tid, new_sl = ctrl.pending_sl_updates.pop(0)
                pos = managed.get(tid)
                if pos:
                    old_sl, pos.stop_loss = pos.stop_loss, new_sl
                    log.info("%s  SL %.5f → %.5f  [trade %s]", pos.pair.upper(), old_sl, new_sl, tid)
                    if live and pos.trade_id and (not pos.occult_stops or pos.sl_materialised):
                        try:
                            oanda.modify_trade_sl(pos.trade_id, new_sl, pos.pair)
                        except Exception as exc:
                            log.warning("SL update failed: %s", exc)

            while ctrl.pending_tp_updates:
                tid, new_tp = ctrl.pending_tp_updates.pop(0)
                pos = managed.get(tid)
                if pos:
                    old_tp, pos.take_profit, pos.original_tp = pos.take_profit, new_tp, new_tp
                    log.info("%s  TP %.5f → %.5f  [trade %s]", pos.pair.upper(), old_tp, new_tp, tid)
                    if live and pos.trade_id and (not pos.occult_stops or pos.tp_materialised):
                        try:
                            oanda.modify_trade_tp(pos.trade_id, new_tp, pos.pair)
                        except Exception as exc:
                            log.warning("TP update failed: %s", exc)

            while ctrl.pending_deregisters:
                tid = ctrl.pending_deregisters.pop(0)
                pos = managed.pop(tid, None)
                if pos:
                    _log_append({"event": "deregister", "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "trade_id": tid, "pair": pos.pair})
                    log.info("%s  deregistered trade %s — no longer managed", pos.pair.upper(), tid)

        # ── Weekend handling ──────────────────────────────────────────────────
        if weekday in (5, 6):
            log.debug("Weekend — skipping pair ticks")
            continue

        if weekday == 4 and now.hour >= WEEKEND_CLOSE_HOUR:
            iso_week = today.isocalendar()[1]
            if weekend_close_done != iso_week:
                any_open_now = any(states[p].position for p in pairs) or bool(managed)
                if any_open_now:
                    log.info("Friday %02d:00 UTC — closing all for weekend", WEEKEND_CLOSE_HOUR)
                    _close_all(pairs, states, managed, live, dry_run, reason="close_weekend")
                weekend_close_done = iso_week

        # ── Live: prune discretionary trades no longer open on OANDA ─────────
        if live and managed:
            try:
                open_ids = {str(t["id"]) for t in oanda.get_open_trades()}
                for tid in list(managed.keys()):
                    if tid not in open_ids:
                        pos = managed.pop(tid)
                        log.warning(
                            "%s  trade %s no longer on OANDA — auto-deregistered",
                            pos.pair.upper(), tid,
                        )
                        _log_append({
                            "event": "deregister", "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "trade_id": tid, "pair": pos.pair,
                        })
            except Exception as exc:
                log.debug("Open-trade verification failed: %s", exc)

        # ── Per-pair ticks ────────────────────────────────────────────────────
        for pair in pairs:
            try:
                states[pair] = tick(pair, states[pair], dry_run, live,
                                    occult_stops, managed, ctrl)
            except Exception as exc:
                log.exception("%s  tick error: %s", pair.upper(), exc)

        # ── Daily session reset ───────────────────────────────────────────────
        today_utc = now.date()
        if today_utc != current_date:
            current_date = today_utc
            ctrl.session_loss_pct = 0.0
            ctrl.drawdown_halt    = False
            log.info("New trading day — session drawdown reset")

        # ── Monthly pip reset ─────────────────────────────────────────────────
        if now.month != current_month:
            current_month = now.month
            for st in states.values():
                st.month_pips = 0.0
            log.info("New calendar month — pip totals reset")

        # ── Twice-daily summary ───────────────────────────────────────────────
        slot = (
            (today, "PM") if now.hour >= 20 else
            (today, "AM") if now.hour >= 8  else
            None
        )
        if slot and last_summary_slot != slot:
            last_summary_slot = slot
            total_pips = sum(st.month_pips for st in states.values())
            subj, body = _email_summary(pairs, states, managed, total_pips)
            if dry_run:
                log.info("[DRY-RUN] %s", subj)
            else:
                send_email(subj, body)


# ── Entry point ───────────────────────────────────────────────────────────────

def _handle_signal(sig, _frame) -> None:
    log.info("Signal %d received — shutting down", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    parser = argparse.ArgumentParser(
        description="FX Trader Daemon v2 — unified automated + discretionary trade management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pair", choices=list(PAIR_INDICATORS.keys()), nargs="+", metavar="PAIR",
        help="Pairs to monitor (default: FX_PAIRS env var or all four)",
    )
    parser.add_argument(
        "--live", action="store_true",
        default=os.getenv("FX_LIVE", "false").lower() == "true",
        help="Enable live OANDA order execution",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        default=os.getenv("FX_DRY_RUN", "false").lower() == "true",
        help="Log events only — no emails or broker calls",
    )
    parser.add_argument(
        "--occult-stops", action="store_true",
        default=FX_OCCULT_STOPS,
        help="Do not send SL/TP to broker; daemon closes explicitly",
    )
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None, metavar="LEVEL",
    )
    args = parser.parse_args()

    logsetup.configure("fxtrader", level=args.log_level)

    if args.pair:
        selected = args.pair
    elif FX_PAIRS_ENV:
        selected = [p.strip().lower() for p in FX_PAIRS_ENV.split(",") if p.strip()]
        unknown  = [p for p in selected if p not in PAIR_INDICATORS]
        if unknown:
            parser.error(f"Unknown pair(s) in FX_PAIRS: {', '.join(unknown)}")
    else:
        selected = list(PAIR_INDICATORS.keys())

    daemon_loop(selected, args.dry_run, args.live, args.occult_stops)
