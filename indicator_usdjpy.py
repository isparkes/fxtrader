"""
USDJPY Scalper
==============
Generates intraday scalping signals targeting 8-15 pip moves.

Overview
--------
The strategy uses a two-timeframe approach: the 1h chart sets the directional
bias and the 5m chart finds precise entry timing within that bias. Signals are
only generated during the London/NY overlap session (07:00-16:00 UTC) where
liquidity and volatility are highest.

──────────────────────────────────────────────────────────────────────────────
TREND FILTER  (1h bars — must pass ALL THREE to open a BUY or SELL bias)
──────────────────────────────────────────────────────────────────────────────

1. EMA50 side
   Price must be above EMA50 for BUY, below for SELL.
   This anchors every trade to the prevailing medium-term trend.

2. MACD histogram — sign + building
   The 1h MACD histogram (12/26/9) must be positive AND larger than the
   previous bar for BUY; negative AND smaller (more negative) for SELL.
   Requiring it to be building, not just on the right side, means we only
   trade when momentum is accelerating — not fading.

3. RSI(14) above / below 50
   The 1h RSI must be above 50 for BUY, below 50 for SELL. This is a
   second momentum confirmation independent of MACD. A MACD that is
   technically positive but accompanied by sub-50 RSI often means the
   move is exhausted; this gate filters those out.

──────────────────────────────────────────────────────────────────────────────
ENTRY FILTERS  (5m bars — evaluated once the 1h bias is active)
──────────────────────────────────────────────────────────────────────────────

Pre-checks applied to every bar before pattern evaluation:

  • Session gate     — bar timestamp must fall within 07:00–16:00 UTC.
  • ATR floor        — 5m ATR(14) must be ≥ 0.0002 (2 pips). Skips entries
                       when the market is too compressed to reach the target
                       before reversing. Effectively a volatility on/off switch.

Pattern A — EMA8/21 cross
  BUY:  EMA8 crosses above EMA21 on the current bar (was below on the previous
        bar). Confirms local momentum has flipped bullish.
  SELL: EMA8 crosses below EMA21. Local momentum flipped bearish.

  Additional guards:
    - RSI(7) must be 52–75 for BUY (momentum present, not overbought)
    - RSI(7) must be 25–48 for SELL (momentum present, not oversold)
    - Stochastic %K must be above %D and below 80 for BUY (aligned, room to run)
    - Stochastic %K must be below %D and above 20 for SELL

Pattern C — MACD histogram flip
  BUY:  5m MACD histogram (6/13/4) crosses from negative to positive while
        price is above EMA21. The short-period MACD is deliberately faster
        than the 1h version — it catches micro-momentum shifts.
  SELL: 5m MACD histogram crosses from positive to negative while price is
        below EMA21.

  Additional guards: same RSI and Stochastic conditions as Pattern A.

Note: an earlier "Pattern B" (EMA21 wick bounce) was removed during development
because it fired on virtually every minor retracement, producing too many false
entries without a meaningful edge.

──────────────────────────────────────────────────────────────────────────────
RISK MANAGEMENT
──────────────────────────────────────────────────────────────────────────────

Stop loss:   ATR(14) × 0.4  (~4–8 pips). Set at entry, never widened.

Take profit: ATR(14) × 3.0  Wide ceiling (~30+ pips). Rarely the binding
             exit — the trailing stop typically closes the trade first.
             Kept as an absolute cap against sudden gap moves.

Trailing stop — two phases:

  Phase 1 (hard stop → breakeven):
    Once price reaches 80% of the initial TP distance the stop is moved to
    entry price, dropping risk to zero (minus spread). The activation is
    intentionally late — firing too early converts near-winners into
    breakeven exits when normal noise pulls price back before TP.

  Phase 2 (breakeven → active trail):
    Once at breakeven the stop trails ATR × 0.4 behind the running best
    price with no fixed ceiling. Winners run until the trail is hit.
    This asymmetry — capped loss, uncapped win — is the core of the edge.

Cooldown:    No new entry for 30 minutes (6 × 5m bars) after a loss.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd
import yfinance as yf
from ta.trend import MACD, EMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

logging.basicConfig(level=logging.WARNING)
console = Console()

# ── Supported pairs ──────────────────────────────────────────────────────────
# Maps a short name (CLI arg) → Yahoo Finance ticker symbol.
# Add new pairs here; everything else adapts automatically.
PAIRS: dict[str, str] = {
    "usdjpy": "USDJPY=X",
}

SYMBOL = "USDJPY=X"


def pip_value(symbol: str) -> float:
    """Return the pip size for a symbol. JPY pairs use 0.01; all others 0.0001."""
    return 0.01 if "JPY" in symbol.upper() else 0.0001


# ── Tunable parameters ────────────────────────────────────────────────────────
# 1h trend
H1_EMA_TREND   = 50
H1_MACD_FAST   = 12
H1_MACD_SLOW   = 26
H1_MACD_SIGNAL = 9
H1_RSI_PERIOD  = 14

# 5m entry
M5_EMA_FAST      = 8
M5_EMA_SLOW      = 21
M5_RSI_PERIOD    = 7
M5_STOCH_PERIOD  = 14
M5_STOCH_SMOOTH  = 3
M5_ATR_MIN       = 0.0002   # 2 pips — don't scalp a dead market

# Risk — tight scalper targets
ATR_PERIOD        = 14
ATR_SL_MULT       = 0.4   # ~4-8 pip stop
ATR_TP_MULT       = 3.0   # wide ceiling — trailing stop usually exits first

# Session — London open through NY afternoon (UTC)
SESSION_START_UTC = 7
SESSION_END_UTC   = 16
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Signal:
    timestamp: str
    direction: str           # "BUY" | "SELL" | "FLAT"
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    atr: Optional[float]
    h1_macd_hist: Optional[float]
    h1_rsi: Optional[float]
    h1_trend: Optional[str]
    entry_basis: str
    risk_pips: Optional[float]
    reward_pips: Optional[float]
    rr_ratio: Optional[float]


def fetch_ohlcv(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """
    Download OHLCV bars from Yahoo Finance and return a clean DataFrame.

    Columns are lowercased and any MultiIndex (returned by some yfinance
    versions when a single ticker is requested) is flattened. Rows
    containing NaN are dropped before returning.

    Args:
        symbol:   Yahoo Finance ticker, e.g. "EURUSD=X".
        interval: Bar size string, e.g. "1h", "5m".
        period:   Lookback window string, e.g. "60d", "5d".

    Raises:
        RuntimeError: If Yahoo Finance returns an empty DataFrame.
    """
    df = yf.download(symbol, interval=interval, period=period, progress=False, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No data returned for {symbol} @ {interval}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df.dropna(inplace=True)
    return df


def compute_h1_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add trend-context indicators to a bar DataFrame (designed for 1h, also
    used on 4h resampled bars in long-mode backtesting).

    Columns added:
        macd_hist  — MACD histogram (12/26/9). Positive = bullish momentum,
                     negative = bearish. The strategy requires this to be
                     building (larger than the previous bar) before trading.
        ema_trend  — EMA(50). Price must be on the correct side of this line
                     for the corresponding direction to be active.
        atr        — ATR(14). Used to size stop-loss and take-profit levels.
        rsi        — RSI(14). Must be above 50 for BUY bias, below 50 for
                     SELL bias — a second momentum gate independent of MACD.
    """
    close = df["close"]

    macd_ind = MACD(close=close, window_fast=H1_MACD_FAST,
                    window_slow=H1_MACD_SLOW, window_sign=H1_MACD_SIGNAL)
    df["macd_hist"] = macd_ind.macd_diff()

    ema = EMAIndicator(close=close, window=H1_EMA_TREND)
    df["ema_trend"] = ema.ema_indicator()

    atr = AverageTrueRange(high=df["high"], low=df["low"], close=close, window=ATR_PERIOD)
    df["atr"] = atr.average_true_range()

    df["rsi"] = RSIIndicator(close=close, window=H1_RSI_PERIOD).rsi()

    return df


