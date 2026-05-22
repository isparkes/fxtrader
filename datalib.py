"""
OANDA Data Library
==================
Manages a persistent local parquet store of historical OANDA candle data.

All market data for backtesting and indicator warm-up is sourced exclusively
from this library.  Yahoo Finance is not used anywhere in this project.

Storage layout
--------------
data/oanda/
    eurusd_M1.parquet      # 1-minute bars — primary resolution
    eurusd_H1.parquet      # 1-hour bars — bias indicators
    eurusd_D.parquet       # daily bars — ADX gate
    gbpusd_M1.parquet
    ...

Format: Parquet with Snappy compression.  Each file has a UTC DatetimeIndex
and float64 OHLCV columns (open, high, low, close, volume as int64).

M5 is never stored.  Always derive it via:  datalib.resample(df_m1, "M5")

Augmentation
------------
update() fetches only bars newer than the last stored timestamp and appends
them to the parquet file.  An initial seed is performed automatically the
first time a pair/granularity is requested.

Default lookback on initial seed:
    M1  —  90 days   (entry simulation; ~93 000 bars per pair)
    H1  — 730 days   (2 years for indicator warmup and regime variety)
    D   — 1000 days  (~3 years for ADX regime context)

CLI usage
---------
    python datalib.py status                  # show stored ranges per pair
    python datalib.py update                  # incremental update, all pairs/granularities
    python datalib.py update eurusd           # all granularities for one pair
    python datalib.py update eurusd M1        # specific pair + granularity
    python datalib.py seed                    # full initial seed, all pairs
    python datalib.py seed eurusd --days 365  # seed one pair with custom lookback
    python datalib.py verify eurusd           # print row counts at each granularity
"""

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import oanda

log = logging.getLogger("fxtrader.datalib")

# ── Constants ─────────────────────────────────────────────────────────────────

PAIRS: list[str] = ["eurusd", "gbpusd", "usdjpy", "audusd"]

GRANULARITIES: list[str] = ["M1", "H1", "D"]

# Mapping from datalib granularity strings to Oanda API granularity strings
_OANDA_GRAN: dict[str, str] = {
    "M1":  "M1",
    "M5":  "M5",
    "M15": "M15",
    "H1":  "H1",
    "H4":  "H4",
    "D":   "D",
}

# Mapping from resample target to pandas offset alias
_RESAMPLE_FREQ: dict[str, str] = {
    "M1":  "1min",
    "M5":  "5min",
    "M15": "15min",
    "H1":  "1h",
    "H4":  "4h",
    "D":   "1D",
}

DEFAULT_LOOKBACK: dict[str, int] = {
    "M1": 90,
    "H1": 730,
    "D":  1000,
}

# Overlap appended to from_time on incremental updates to catch any partial
# bars that were still forming on the previous fetch.
_UPDATE_OVERLAP: dict[str, timedelta] = {
    "M1": timedelta(minutes=5),
    "H1": timedelta(hours=3),
    "D":  timedelta(days=2),
}

_DATA_DIR_ENV = os.getenv("DATALIB_DIR", "data/oanda")


