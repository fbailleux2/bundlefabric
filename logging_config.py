"""BundleFabric — Centralized logging configuration.

Provides structured logging equivalent to log4j, with:
  - Named loggers per module (hierarchy: bundlefabric.*)
  - Colour-coded text format for development
  - JSON format for production log aggregation (ELK / Loki / Grafana)
  - Request-ID tracing via ContextVar (propagates across async tasks)
  - Optional rotating file handler

Environment variables:
  LOG_LEVEL   — DEBUG | INFO | WARNING | ERROR | CRITICAL  (default: INFO)
  LOG_FORMAT  — text | json                                 (default: text)
  LOG_FILE    — path to log file (empty = stdout only)      (default: "")
  LOG_MAX_MB  — max log file size in MB before rotation     (default: 10)

Usage:
    from logging_config import get_logger
    logger = get_logger("orchestrator.main")

    logger.info("Server started", extra={"version": "2.1.0"})
    logger.debug("Intent extracted in %.1fms", elapsed)
    logger.warning("Ollama timeout — falling back to keywords")
    logger.error("Qdrant unavailable", exc_info=True)
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar
from typing import Optional

# ── Environment configuration ─────────────────────────────────────────────────

LOG_LEVEL        = os.getenv("LOG_LEVEL",  "INFO").upper()
LOG_FORMAT       = os.getenv("LOG_FORMAT", "text")   # "text" | "json"
LOG_FILE         = os.getenv("LOG_FILE",   "")
LOG_MAX_BYTES    = int(os.getenv("LOG_MAX_MB", "10")) * 1024 * 1024
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# ── Request-ID context variable ────────────────────────────────────────────────
# Set once per HTTP request (in the FastAPI middleware) and read by all log
# formatters to correlate every log line belonging to the same request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


# ── Formatters ────────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """One-JSON-object-per-line formatter — compatible with ELK / Loki / Grafana Loki.

    Output example:
      {"ts":"2026-03-19T01:42:00","level":"INFO","logger":"bundlefabric.factory.loader",
       "msg":"Bundle loaded in 2.3ms","req_id":"a1b2c3d4","bundle_id":"bundle-linux-ops"}
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":      self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
            "req_id":  request_id_var.get("-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra={} fields passed by callers
        _skip = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        for k, v in record.__dict__.items():
            if k not in _skip and not k.startswith("_") and k not in payload:
                try:
                    json.dumps(v)        # Only include JSON-serialisable extras
                    payload[k] = v
                except (TypeError, ValueError):
                    payload[k] = str(v)  # Fallback: stringify non-serialisable values
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Colour-coded human-readable formatter for terminal / development use.

    Output example:
      01:42:00 INFO     bundlefabric.factory.loader [a1b2c3d4] — Bundle loaded in 2.3ms
    """

    _COLORS = {
        "DEBUG":    "\033[36m",    # cyan
        "INFO":     "\033[32m",    # green
        "WARNING":  "\033[33m",    # yellow
        "ERROR":    "\033[31m",    # red
        "CRITICAL": "\033[35;1m",  # magenta bold
    }
    _RESET = "\033[0m"
    _DIM   = "\033[2m"
    _BOLD  = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color   = self._COLORS.get(record.levelname, "")
        req_id  = request_id_var.get("-")
        ts      = self.formatTime(record, datefmt="%H:%M:%S")

        # Short module name (drop the "bundlefabric." prefix for readability)
        short_name = record.name.removeprefix("bundlefabric.")

        line = (
            f"{self._DIM}{ts}{self._RESET} "
            f"{color}{record.levelname:<8}{self._RESET} "
            f"{self._BOLD}{short_name}{self._RESET}"
        )
        if req_id != "-":
            line += f" {self._DIM}[{req_id[:8]}]{self._RESET}"
        line += f" — {record.getMessage()}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ── Setup ─────────────────────────────────────────────────────────────────────

_configured: bool = False


def setup_logging() -> None:
    """Configure the root 'bundlefabric' logger. Idempotent — safe to call many times."""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, LOG_LEVEL, logging.INFO)

    # Select formatter based on LOG_FORMAT
    fmt: logging.Formatter = JsonFormatter() if LOG_FORMAT == "json" else TextFormatter()

    # Always write to stdout
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    handlers: list[logging.Handler] = [console]

    # Optional rotating file handler
    if LOG_FILE:
        try:
            fh = logging.handlers.RotatingFileHandler(
                LOG_FILE,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            fh.setFormatter(fmt)
            handlers.append(fh)
        except OSError as exc:
            logging.warning("Cannot open log file %s: %s", LOG_FILE, exc)

    # Attach handlers to the bundlefabric root logger (not the Python root logger,
    # so we don't accidentally capture noise from third-party libraries).
    bf_logger = logging.getLogger("bundlefabric")
    bf_logger.setLevel(level)
    bf_logger.handlers.clear()
    for h in handlers:
        bf_logger.addHandler(h)
    bf_logger.propagate = False  # Prevent double-logging via Python root logger

    # Quiet down noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    bf_logger.info(
        "Logging initialised — level=%s format=%s%s",
        LOG_LEVEL, LOG_FORMAT,
        f" file={LOG_FILE}" if LOG_FILE else "",
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger under the 'bundlefabric' namespace.

    The `name` argument should identify the module using dot notation:
        get_logger("orchestrator.main")   → bundlefabric.orchestrator.main
        get_logger("factory.loader")      → bundlefabric.factory.loader
        get_logger("memory.rag")          → bundlefabric.memory.rag
        get_logger("auth")                → bundlefabric.auth

    Callers never need to call setup_logging() manually — it's invoked here
    on first use, guaranteeing the logger is ready before the first message.
    """
    setup_logging()
    return logging.getLogger(f"bundlefabric.{name}")
