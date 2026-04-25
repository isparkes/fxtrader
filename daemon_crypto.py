"""
Crypto Scalper Daemon
=====================
Monitors BTCUSD continuously, caches market data incrementally, executes
trades on Binance, and sends email alerts on three events:

  OPEN   — a new scalp signal fires (entry, SL, TP details in $)
  BE     — stop-loss moved to breakeven (OCO replaced on Binance)
  CLOSE  — trade closed at TP or SL (Binance orders cancelled, P&L emailed)

For FX pairs (EURUSD, GBPUSD, USDJPY, AUDUSD) see daemon_fx.py.

Configuration
-------------
Copy .env.example to .env and set:
  BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET
  CRYPTO_RISK_USD, CRYPTO_TRADE_SIZE_USD
  SMTP_* / MAIL_* for email alerts.

Usage
-----
    python daemon_crypto.py                    # monitor BTCUSD, poll every 5 min
    python daemon_crypto.py --interval 60      # poll every 60 s (useful for testing)
    python daemon_crypto.py --dry-run          # log events, skip email and Binance orders

Running as a background process (macOS / Linux)
------------------------------------------------
    nohup python daemon_crypto.py >> cryptotrader.log 2>&1 &
    echo $! > cryptotrader.pid
    kill $(cat cryptotrader.pid)
"""

import os
import sys
import signal
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

import indicator_btcusd
from mailer import send_email
import tradelog

load_dotenv()

try:
    from binance.client import Client as BinanceClient
    from binance.exceptions import BinanceAPIException
    _BINANCE_LIB = True
except ImportError:
    _BINANCE_LIB = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("cryptotrader.daemon")

PAIRS: dict[str, str] = {
    "btcusd": "BTC-USD",
}

PAIR_INDICATORS = {
    "btcusd": indicator_btcusd,
}

# ── Constants ─────────────────────────────────────────────────────────────────
TRAIL_ACTIVATE_FRAC = 0.80
COOLDOWN_MINS       = 30

H1_MAX_BARS = 300
M5_MAX_BARS = 600

H1_LOOKBACK = pd.Timedelta(hours=3)
M5_LOOKBACK = pd.Timedelta(minutes=15)

# Trade sizing from .env (can be overridden without code changes)
CRYPTO_RISK_USD       = float(os.getenv("CRYPTO_RISK_USD", "50"))
CRYPTO_TRADE_SIZE_USD = float(os.getenv("CRYPTO_TRADE_SIZE_USD", "1000"))

# Binance symbol mapping (Yahoo Finance key → Binance symbol)
BINANCE_SYMBOL_MAP = {"btcusd": "BTCUSDT"}

# BTCUSDT precision constants (qty step 0.00001 BTC, price tick $0.01)
_QTY_STEP  = 0.00001
_QTY_PREC  = 5
_PRICE_DEC = 2

# Module-level Binance client — initialised in daemon_loop()
_binance_client: Optional["BinanceClient"] = None


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Position:
    pair:              str
    symbol:            str
    direction:         str
    entry_price:       float
    stop_loss:         float
    take_profit:       float
    atr:               float
    risk_pips:         float
    reward_pips:       float
    rr_ratio:          float
    opened_at:         str
    basis:             str
    be_activated:      bool         = False
    qty:               float        = 0.0
    entry_order_id:    Optional[str] = field(default=None)
    oco_order_list_id: Optional[str] = field(default=None)


@dataclass
class PairState:
    cache_h1:        Optional[pd.DataFrame] = None
    cache_5m:        Optional[pd.DataFrame] = None
    position:        Optional[Position]     = None
    cooldown_until:  Optional[datetime]     = None
    last_signal_bar: Optional[str]          = None
    month_pips:      float                  = 0.0


# ── Binance helpers ───────────────────────────────────────────────────────────

def _init_binance() -> Optional["BinanceClient"]:
    if not _BINANCE_LIB:
        log.warning("python-binance not installed — order execution disabled")
        return None
    api_key    = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    testnet    = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
    if not api_key or not api_secret:
        log.warning("BINANCE_API_KEY/BINANCE_API_SECRET not set — order execution disabled")
        return None
    try:
        client = BinanceClient(api_key, api_secret, testnet=testnet)
        client.ping()
        log.info("Binance client ready (testnet=%s)", testnet)
        return client
    except Exception as exc:
        log.error("Binance init failed: %s — order execution disabled", exc)
        return None


