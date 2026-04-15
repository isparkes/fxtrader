"""
Persistent trade log for the FX daemon.

Every OPEN / BE / CLOSE event is appended as a JSON line to ``trades.jsonl``.
On restart, ``load_state()`` replays the file and returns any open positions
together with the month-to-date pip total so the daemon can resume seamlessly.

Log format (one JSON object per line):
  {"event": "open",  "ts": "...", "pair": "eurusd", "symbol": "EURUSD=X",
   "direction": "BUY", "entry": 1.08500, "sl": 1.08300, "tp": 1.08900,
   "atr": 0.00120, "risk_pips": 20.0, "reward_pips": 40.0, "rr": 2.0,
   "opened_at": "2024-01-01T10:00:00 UTC", "basis": "..."}

  {"event": "be",    "ts": "...", "pair": "eurusd", "symbol": "EURUSD=X",
   "opened_at": "...", "sl": 1.08500}

  {"event": "close", "ts": "...", "pair": "eurusd", "symbol": "EURUSD=X",
   "opened_at": "...", "direction": "BUY", "entry": 1.08500, "exit": 1.08900,
   "pnl_pips": 40.0, "reason": "close_tp"}
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("fxtrader.tradelog")

TRADE_LOG_FILE = Path("trades.jsonl")


# ── Writers ───────────────────────────────────────────────────────────────────

def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(record: dict) -> None:
    with TRADE_LOG_FILE.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def log_open(pos) -> None:
    """Append an OPEN event for a newly entered position."""
    _append({
        "event":       "open",
        "ts":          _now_ts(),
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


def log_be(pos) -> None:
    """Append a BE (stop-to-breakeven) event for an open position."""
    _append({
        "event":     "be",
        "ts":        _now_ts(),
        "pair":      pos.pair,
        "symbol":    pos.symbol,
        "opened_at": pos.opened_at,
        "sl":        pos.entry_price,   # new stop = entry (breakeven)
    })


def log_close(pos, reason: str, exit_price: float, pnl_pips: float) -> None:
    """Append a CLOSE event (TP or SL hit) for a position."""
    _append({
        "event":     "close",
        "ts":        _now_ts(),
        "pair":      pos.pair,
        "symbol":    pos.symbol,
        "opened_at": pos.opened_at,
        "direction": pos.direction,
        "entry":     pos.entry_price,
        "exit":      exit_price,
        "pnl_pips":  round(pnl_pips, 1),
        "reason":    reason,
    })


# ── Reader ────────────────────────────────────────────────────────────────────

def load_state() -> dict[str, dict]:
    """
    Replay ``trades.jsonl`` and reconstruct daemon state.

    Returns a dict keyed by *symbol* (e.g. ``"EURUSD=X"``) containing:

        {
            "position": dict | None,   # Position constructor kwargs, or None
            "month_pips": float,       # closed-trade pips in the current month
        }

    ``position`` is a plain dict — the caller is responsible for constructing
    the ``Position`` dataclass from it (avoids a circular import).  The ``sl``
    field already reflects whether breakeven was activated.
    """
    if not TRADE_LOG_FILE.exists():
        return {}

    # (pair, opened_at) is the unique key for a trade leg
    opens:  dict[tuple, dict] = {}
    be_set: set[tuple]        = set()
    closed: set[tuple]        = set()
    # symbol -> pips accumulated in the current calendar month
    month_pips: dict[str, float] = {}

    now           = datetime.now(timezone.utc)
    current_month = now.month
    current_year  = now.year

    with TRADE_LOG_FILE.open() as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                log.warning("tradelog line %d — malformed JSON (skipped): %s", lineno, line[:80])
                continue

            event     = rec.get("event")
            pair      = rec.get("pair")
            opened_at = rec.get("opened_at")
            key       = (pair, opened_at)

            if event == "open":
                opens[key] = rec

            elif event == "be":
                be_set.add(key)

            elif event == "close":
                closed.add(key)
                # Accumulate month-to-date pips for the current calendar month
                try:
                    ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                    if ts.month == current_month and ts.year == current_year:
                        sym = rec.get("symbol", "")
                        month_pips[sym] = month_pips.get(sym, 0.0) + rec.get("pnl_pips", 0.0)
                except (KeyError, ValueError):
                    pass

    # Build result — only unclosed open trades
    result: dict[str, dict] = {}

    for key, rec in opens.items():
        if key in closed:
            continue

        symbol    = rec["symbol"]
        be_active = key in be_set

        position_data = {
            "pair":         rec["pair"],
            "symbol":       symbol,
            "direction":    rec["direction"],
            "entry_price":  rec["entry"],
            # If breakeven was activated the SL is now at entry; otherwise the
            # original SL is the last known value (a further trail update would
            # need its own log event type — currently only BE is tracked).
            "stop_loss":    rec["entry"] if be_active else rec["sl"],
            "take_profit":  rec["tp"],
            "atr":          rec["atr"],
            "risk_pips":    rec["risk_pips"],
            "reward_pips":  rec["reward_pips"],
            "rr_ratio":     rec["rr"],
            "opened_at":    rec["opened_at"],
            "basis":        rec["basis"],
            "be_activated": be_active,
        }

        if symbol not in result:
            result[symbol] = {"position": None, "month_pips": 0.0}
        result[symbol]["position"] = position_data

        log.info(
            "Restored open position: %s %s @ %.5f  BE=%s",
            rec["pair"].upper(), rec["direction"], rec["entry"],
            "active" if be_active else "pending",
        )

    # Merge month pips — symbols with only closed trades (no live position)
    for sym, pips in month_pips.items():
        if sym not in result:
            result[sym] = {"position": None, "month_pips": 0.0}
        result[sym]["month_pips"] += pips

    return result
