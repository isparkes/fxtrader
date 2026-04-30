"""
Logging configuration for the FX / crypto trader daemons.

Each daemon calls configure() once at startup.  After that, every module
using logging.getLogger("<name>.*") writes to both the console and a
rotating log file.

Log levels
----------
DEBUG   : per-pair polling results, cache sizes, skipped bars, duplicate signals
INFO    : trade events (OPEN / BE / CLOSE), Oanda order fills, daemon start/stop
WARNING : recoverable problems — data fetch failures, Oanda API soft errors
ERROR   : unrecoverable signal-level failures — Oanda order rejected, unexpected exceptions

Console output follows LOG_LEVEL (default INFO, so routine polls stay quiet).
The file always captures DEBUG and above so the full history is available when
diagnosing problems.

Environment variables (all optional)
-------------------------------------
LOG_LEVEL        : console threshold — DEBUG / INFO / WARNING / ERROR (default INFO)
LOG_MAX_BYTES    : rotate when the file reaches this size in bytes (default 5 MB)
LOG_BACKUP_COUNT : number of rotated files to keep (default 5)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_LEVEL        = os.getenv("LOG_LEVEL",        "INFO").upper()
_LOG_MAX_BYTES    = int(os.getenv("LOG_MAX_BYTES",    str(5 * 1024 * 1024)))
_LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

_FMT      = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def configure(name: str, log_file: Path | None = None, level: str | None = None) -> None:
    """
    Attach console + rotating file handlers to the logger called ``name``.

    Args:
        name:     Root logger name, e.g. "fxtrader" or "cryptotrader".
                  All child loggers (name.daemon, name.tradelog, …) inherit
                  these handlers automatically.
        log_file: Path to the log file.  Defaults to ``<name>.log`` in the
                  current working directory.
        level:    Console log level override.  Falls back to the LOG_LEVEL
                  env var, then "INFO".

    Safe to call multiple times — handlers are only attached once.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return  # already configured; avoid duplicate handlers on restart/reload

    console_level = logging.getLevelName(level or _LOG_LEVEL)
    logger.setLevel(logging.DEBUG)   # logger itself passes everything; handlers filter
    logger.propagate = False         # don't bubble up to the root Python logger

    fmt = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # ── Console handler ───────────────────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ── Rotating file handler ─────────────────────────────────────────────────
    path = log_file or Path(f"{name}.log")
    fh = RotatingFileHandler(
        path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)   # file always captures everything
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("Logging initialised — file: %s  console: %s  file: DEBUG",
                path, logging.getLevelName(console_level))