def _calc_qty(entry: float, stop_loss: float, risk_usd: float, max_notional: float) -> float:
    sl_dist = abs(entry - stop_loss)
    if sl_dist <= 0:
        return 0.0
    qty     = risk_usd / sl_dist
    max_qty = max_notional / entry
    return min(qty, max_qty)


def _round_qty(qty: float) -> float:
    return round(round(qty / _QTY_STEP) * _QTY_STEP, _QTY_PREC)


def _round_price(price: float) -> float:
    return round(price, _PRICE_DEC)


def _place_entry_order(client, pair: str, direction: str, qty: float) -> Optional[str]:
    sym = BINANCE_SYMBOL_MAP.get(pair)
    if not sym:
        return None
    try:
        if direction == "BUY":
            order = client.order_market_buy(symbol=sym, quantity=qty)
        else:
            order = client.order_market_sell(symbol=sym, quantity=qty)
        log.info("Binance market %s: %s qty=%.5f orderId=%s",
                 direction, pair.upper(), qty, order["orderId"])
        return str(order["orderId"])
    except BinanceAPIException as exc:
        log.error("Binance entry order failed: %s", exc)
        return None


def _place_oco_exit(client, pair: str, direction: str,
                    qty: float, tp: float, sl: float) -> Optional[str]:
    sym = BINANCE_SYMBOL_MAP.get(pair)
    if not sym:
        return None
    tp_p = _round_price(tp)
    sl_p = _round_price(sl)
    if direction == "BUY":
        exit_side    = "SELL"
        sl_limit_p   = _round_price(sl * 0.998)   # 0.2% slippage allowance
    else:
        exit_side    = "BUY"
        sl_limit_p   = _round_price(sl * 1.002)
    try:
        order = client.create_oco_order(
            symbol=sym,
            side=exit_side,
            quantity=qty,
            price=str(tp_p),
            stopPrice=str(sl_p),
            stopLimitPrice=str(sl_limit_p),
            stopLimitTimeInForce="GTC",
        )
        list_id = str(order["orderListId"])
        log.info("Binance OCO exit: %s qty=%.5f TP=%.2f SL=%.2f listId=%s",
                 pair.upper(), qty, tp_p, sl_p, list_id)
        return list_id
    except BinanceAPIException as exc:
        log.error("Binance OCO order failed: %s", exc)
        return None


def _cancel_oco(client, pair: str, order_list_id: str) -> None:
    sym = BINANCE_SYMBOL_MAP.get(pair)
    if not sym or not order_list_id:
        return
    try:
        client.cancel_order_list(symbol=sym, orderListId=int(order_list_id))
        log.info("Binance OCO %s cancelled (%s)", order_list_id, pair.upper())
    except BinanceAPIException as exc:
        log.warning("Binance OCO cancel (may already be filled): %s", exc)


def _cancel_all_open_orders(client, pair: str) -> None:
    sym = BINANCE_SYMBOL_MAP.get(pair)
    if not sym:
        return
    try:
        result = client.cancel_open_orders(symbol=sym)
        if result:
            log.info("Binance: cancelled %d open order(s) for %s", len(result), sym)
    except BinanceAPIException as exc:
        log.warning("Binance cancel all orders: %s", exc)


# ── Data helpers ──────────────────────────────────────────────────────────────

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def _fetch_raw(symbol: str, interval: str, **kwargs) -> pd.DataFrame:
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
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined.tail(max_bars)


def refresh_data(symbol: str, state: PairState) -> PairState:
    if state.cache_h1 is None:
        log.info("Initial fetch for %s …", symbol)
        state.cache_h1 = _fetch_raw(symbol, "1h", period="7d")
        state.cache_5m = _fetch_raw(symbol, "5m", period="2d")
        log.info(
            "%s  cache seeded: %d × 1h bars, %d × 5m bars",
            symbol, len(state.cache_h1), len(state.cache_5m),
        )
        return state

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
    events = []
    high = float(bar["high"])
    low  = float(bar["low"])

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
        f"Entry ${pos.entry_price:.2f}"
    )
    lines = [
        f"Trade Opened : {pos.pair.upper()} {pos.direction}",
        f"Timestamp    : {pos.opened_at}",
        "",
        f"Entry        : ${pos.entry_price:.2f}",
        f"Stop Loss    : ${pos.stop_loss:.2f}  (${pos.risk_pips:.1f} risk/BTC)",
        f"Take Profit  : ${pos.take_profit:.2f}  (${pos.reward_pips:.1f} reward/BTC)",
        f"R:R          : 1 : {pos.rr_ratio:.2f}",
        f"ATR(14) 1h   : ${pos.atr:.2f}",
    ]
    if pos.qty > 0:
        notional    = pos.qty * pos.entry_price
        actual_risk = pos.qty * pos.risk_pips
        lines.extend([
            "",
            f"Size         : {pos.qty:.5f} BTC  (${notional:.2f} notional)",
            f"Risk         : ${actual_risk:.2f}",
        ])
    lines.extend([
        "",
        f"Basis: {pos.basis}",
    ])
    return subject, "\n".join(lines)


