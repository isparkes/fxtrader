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
from datetime import datetime

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

def place_market_order(
    pair: str,
    direction: str,
    units: int,
    stop_loss: float,
    take_profit: float,
) -> dict:
    """
    Place a market order with attached stop-loss and take-profit.

    Args:
        pair:        internal key, e.g. "eurusd"
        direction:   "BUY" or "SELL"
        units:       positive integer — sign is applied from direction
        stop_loss:   absolute price level
        take_profit: absolute price level

    Returns the full Oanda order-fill response dict.
    The trade ID lives at response["orderFillTransaction"]["tradeOpened"]["tradeID"].
    """
    _require_config()
    instrument  = INSTRUMENTS[pair.lower()]
    signed_units = units if direction == "BUY" else -units
    payload = {
        "order": {
            "type":        "MARKET",
            "instrument":  instrument,
            "units":       str(signed_units),
            "timeInForce": "FOK",
            "stopLossOnFill":   {"price": f"{stop_loss:.5f}"},
            "takeProfitOnFill": {"price": f"{take_profit:.5f}"},
        }
    }
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/orders"
    resp = requests.post(url, headers=_headers(), json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def modify_trade_sl(trade_id: str, stop_loss: float) -> dict:
    """Move the stop-loss on an open trade (e.g. to breakeven)."""
    _require_config()
    url = f"{_BASE_URL}/v3/accounts/{_ACCOUNT_ID}/trades/{trade_id}/orders"
    payload = {"stopLoss": {"price": f"{stop_loss:.5f}"}}
    resp = requests.put(url, headers=_headers(), json=payload, timeout=10)
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
        count:       number of candles (max 5000); ignored when from_time is set
        from_time:   if given, fetch from this UTC datetime instead of using count

    Returns a list of dicts with keys: time, open, high, low, close, volume.
    Incomplete (still-forming) candles are excluded.
    """
    _require_config()
    instrument = INSTRUMENTS[pair.lower()]
    url = f"{_BASE_URL}/v3/instruments/{instrument}/candles"
    params: dict = {"granularity": granularity, "price": "M"}
    if from_time is not None:
        params["from"] = from_time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    else:
        params["count"] = count
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