def _data_dir() -> Path:
    p = Path(_DATA_DIR_ENV)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(pair: str, granularity: str) -> Path:
    return _data_dir() / f"{pair.lower()}_{granularity.upper()}.parquet"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _df_to_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame to parquet, ensuring correct dtypes."""
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype("float64")
    df["volume"] = df["volume"].astype("int64")
    df.to_parquet(path, compression="snappy", engine="fastparquet")


def _fetch_initial(pair: str, granularity: str, lookback_days: int) -> pd.DataFrame:
    """Seed a new parquet file with lookback_days of history."""
    from_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    log.info(
        "%s %s  initial seed: fetching %d days from %s",
        pair.upper(), granularity, lookback_days,
        from_time.strftime("%Y-%m-%d"),
    )
    df = oanda.get_candles_paginated(
        pair,
        granularity=_OANDA_GRAN[granularity],
        from_time=from_time,
    )
    if df.empty:
        log.warning("%s %s  no candles returned for initial seed", pair.upper(), granularity)
    return df


def _fetch_delta(pair: str, granularity: str, last_ts: datetime) -> pd.DataFrame:
    """Fetch candles newer than last_ts (with a small overlap)."""
    overlap = _UPDATE_OVERLAP.get(granularity, timedelta(minutes=5))
    from_time = last_ts - overlap
    log.debug(
        "%s %s  incremental fetch from %s",
        pair.upper(), granularity, from_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return oanda.get_candles_paginated(
        pair,
        granularity=_OANDA_GRAN[granularity],
        from_time=from_time,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def update(
    pair: str,
    granularity: str | None = None,
    lookback_days: int | None = None,
) -> dict[str, int]:
    """
    Fetch new bars from OANDA and append to the parquet store.

    If the parquet file does not exist, performs an initial seed using
    DEFAULT_LOOKBACK (or lookback_days if provided).

    Args:
        pair:          internal pair key, e.g. "eurusd"
        granularity:   "M1", "H1", or "D"; if None, updates all three
        lookback_days: override default lookback for initial seeds only

    Returns {granularity: new_bars_added}.
    """
    grans = [granularity.upper()] if granularity else GRANULARITIES
    result: dict[str, int] = {}

    for gran in grans:
        path = _path(pair, gran)

        if not path.exists():
            days = lookback_days or DEFAULT_LOOKBACK[gran]
            new_df = _fetch_initial(pair, gran, days)
            if not new_df.empty:
                _df_to_parquet(new_df, path)
                result[gran] = len(new_df)
                log.info(
                    "%s %s  seeded %d bars (%s → %s)",
                    pair.upper(), gran, len(new_df),
                    new_df.index[0].strftime("%Y-%m-%d"),
                    new_df.index[-1].strftime("%Y-%m-%d"),
                )
            else:
                result[gran] = 0
            continue

        existing = pd.read_parquet(path, engine="fastparquet")
        last_ts  = existing.index[-1].to_pydatetime()
        delta    = _fetch_delta(pair, gran, last_ts)

        if delta.empty:
            log.debug("%s %s  no new bars", pair.upper(), gran)
            result[gran] = 0
            continue

        combined = pd.concat([existing, delta])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        new_bars = len(combined) - len(existing)
        _df_to_parquet(combined, path)
        result[gran] = max(new_bars, 0)
        if new_bars > 0:
            log.debug(
                "%s %s  +%d bars (now up to %s)",
                pair.upper(), gran, new_bars,
                combined.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        else:
            log.debug("%s %s  already up to date", pair.upper(), gran)

    return result


def update_all() -> dict[str, dict[str, int]]:
    """Update all pairs and all granularities. Returns {pair: {gran: bars_added}}."""
    results = {}
    for pair in PAIRS:
        results[pair] = update(pair)
    return results


def load(
    pair: str,
    granularity: str,
    start: datetime | None = None,
    end:   datetime | None = None,
) -> pd.DataFrame:
    """
    Load bars from the parquet store for an optional date range.

    Args:
        pair:        internal pair key, e.g. "eurusd"
        granularity: "M1", "H1", or "D"
        start:       UTC inclusive lower bound; None = beginning of stored data
        end:         UTC inclusive upper bound; None = end of stored data

    Returns a UTC-indexed DataFrame with OHLCV columns.

    Raises FileNotFoundError if the pair/granularity has not been seeded yet.
    Run `python datalib.py seed` to populate.
    """
    path = _path(pair, granularity)
    if not path.exists():
        raise FileNotFoundError(
            f"No data for {pair.upper()} {granularity}.  "
            f"Run: python datalib.py seed {pair} {granularity}"
        )

    log.info("Loading parquet data from %s", path)
    df = pd.read_parquet(path, engine="fastparquet")

    if start is not None:
        ts_start = pd.Timestamp(start) if start.tzinfo is not None else pd.Timestamp(start, tz="UTC")
        df = df[df.index >= ts_start]
    if end is not None:
        ts_end = pd.Timestamp(end) if end.tzinfo is not None else pd.Timestamp(end, tz="UTC")
        df = df[df.index <= ts_end]

    log.info(
        "%s %s  loaded %d bars  %s → %s",
        pair.upper(), granularity,
        len(df),
        df.index[0].strftime("%Y-%m-%dT%H:%M:%SZ") if len(df) else "—",
        df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ") if len(df) else "—",
    )
    return df


def resample(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """
    Resample an OHLCV DataFrame (typically M1) to a coarser granularity.

    Args:
        df:     UTC-indexed OHLCV DataFrame (any base granularity)
        target: target granularity — "M5", "M15", "H1", "H4", "D"

    Returns a new DataFrame at the target granularity.  Incomplete boundary
    bars (the final partial bar at the time of fetch) are dropped.
    """
    if target not in _RESAMPLE_FREQ:
        raise ValueError(
            f"Unsupported resample target '{target}'. "
            f"Choose from: {', '.join(_RESAMPLE_FREQ)}"
        )
    freq = _RESAMPLE_FREQ[target]
    resampled = (
        df.resample(freq, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    # Drop the last bar if it looks like a partial candle (volume below 10% of
    # the rolling median — a heuristic that catches the still-forming bar at
    # the boundary of the fetch window without needing to know the exact time).
    if len(resampled) > 20:
        median_vol = resampled["volume"].iloc[:-1].median()
        if median_vol > 0 and resampled["volume"].iloc[-1] < median_vol * 0.1:
            resampled = resampled.iloc[:-1]
    return resampled


def status() -> dict[str, dict[str, dict]]:
    """
    Return a summary of stored data per pair/granularity.

    Returns:
        {pair: {granularity: {"first": datetime, "last": datetime, "bars": int}}}
    """
    result: dict[str, dict[str, dict]] = {}
    for pair in PAIRS:
        result[pair] = {}
        for gran in GRANULARITIES:
            path = _path(pair, gran)
            if not path.exists():
                result[pair][gran] = None
                continue
            df = pd.read_parquet(path, columns=["open"], engine="fastparquet")
            result[pair][gran] = {
                "first": df.index[0].to_pydatetime(),
                "last":  df.index[-1].to_pydatetime(),
                "bars":  len(df),
                "size_mb": round(path.stat().st_size / 1_048_576, 2),
            }
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_status(_args) -> None:
    from rich.console import Console
    from rich.table import Table
    from rich import box

    info = status()
    console = Console()
    table = Table(title="OANDA Data Library", box=box.SIMPLE_HEAVY)
    table.add_column("Pair",        style="bold")
    table.add_column("Gran")
    table.add_column("Bars",        justify="right")
    table.add_column("First",       style="dim")
    table.add_column("Last",        style="dim")
    table.add_column("Size (MB)",   justify="right", style="dim")

    for pair in PAIRS:
        for gran in GRANULARITIES:
            entry = info[pair][gran]
            if entry is None:
                table.add_row(pair.upper(), gran, "—", "not seeded", "—", "—")
            else:
                table.add_row(
                    pair.upper(),
                    gran,
                    f"{entry['bars']:,}",
                    entry["first"].strftime("%Y-%m-%d"),
                    entry["last"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    str(entry["size_mb"]),
                )
    console.print(table)


def _cmd_update(args) -> None:
    pair = args.pair.lower() if args.pair else None
    gran = args.granularity.upper() if getattr(args, "granularity", None) else None

    if pair:
        totals = update(pair, gran, lookback_days=getattr(args, "days", None))
        for g, n in totals.items():
            print(f"{pair.upper()} {g}: +{n} bars")
    else:
        all_totals = update_all()
        for p, grans in all_totals.items():
            for g, n in grans.items():
                print(f"{p.upper()} {g}: +{n} bars")


def _cmd_seed(args) -> None:
    pair = args.pair.lower() if getattr(args, "pair", None) else None
    days = getattr(args, "days", None)
    pairs = [pair] if pair else PAIRS
    for p in pairs:
        totals = update(p, lookback_days=days)
        for g, n in totals.items():
            print(f"{p.upper()} {g}: {n} bars seeded")


def _cmd_verify(args) -> None:
    pair = args.pair.lower()
    for gran in GRANULARITIES:
        path = _path(pair, gran)
        if not path.exists():
            print(f"{pair.upper()} {gran}: not seeded")
            continue
        df = pd.read_parquet(path, engine="fastparquet")
        print(
            f"{pair.upper()} {gran}: {len(df):,} bars  "
            f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        if gran == "M1":
            m5  = resample(df, "M5")
            h1  = resample(df, "H1")
            print(f"  → M5:  {len(m5):,} bars")
            print(f"  → H1:  {len(h1):,} bars")


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="OANDA Data Library — manage persistent parquet candle store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples
--------
  python datalib.py status                  Show stored data ranges
  python datalib.py update                  Incremental update, all pairs
  python datalib.py update eurusd           Update all granularities for eurusd
  python datalib.py update eurusd M1        Update eurusd M1 only
  python datalib.py seed                    Full seed, all pairs (one-time setup)
  python datalib.py seed eurusd --days 365  Seed eurusd with 1-year lookback
  python datalib.py verify eurusd           Check row counts and resample
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    sub.add_parser("status", help="Show stored data ranges per pair/granularity")

    # update
    p_update = sub.add_parser("update", help="Incremental update (fetch new bars only)")
    p_update.add_argument("pair",        nargs="?", help="e.g. eurusd (default: all pairs)")
    p_update.add_argument("granularity", nargs="?", help="M1, H1, or D (default: all)")

    # seed
    p_seed = sub.add_parser("seed", help="Full initial seed (use once per pair)")
    p_seed.add_argument("pair",    nargs="?", help="e.g. eurusd (default: all pairs)")
    p_seed.add_argument("--days",  type=int, default=None,
                        help="Override default lookback in days")

    # verify
    p_verify = sub.add_parser("verify", help="Check row counts and test resample")
    p_verify.add_argument("pair", help="e.g. eurusd")

    args = parser.parse_args()

    try:
        if args.cmd == "status":
            _cmd_status(args)
        elif args.cmd == "update":
            _cmd_update(args)
        elif args.cmd == "seed":
            _cmd_seed(args)
        elif args.cmd == "verify":
            _cmd_verify(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