def _email_be(pos: Position) -> tuple[str, str]:
    subject = f"[{pos.pair.upper()}] {pos.direction} — Stop Moved to Breakeven"
    lines = [
        f"Breakeven triggered on {pos.pair.upper()} {pos.direction}",
        "",
        f"Entry        : ${pos.entry_price:.2f}",
        f"New SL       : ${pos.entry_price:.2f}  (breakeven — risk now zero)",
        f"TP still live: ${pos.take_profit:.2f}  (${pos.reward_pips:.1f} remaining)",
    ]
    if pos.qty > 0:
        lines.append(f"Size         : {pos.qty:.5f} BTC")
    return subject, "\n".join(lines)


def _email_close(pos: Position, event: str, exit_price: float) -> tuple[str, str]:
    pnl_per_btc = (
        (exit_price - pos.entry_price) if pos.direction == "BUY"
        else (pos.entry_price - exit_price)
    ) / PAIR_INDICATORS[pos.pair].pip_value(pos.pair)
    result = "WIN" if pnl_per_btc > 0 else "LOSS"
    reason = "Take Profit" if event == "close_tp" else "Stop Loss"
    sign   = "+" if pnl_per_btc >= 0 else ""

    if pos.qty > 0:
        actual_pnl = pnl_per_btc * pos.qty
        subject = (
            f"[{pos.pair.upper()}] {pos.direction} Closed — "
            f"{result} {sign}${actual_pnl:.2f}"
        )
    else:
        subject = (
            f"[{pos.pair.upper()}] {pos.direction} Closed — "
            f"{result} {sign}${pnl_per_btc:.2f}/BTC"
        )

    lines = [
        f"Trade Closed : {pos.pair.upper()} {pos.direction}",
        f"Exit Reason  : {reason} Hit",
        "",
        f"Entry        : ${pos.entry_price:.2f}",
        f"Exit         : ${exit_price:.2f}",
        f"P&L/BTC      : {sign}${pnl_per_btc:.2f}",
    ]
    if pos.qty > 0:
        actual_pnl = pnl_per_btc * pos.qty
        lines.extend([
            f"Size         : {pos.qty:.5f} BTC",
            f"Total P&L    : {sign}${actual_pnl:.2f}",
        ])
    lines.append(f"Result       : {result}")
    return subject, "\n".join(lines)


# ── Startup / summary emails ──────────────────────────────────────────────────

def _email_startup(
    pairs: list[tuple[str, str]],
    restored: list[Position],
) -> tuple[str, str]:
    subject = "[Crypto Trader] Daemon started"
    lines = [
        "Crypto Trader daemon has started successfully.",
        "",
        f"Monitoring {len(pairs)} pair(s): {', '.join(p.upper() for p, _ in pairs)}",
        f"Started at : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Risk/trade : ${CRYPTO_RISK_USD:.0f}  |  Max notional: ${CRYPTO_TRADE_SIZE_USD:.0f}",
        f"Binance    : {'connected' if _binance_client else 'not connected'}",
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
                f"    Entry       : ${pos.entry_price:.2f}",
                f"    Stop Loss   : ${pos.stop_loss:.2f}",
                f"    Take Profit : ${pos.take_profit:.2f}",
                f"    Breakeven   : {'activated' if pos.be_activated else 'pending'}",
            ]
    else:
        lines += ["", "No open positions restored from trade log."]
    return subject, "\n".join(lines)


