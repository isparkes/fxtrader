"""
Oanda REST API v20 client — practice (demo) account wrapper.

Targets the practice environment by default.  Set OANDA_ENV=live in .env
to switch to the live API.  All functions raise RuntimeError if credentials
are not configured and requests.HTTPError on non-2xx responses.

Required .env variables:
    OANDA_API_KEY    — personal access token from Oanda's API management page
    OANDA_ACCOUNT_ID — numeric account ID shown in the Oanda hub

Optional:
    OANDA_ENV        — "practice" (default) | "live"
"""

import os
import time as _time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

_ENV        = os.getenv("OANDA_ENV", "practice")
_API_KEY    = os.getenv("OANDA_API_KEY", "")
_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")

_BASE_URL = (
    "https://api-fxtrade.oanda.com"
    if _ENV == "live"
    else "https://api-fxpractice.oanda.com"
)

# Maps the internal pair keys used throughout the project to Oanda instrument names.
INSTRUMENTS: dict[str, str] = {
    "eurusd": "EUR_USD",
    "gbpusd": "GBP_USD",
    "usdjpy": "USD_JPY",
    "audusd": "AUD_USD",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }


def _require_config() -> None:
    if not _API_KEY or not _ACCOUNT_ID:
        raise RuntimeError(
            "OANDA_API_KEY and OANDA_ACCOUNT_ID must be set in .env"
        )


# ── Account ───────────────────────────────────────────────────────────────────

def get_account_summary() -> dict:
    """
    Return account balance, NAV, unrealised P&L, margin, and open trade count.

    Relevant keys in the returned dict:
        balance, NAV, unrealizedPL, marginUsed, marginAvailable, openTradeCount
    """
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/summary"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()["account"]


# ── Pricing ───────────────────────────────────────────────────────────────────

def get_price(pair: str) -> dict:
    """
    Return the current bid/ask spread for a pair.

    Args:
        pair: internal key, e.g. "eurusd"

    Returns:
        {"instrument": "EUR_USD", "bid": 1.08123, "ask": 1.08131}
    """
    _require_config()
    instrument = INSTRUMENTS[pair.lower()]
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/pricing"
    resp = requests.get(
        url,
        headers=_headers(),
        params={"instruments": instrument},
        timeout=10,
    )
    resp.raise_for_status()
    prices = resp.json()["prices"]
    if not prices:
        raise ValueError(f"No pricing data returned for {instrument}")
    p = prices[0]
    return {
        "instrument": p["instrument"],
        "bid": float(p["bids"][0]["price"]),
        "ask": float(p["asks"][0]["price"]),
    }


# ── Orders ────────────────────────────────────────────────────────────────────

def _fmt_price(pair: str, price: float) -> str:
    """Format a price with the correct decimal precision for the instrument."""
    decimals = 3 if "jpy" in pair.lower() else 5
    return f"{price:.{decimals}f}"


def place_market_order(
    pair: str,
    direction: str,
    units: int,
    stop_loss: float,
    take_profit: float,
    occult_stops: bool = False,
) -> dict:
    """
    Place a market order, optionally without broker-side SL/TP orders.

    Args:
        pair:         internal key, e.g. "eurusd"
        direction:    "BUY" or "SELL"
        units:        positive integer — sign is applied from direction
        stop_loss:    absolute price level
        take_profit:  absolute price level
        occult_stops: when True, omit stopLossOnFill/takeProfitOnFill so no
                      stop orders are visible to the broker (stop-hunt defence).
                      The daemon closes the trade explicitly when levels are hit.

    Returns the full Oanda order-fill response dict.
    The trade ID lives at response["orderFillTransaction"]["tradeOpened"]["tradeID"].
    """
    _require_config()
    instrument   = INSTRUMENTS[pair.lower()]
    signed_units = units if direction == "BUY" else -units
    order: dict = {
        "type":        "MARKET",
        "instrument":  instrument,
        "units":       str(signed_units),
        "timeInForce": "FOK",
    }
    if not occult_stops:
        order["stopLossOnFill"]   = {"price": _fmt_price(pair, stop_loss)}
        order["takeProfitOnFill"] = {"price": _fmt_price(pair, take_profit)}
    payload = {"order": order}
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/orders"
    resp = requests.post(url, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} — {resp.text}",
            response=resp,
        )
    return resp.json()