def compute_m5_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add entry-timing indicators to a bar DataFrame (designed for 5m, also
    used on 1h bars in long-mode backtesting).

    Columns added:
        ema_fast   — EMA(8). Compared against ema_slow to detect crossovers.
        ema_slow   — EMA(21). Price must be above this for BUY entries,
                     below for SELL entries.
        rsi        — RSI(7). Short period for responsiveness. Must be in the
                     52-75 band for BUY, 25-48 for SELL.
        macd_hist  — MACD histogram (6/13/4). Faster settings than the trend
                     MACD to catch micro-momentum shifts. A cross of zero
                     while price is on the correct side of ema_slow triggers
                     Pattern C entries.
        stoch_k    — Stochastic %K (14,3). Must be above stoch_d and below
                     80 for BUY; below stoch_d and above 20 for SELL.
        stoch_d    — Stochastic %D (3-bar smoothed signal line).
        atr        — ATR(14). Used as a volatility gate: entries are skipped
                     when atr < M5_ATR_MIN (market too flat to reach target).
    """
    close = df["close"]

    df["ema_fast"] = EMAIndicator(close=close, window=M5_EMA_FAST).ema_indicator()
    df["ema_slow"] = EMAIndicator(close=close, window=M5_EMA_SLOW).ema_indicator()
    df["rsi"]      = RSIIndicator(close=close, window=M5_RSI_PERIOD).rsi()

    macd_ind = MACD(close=close, window_fast=6, window_slow=13, window_sign=4)
    df["macd_hist"] = macd_ind.macd_diff()

    stoch = StochasticOscillator(
        high=df["high"], low=df["low"], close=close,
        window=M5_STOCH_PERIOD, smooth_window=M5_STOCH_SMOOTH,
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=close, window=ATR_PERIOD,
    ).average_true_range()

    return df


def assess_h1_bias(df: pd.DataFrame) -> dict:
    """
    Evaluate the three trend gates on the last completed 1h bar and return
    the directional bias together with the raw indicator values.

    Uses iloc[-2] (last completed bar) rather than iloc[-1] (still forming).
    Returns direction "FLAT" unless all three gates pass simultaneously:
        1. Price side of EMA50
        2. MACD histogram positive/negative AND building vs previous bar
        3. RSI(14) above/below 50

    Returns a dict with keys:
        direction  — "BUY", "SELL", or "FLAT"
        macd_hist  — raw MACD histogram value
        h1_rsi     — raw RSI value
        atr        — raw ATR value (used for SL/TP sizing)
        trend      — human-readable EMA50 position string
        close      — last completed bar close price
    """
    last = df.iloc[-2]   # -1 is still forming
    prev = df.iloc[-3]

    close     = float(last["close"])
    ema_trend = float(last["ema_trend"])
    macd_hist = float(last["macd_hist"])
    atr       = float(last["atr"])

    prev_hist = float(prev["macd_hist"])
    h1_rsi    = float(last["rsi"])

    above = close > ema_trend
    below = close < ema_trend
    # MACD building + RSI on the right side of 50
    bull  = macd_hist > 0 and macd_hist > prev_hist and h1_rsi > 50
    bear  = macd_hist < 0 and macd_hist < prev_hist and h1_rsi < 50

    if above and bull:
        direction = "BUY"
    elif below and bear:
        direction = "SELL"
    else:
        direction = "FLAT"

    return {
        "direction":  direction,
        "macd_hist":  macd_hist,
        "h1_rsi":     h1_rsi,
        "atr":        atr,
        "trend":      "above EMA50" if above else "below EMA50",
        "close":      close,
    }


def find_m5_entry(df5m: pd.DataFrame, direction: str) -> Optional[dict]:
    """
    Scan the last 24 5m bars (2 hours) for a scalp entry trigger.
    Direction is set by 1h bias — entries only fire when aligned with it.

    Pattern A: EMA8 crosses EMA21 in trend direction, RSI showing momentum
    Pattern C: 5m MACD histogram flips in trend direction, RSI confirming
    (Pattern B — EMA21 wick bounce — removed: too noisy for scalping)
    """
    if direction == "FLAT":
        return None

    window = df5m.iloc[-24:].copy()

    for i in range(3, len(window)):
        bar  = window.iloc[i]
        prev = window.iloc[i - 1]

        # Session filter — skip bars outside London/NY overlap
        ts = bar.name
        if hasattr(ts, "hour"):
            hour = ts.tz_convert("UTC").hour if getattr(ts, "tzinfo", None) else ts.hour
            if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
                continue

        close    = float(bar["close"])
        ema_fast = float(bar["ema_fast"])
        ema_slow = float(bar["ema_slow"])
        prev_ef  = float(prev["ema_fast"])
        prev_es  = float(prev["ema_slow"])
        rsi      = float(bar["rsi"])
        hist     = float(bar["macd_hist"])
        prev_h   = float(prev["macd_hist"])
        stoch_k  = float(bar["stoch_k"])
        stoch_d  = float(bar["stoch_d"])
        atr_m5   = float(bar["atr"])

        if any(pd.isna(v) for v in [ema_fast, ema_slow, rsi, hist, stoch_k, stoch_d, atr_m5]):
            continue

        # ATR filter: skip if market is too flat to reach the target
        if atr_m5 < M5_ATR_MIN:
            continue

        if direction == "BUY":
            # Stochastic: %K above %D and not overbought
            stoch_ok = stoch_k > stoch_d and stoch_k < 80
            # A: EMA8 crosses above EMA21, RSI and Stochastic confirm
            if ema_fast > ema_slow and prev_ef <= prev_es and 52 < rsi < 75 and stoch_ok:
                return {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross"}
            # C: MACD histogram flips positive, RSI and Stochastic confirm
            if hist > 0 and prev_h <= 0 and close > ema_slow and 52 < rsi < 72 and stoch_ok:
                return {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip"}

        elif direction == "SELL":
            # Stochastic: %K below %D and not oversold
            stoch_ok = stoch_k < stoch_d and stoch_k > 20
            # A: EMA8 crosses below EMA21, RSI and Stochastic confirm
            if ema_fast < ema_slow and prev_ef >= prev_es and 25 < rsi < 48 and stoch_ok:
                return {"price": close, "bar_time": str(bar.name), "pattern": "A-ema-cross"}
            # C: MACD histogram flips negative, RSI and Stochastic confirm
            if hist < 0 and prev_h >= 0 and close < ema_slow and 28 < rsi < 48 and stoch_ok:
                return {"price": close, "bar_time": str(bar.name), "pattern": "C-macd-flip"}

    return None


def build_signal(h1_bias: dict, entry: Optional[dict], symbol: str = "EURUSD=X") -> Signal:
    """
    Combine the 1h bias and the 5m entry trigger into a Signal dataclass.

    If direction is FLAT or no entry was found, returns a FLAT signal with
    the trend indicator values filled in for diagnostic purposes.

    Otherwise computes:
        stop_loss   = entry ± ATR × ATR_SL_MULT
        take_profit = entry ± ATR × ATR_TP_MULT  (wide ceiling)
        risk_pips / reward_pips / rr_ratio derived from the above
    """
    direction = h1_bias["direction"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    atr       = h1_bias["atr"]

    if direction == "FLAT" or entry is None:
        reason = "No 1h trend alignment" if direction == "FLAT" else "No 5m entry trigger"
        return Signal(
            timestamp=now_str, direction="FLAT",
            entry_price=None, stop_loss=None, take_profit=None,
            atr=round(atr, 5),
            h1_macd_hist=round(h1_bias["macd_hist"], 6),
            h1_rsi=round(h1_bias["h1_rsi"], 1),
            h1_trend=h1_bias["trend"],
            entry_basis=reason,
            risk_pips=None, reward_pips=None, rr_ratio=None,
        )

    ep = entry["price"]
    if direction == "BUY":
        sl = ep - atr * ATR_SL_MULT
        tp = ep + atr * ATR_TP_MULT
    else:
        sl = ep + atr * ATR_SL_MULT
        tp = ep - atr * ATR_TP_MULT

    pv          = pip_value(symbol)
    risk_pips   = abs(ep - sl) / pv
    reward_pips = abs(tp - ep) / pv
    rr          = reward_pips / risk_pips if risk_pips > 0 else 0

    pattern_labels = {
        "A-ema-cross":  "5m EMA8/21 cross",
        "B-ema-bounce": "5m EMA21 bounce",
        "C-macd-flip":  "5m MACD flip",
    }
    label = pattern_labels.get(entry.get("pattern", ""), entry.get("pattern", ""))
    basis = (
        f"1h {h1_bias['trend']}, MACD {'bull' if direction == 'BUY' else 'bear'}, "
        f"{label} @ {entry['bar_time']}"
    )

    return Signal(
        timestamp=now_str,
        direction=direction,
        entry_price=round(ep, 5),
        stop_loss=round(sl, 5),
        take_profit=round(tp, 5),
        atr=round(atr, 5),
        h1_macd_hist=round(h1_bias["macd_hist"], 6),
        h1_rsi=round(h1_bias["h1_rsi"], 1),
        h1_trend=h1_bias["trend"],
        entry_basis=basis,
        risk_pips=round(risk_pips, 1),
        reward_pips=round(reward_pips, 1),
        rr_ratio=round(rr, 2),
    )


def run(symbol: str = SYMBOL) -> Signal:
    """
    Fetch live data, compute indicators, and return the current signal.

    Fetches 60 days of 1h data for trend context and 5 days of 5m data
    for entry timing. The shorter 5m window keeps the entry scan focused
    on the most recent price action.

    Args:
        symbol: Yahoo Finance ticker, e.g. "EURUSD=X" or "GBPUSD=X".
    """
    console.print(f"[bold cyan]Fetching {symbol} data...[/]")

    df_h1 = fetch_ohlcv(symbol, interval="1h", period="60d")
    df_5m = fetch_ohlcv(symbol, interval="5m", period="5d")

    df_h1 = compute_h1_indicators(df_h1)
    df_5m = compute_m5_indicators(df_5m)

    h1_bias = assess_h1_bias(df_h1)
    entry   = find_m5_entry(df_5m, h1_bias["direction"])
    signal  = build_signal(h1_bias, entry, symbol)

    return signal


def display_signal(signal: Signal, symbol: str = SYMBOL) -> None:
    """Render the signal as a Rich panel to the terminal."""
    colour = {
        "BUY":  "bold green",
        "SELL": "bold red",
        "FLAT": "bold yellow",
    }[signal.direction]

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Field", style="dim")
    table.add_column("Value")

    table.add_row("Timestamp",   signal.timestamp)
    table.add_row("Direction",   f"[{colour}]{signal.direction}[/]")

    if signal.direction != "FLAT":
        table.add_row("Entry",       f"{signal.entry_price:.5f}")
        table.add_row("Stop Loss",   f"{signal.stop_loss:.5f}  ({signal.risk_pips:.0f} pips)")
        table.add_row("Take Profit", f"{signal.take_profit:.5f}  ({signal.reward_pips:.0f} pips)")
        table.add_row("R:R",         f"1 : {signal.rr_ratio:.2f}")

    table.add_row("ATR(14) 1h",  f"{signal.atr:.5f}")
    table.add_row("1h Trend",    signal.h1_trend or "")
    table.add_row("1h RSI",      f"{signal.h1_rsi:.1f}" if signal.h1_rsi is not None else "—")
    table.add_row("MACD Hist",   f"{signal.h1_macd_hist:.6f}")
    table.add_row("Basis",       signal.entry_basis)

    pair_label = symbol.replace("=X", "")
    console.print(Panel(table, title=f"[bold]{pair_label} Scalper Signal[/]", border_style="cyan"))


def save_signal(signal: Signal, path: str = "signals.jsonl") -> None:
    """Append the signal as a JSON line to the log file."""
    with open(path, "a") as f:
        f.write(json.dumps(asdict(signal)) + "\n")


if __name__ == "__main__":
    import argparse as _argparse

    _parser = _argparse.ArgumentParser(description="FX Scalper — live signal generator")
    _parser.add_argument(
        "--pair",
        default="eurusd",
        choices=list(PAIRS.keys()),
        help="Currency pair to analyse (default: eurusd)",
    )
    _parser.add_argument(
        "--all",
        action="store_true",
        help="Run all supported pairs",
    )
    _parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only display non-FLAT signals",
    )
    _args = _parser.parse_args()

    _pairs_to_run = list(PAIRS.items()) if _args.all else [(_args.pair, PAIRS[_args.pair])]

    for _pair_name, _symbol in _pairs_to_run:
        signal = run(_symbol)
        if _args.quiet and signal.direction == "FLAT":
            continue
        display_signal(signal, _symbol)
        save_signal(signal)

    console.print("\n[dim]Signal(s) appended to signals.jsonl[/]")