def _email_daily_summary(
    pairs: list[tuple[str, str]],
    states: dict[str, PairState],
    month_dollars: float,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    subject = f"[Crypto Trader] Daily Summary — {now.strftime('%Y-%m-%d')}"

    sign = "+" if month_dollars >= 0 else ""
    lines = [
        f"Daily Status Summary — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Monitoring : {', '.join(p.upper() for p, _ in pairs)}",
        f"Month-to-date P&L : {sign}${month_dollars:.2f}  (resets each calendar month)",
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
                f"    Entry       : ${pos.entry_price:.2f}",
                f"    Stop Loss   : ${pos.stop_loss:.2f}",
                f"    Take Profit : ${pos.take_profit:.2f}",
                f"    R:R         : 1 : {pos.rr_ratio:.2f}",
                f"    Breakeven   : {'activated' if pos.be_activated else 'pending'}",
            ])
            if pos.qty > 0:
                lines.append(f"    Size        : {pos.qty:.5f} BTC")
    else:
        lines.append("Open Positions : None")

    in_cooldown = [
        f"{pair.upper()} (until {states[sym].cooldown_until.strftime('%H:%M UTC')})"
        for pair, sym in pairs
        if states[sym].cooldown_until and datetime.now(timezone.utc) < states[sym].cooldown_until
    ]
    if in_cooldown:
        lines.extend(["", "In Cooldown : " + ", ".join(in_cooldown)])

    return subject, "\n".join(lines)


# ── Core tick ─────────────────────────────────────────────────────────────────

