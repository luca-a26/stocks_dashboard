from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"


def get_logger(name: str = "strategic_metals") -> logging.Logger:
    """Return a project logger with console and file output."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_DIR / "dashboard.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Unable to initialise file logging: %s", exc)

    return logger


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "config.yaml")


def ensure_storage_path(subfolder: str) -> Path:
    """Ensure a project-local storage folder exists and return its absolute path."""
    path = Path(subfolder)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_tickers() -> dict[str, dict[str, Any]]:
    """
    Load watchlist metadata without making network calls.

    Network IO belongs in analysis/data fetchers, not configuration helpers.
    Keeping this function side-effect light makes dashboards and tests faster.
    """
    raw = load_yaml(CONFIG_DIR / "tickers.yaml")
    stocks = raw.get("stocks", {})
    tickers: dict[str, dict[str, Any]] = {}

    for code, info in stocks.items():
        normalised = dict(info or {})
        normalised["code"] = code
        normalised["ticker"] = (
            normalised.get("ticker")
            or normalised.get("investiny")
            or code
        )
        tickers[code] = normalised

    return tickers