def modify_trade_sl(trade_id: str, stop_loss: float, pair: str = "") -> dict:
    """Move the stop-loss on an open trade (e.g. to breakeven)."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}/orders"
    payload = {"stopLoss": {"price": _fmt_price(pair, stop_loss)}}
    resp = requests.put(url, headers=_headers(), json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def modify_trade_tp(trade_id: str, take_profit: float, pair: str = "") -> dict:
    """Place or move the take-profit order on an open trade."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}/orders"
    payload = {"takeProfit": {"price": _fmt_price(pair, take_profit)}}
    resp = requests.put(url, headers=_headers(), json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def cancel_trade_sl(trade_id: str) -> dict:
    """Remove the stop-loss order attached to an open trade (occult it)."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    sl_order = resp.json().get("trade", {}).get("stopLossOrder")
    if not sl_order:
        return {"message": "no stop loss order found"}
    order_id = sl_order["id"]
    cancel_url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/orders/{order_id}/cancel"
    resp = requests.put(cancel_url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def cancel_trade_tp(trade_id: str) -> dict:
    """Remove the take-profit order attached to an open trade (occult it)."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    tp_order = resp.json().get("trade", {}).get("takeProfitOrder")
    if not tp_order:
        return {"message": "no take profit order found"}
    order_id = tp_order["id"]
    cancel_url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/orders/{order_id}/cancel"
    resp = requests.put(cancel_url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def close_trade(trade_id: str) -> dict:
    """Close an open trade in full by its Oanda trade ID."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}/close"
    resp = requests.put(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Open trades ───────────────────────────────────────────────────────────────

def get_open_trades() -> list[dict]:
    """
    Return all open trades on the account.

    Each dict contains at minimum: id, instrument, currentUnits, price,
    unrealizedPL, stopLossOrder, takeProfitOrder.
    """
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/openTrades"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()["trades"]


# ── Candles ───────────────────────────────────────────────────────────────────

def get_candles(
    pair: str,
    granularity: str = "M5",
    count: int = 200,
    from_time: datetime | None = None,
) -> list[dict]:
    """
    Fetch completed mid-price OHLCV candles.

    Args:
        pair:        internal key, e.g. "eurusd"
        granularity: Oanda string — "M5", "M15", "H1", "H4", "D", etc.
        count:       number of candles to return (max 5000); combined with from_time
                     when both are specified — returns up to count candles from that start
        from_time:   if given, fetch candles whose open time is >= this UTC datetime

    Returns a list of dicts with keys: time, open, high, low, close, volume.
    Incomplete (still-forming) candles are excluded.
    """
    _require_config()
    instrument = INSTRUMENTS[pair.lower()]
    url = f"{_BASE_URL}/v3/instruments/{instrument}/candles"
    params: dict = {"granularity": granularity, "price": "M", "count": count}
    if from_time is not None:
        params["from"] = from_time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return [
        {
            "time":   c["time"],
            "open":   float(c["mid"]["o"]),
            "high":   float(c["mid"]["h"]),
            "low":    float(c["mid"]["l"]),
            "close":  float(c["mid"]["c"]),
            "volume": int(c["volume"]),
        }
        for c in resp.json()["candles"]
        if c.get("complete", True)
    ]


def get_candles_paginated(
    pair: str,
    granularity: str,
    from_time: datetime,
    to_time: datetime | None = None,
    page_size: int = 5000,
) -> pd.DataFrame:
    """
    Fetch a large history of candles by paging through OANDA in batches of
    up to page_size (max 5000) candles per request.

    Repeatedly calls get_candles() with a moving from_time cursor until
    to_time is reached or a partial page is returned (end of available data).

    Args:
        pair:        internal pair key, e.g. "eurusd"
        granularity: Oanda granularity string — "M1", "M5", "H1", "D", etc.
        from_time:   UTC start datetime (inclusive, candle open time)
        to_time:     UTC end datetime (inclusive); defaults to now
        page_size:   candles per request, max 5000

    Returns a UTC-indexed DataFrame with open/high/low/close/volume columns,
    sorted ascending.  Returns an empty DataFrame if no candles are available.
    The caller is responsible for deduplication if ranges overlap.
    """
    if to_time is None:
        to_time = datetime.now(timezone.utc)

    accumulated: list[dict] = []
    cursor = from_time

    while cursor < to_time:
        batch = get_candles(pair, granularity=granularity, from_time=cursor, count=page_size)
        if not batch:
            break

        accumulated.extend(batch)

        if len(batch) < page_size:
            break  # partial page — consumed all available data up to to_time

        # Advance cursor past the last returned candle.
        # OANDA timestamps are candle open times (RFC3339, nanosecond precision).
        # Truncate to seconds then add 1 second to land inside the next candle's
        # open time for any granularity (M1=60s gap, H1=3600s gap, D=86400s gap).
        last_open = datetime.strptime(
            batch[-1]["time"][:19], "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        if last_open >= to_time:
            break
        cursor = last_open + timedelta(seconds=1)
        _time.sleep(0.2)  # be polite to the API between pages

    if not accumulated:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(accumulated)
    df.index = pd.to_datetime(df["time"], utc=True)
    df.drop(columns=["time"], inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)
    _to_ts = pd.Timestamp(to_time) if to_time.tzinfo is not None else pd.Timestamp(to_time, tz="UTC")
    df = df[df.index <= _to_ts]
    return df[["open", "high", "low", "close", "volume"]]