def tick(pair: str, symbol: str, state: PairState, dry_run: bool) -> PairState:
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

    ind   = PAIR_INDICATORS[pair]
    df_h1 = ind.compute_h1_indicators(state.cache_h1.copy())
    df_5m = ind.compute_m5_indicators(state.cache_5m.copy())

    # ── Manage open position ──────────────────────────────────────────────────
    if state.position is not None:
        pos    = state.position
        latest = df_5m.iloc[-1]
        events = check_position_events(pos, latest)
        closed = False

        for event, price in events:
            if event == "be":
                log.info("%s  BE triggered — SL moved to %.2f", pair.upper(), pos.entry_price)
                # Replace OCO on Binance with new SL at breakeven
                if _binance_client and not dry_run and pos.oco_order_list_id and pos.qty > 0:
                    _cancel_oco(_binance_client, pos.pair, pos.oco_order_list_id)
                    pos.oco_order_list_id = _place_oco_exit(
                        _binance_client, pos.pair, pos.direction,
                        pos.qty, pos.take_profit, pos.entry_price,
                    )
                tradelog.log_be(pos)
                subj, body = _email_be(pos)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

            elif event in ("close_tp", "close_sl"):
                pnl = (
                    (price - pos.entry_price) if pos.direction == "BUY"
                    else (pos.entry_price - price)
                ) / PAIR_INDICATORS[pair].pip_value(pair)
                log.info(
                    "%s  CLOSE %s — %s @ %.2f  P&L $%.2f/BTC",
                    pair.upper(), pos.direction, event, price, pnl,
                )
                # Cancel any remaining Binance orders for this pair
                if _binance_client and not dry_run:
                    _cancel_all_open_orders(_binance_client, pair)
                tradelog.log_close(pos, event, price, pnl)
                subj, body = _email_close(pos, event, price)
                if dry_run:
                    log.info("[DRY-RUN] %s", subj)
                else:
                    send_email(subj, body)

                state.month_pips += pnl * (pos.qty if pos.qty > 0 else 1.0)

                if event == "close_sl":
                    state.cooldown_until = now + timedelta(minutes=COOLDOWN_MINS)
                    log.info("%s  cooldown until %s",
                             pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
                state.position = None
                closed = True
                break

        if not closed:
            log.debug(
                "%s  position open: entry=%.2f  SL=%.2f  BE=%s",
                pair.upper(), pos.entry_price, pos.stop_loss,
                "active" if pos.be_activated else "pending",
            )
        return state

    # ── Look for a new entry ──────────────────────────────────────────────────
    if state.cooldown_until and now < state.cooldown_until:
        log.debug("%s  in cooldown until %s",
                  pair.upper(), state.cooldown_until.strftime("%H:%M UTC"))
        return state

    h1_bias = ind.assess_h1_bias(df_h1)
    entry   = ind.find_m5_entry(df_5m, h1_bias["direction"])

    if h1_bias["direction"] == "FLAT":
        log.debug("%s  1h bias FLAT", pair.upper())
        return state

    if entry is None:
        log.debug("%s  %s bias, no 5m entry trigger", pair.upper(), h1_bias["direction"])
        return state

    if entry["bar_time"] == state.last_signal_bar:
        log.debug("%s  duplicate signal bar (%s) — skipped", pair.upper(), entry["bar_time"])
        return state

    signal = ind.build_signal(h1_bias, entry, symbol)
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

    # ── Execute on Binance ────────────────────────────────────────────────────
    if _binance_client:
        qty = _round_qty(_calc_qty(
            pos.entry_price, pos.stop_loss, CRYPTO_RISK_USD, CRYPTO_TRADE_SIZE_USD,
        ))
        if qty > 0:
            pos.qty = qty
            if not dry_run:
                pos.entry_order_id = _place_entry_order(
                    _binance_client, pair, pos.direction, qty,
                )
                if pos.entry_order_id:
                    pos.oco_order_list_id = _place_oco_exit(
                        _binance_client, pair, pos.direction,
                        qty, pos.take_profit, pos.stop_loss,
                    )

    log.info(
        "%s  OPEN %s @ %.2f  SL=%.2f  TP=%.2f  ($%.1f/$%.1f  R:R 1:%.2f)%s",
        pair.upper(), pos.direction, pos.entry_price,
        pos.stop_loss, pos.take_profit,
        pos.risk_pips, pos.reward_pips, pos.rr_ratio,
        f"  qty={pos.qty:.5f} BTC" if pos.qty > 0 else "",
    )
    tradelog.log_open(pos)

    subj, body = _email_open(pos)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    return state


# ── Daemon loop ───────────────────────────────────────────────────────────────

def daemon_loop(pairs: list[tuple[str, str]], interval: int, dry_run: bool) -> None:
    global _binance_client
    _binance_client = _init_binance()

    states: dict[str, PairState] = {sym: PairState() for _, sym in pairs}

    saved = tradelog.load_state()
    restored_positions: list[Position] = []

    for symbol, data in saved.items():
        if symbol not in states:
            log.warning("Trade log has symbol %s not in current pair list — skipped", symbol)
            continue

        states[symbol].month_pips = data["month_pips"]

        pos_data = data.get("position")
        if pos_data:
            # Filter to only known Position fields for backwards compatibility
            known = Position.__dataclass_fields__.keys()
            pos = Position(**{k: v for k, v in pos_data.items() if k in known})
            states[symbol].position = pos
            restored_positions.append(pos)

    if restored_positions:
        log.info(
            "Restored %d open position(s) from %s",
            len(restored_positions), tradelog.TRADE_LOG_FILE,
        )
    else:
        log.info("No open positions in trade log")

    log.info(
        "Daemon started — %d pair(s): %s — poll interval %ds%s",
        len(pairs),
        ", ".join(p.upper() for p, _ in pairs),
        interval,
        "  [DRY-RUN]" if dry_run else "",
    )

    subj, body = _email_startup(pairs, restored_positions)
    if dry_run:
        log.info("[DRY-RUN] %s", subj)
    else:
        send_email(subj, body)

    last_summary_slot: Optional[tuple] = None
    current_month: int = datetime.now(timezone.utc).month

    while True:
        for pair, symbol in pairs:
            try:
                states[symbol] = tick(pair, symbol, states[symbol], dry_run)
            except Exception as exc:
                log.exception("%s  unexpected error in tick: %s", pair.upper(), exc)

        now = datetime.now(timezone.utc)
        today = now.date()

        if now.month != current_month:
            current_month = now.month
            for state in states.values():
                state.month_pips = 0.0
            log.info("New calendar month — monthly P&L totals reset")

        if now.hour >= 20:
            slot = (today, "PM")
        elif now.hour >= 8:
            slot = (today, "AM")
        else:
            slot = None

        if slot and last_summary_slot != slot:
            last_summary_slot = slot
            total_month_dollars = sum(s.month_pips for s in states.values())
            log.info("Sending %s summary email", slot[1])
            subj, body = _email_daily_summary(pairs, states, total_month_dollars)
            if dry_run:
                log.info("[DRY-RUN] %s", subj)
            else:
                send_email(subj, body)

        time.sleep(interval)


# ── Entry point ───────────────────────────────────────────────────────────────

def _handle_signal(sig, _frame) -> None:
    log.info("Received signal %d — shutting down", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    parser = argparse.ArgumentParser(
        description="Crypto Scalper Daemon — trades on Binance, email alerts on OPEN/BE/CLOSE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pair",
        choices=list(PAIRS.keys()),
        help="Pair to monitor (default: all)",
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
        help="Log events, skip email and Binance order execution",
    )
    args = parser.parse_args()

    pairs_to_watch = (
        [(args.pair, PAIRS[args.pair])]
        if args.pair
        else list(PAIRS.items())
    )

    daemon_loop(pairs_to_watch, args.interval, args.dry_run)
