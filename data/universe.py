from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analysis.rare_earth_scoring import score_metadata_only
from data.discovery import load_project_pipeline
from data.utils import CONFIG_DIR, ensure_storage_path, get_logger, load_tickers

UNIVERSE_PATH = CONFIG_DIR / "ticker_universe.csv"
SCORE_CACHE_DIR = ensure_storage_path("storage/cache/scores")
DEFAULT_UNIVERSE_LIMIT = 100

UNIVERSE_FIELDS = [
    "ticker",
    "exchange",
    "company_name",
    "country",
    "sector",
    "commodity_tags",
    "supply_chain_role",
    "stage",
    "market_cap_tier",
    "source",
    "notes",
    "priority",
]


def score_cache_ttl() -> timedelta:
    hours = float(os.getenv("SCORE_CACHE_TTL_HOURS", "6"))
    return timedelta(hours=hours)


def _normalise_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[|;]", str(value)) if part.strip()]


def _join_tags(values: list[str]) -> str:
    seen: set[str] = set()
    tags: list[str] = []
    for value in values:
        normalised = value.strip()
        key = normalised.lower()
        if normalised and key not in seen:
            seen.add(key)
            tags.append(normalised)
    return "|".join(tags)


def _normalise_record(raw: dict[str, Any]) -> dict[str, Any]:
    ticker = _normalise_key(raw.get("ticker") or raw.get("code"))
    tags = _split_tags(raw.get("commodity_tags") or raw.get("focus"))
    return {
        "ticker": ticker,
        "exchange": str(raw.get("exchange") or "").strip(),
        "company_name": str(raw.get("company_name") or raw.get("name") or ticker).strip(),
        "country": str(raw.get("country") or "").strip(),
        "sector": str(raw.get("sector") or "").strip(),
        "commodity_tags": tags,
        "supply_chain_role": str(raw.get("supply_chain_role") or "").strip(),
        "stage": str(raw.get("stage") or "").strip(),
        "market_cap_tier": str(raw.get("market_cap_tier") or "").strip(),
        "source": str(raw.get("source") or "").strip(),
        "notes": str(raw.get("notes") or "").strip(),
        "priority": str(raw.get("priority") or "").strip(),
        "former_name": str(raw.get("former_name") or "").strip(),
        "former_ticker": str(raw.get("former_ticker") or "").strip(),
        "requested_name": str(raw.get("requested_name") or "").strip(),
    }


def _merge_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for field, value in incoming.items():
        if field == "commodity_tags":
            merged[field] = _split_tags(merged.get(field)) + _split_tags(value)
            merged[field] = _split_tags(_join_tags(merged[field]))
        elif value and not merged.get(field):
            merged[field] = value
        elif field == "notes" and value and value not in str(merged.get(field, "")):
            merged[field] = "; ".join(part for part in [merged.get(field), value] if part)
        elif field == "source" and value and value not in str(merged.get(field, "")):
            merged[field] = "; ".join(part for part in [merged.get(field), value] if part)
    return merged


def _records_from_universe_csv(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        get_logger(__name__).warning("Ticker universe file not found at %s", path)
        return records

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = _normalise_record(row)
            if record["ticker"]:
                records[record["ticker"]] = record

    get_logger(__name__).info("Loaded %s universe metadata rows from %s", len(records), path)
    return records


def _records_from_watchlist() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for ticker, info in load_tickers().items():
        record = _normalise_record(
            {
                "ticker": ticker,
                "exchange": info.get("exchange"),
                "company_name": info.get("name"),
                "commodity_tags": info.get("focus", []),
                "source": "config/tickers.yaml",
                "priority": info.get("priority") or "High",
                "former_name": info.get("former_name"),
                "former_ticker": info.get("former_ticker"),
                "requested_name": info.get("requested_name"),
            }
        )
        records[ticker] = record
    return records


def _records_from_discovery() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for project in load_project_pipeline():
        ticker = _normalise_key(project.get("ticker"))
        if not ticker:
            continue
        tags = _split_tags(project.get("commodity_focus")) + _split_tags(project.get("ree_class"))
        record = _normalise_record(
            {
                "ticker": ticker,
                "exchange": project.get("exchange"),
                "company_name": project.get("company"),
                "country": project.get("country"),
                "commodity_tags": tags,
                "supply_chain_role": project.get("supply_chain_role"),
                "stage": project.get("stage"),
                "source": project.get("source_confidence") or "config/ree_pipeline.yaml",
                "notes": project.get("notes"),
                "priority": project.get("priority"),
                "requested_name": project.get("requested_name"),
            }
        )
        records[ticker] = record
    return records


def load_ticker_universe(
    path: Path | None = None,
    *,
    include_curated: bool = True,
    include_discovery: bool = True,
) -> list[dict[str, Any]]:
    """
    Load cheap ticker metadata for search/ranking without market-data downloads.

    The tracked CSV is the scalable universe source. The curated watchlist and
    discovery config are merged in so existing high-priority names remain visible
    even if the CSV has not yet been fully populated.
    """
    records = _records_from_universe_csv(path or UNIVERSE_PATH)

    for source_records in (
        _records_from_watchlist() if include_curated else {},
        _records_from_discovery() if include_discovery else {},
    ):
        for ticker, record in source_records.items():
            records[ticker] = _merge_record(records.get(ticker, {}), record)

    universe = [record for record in records.values() if record.get("ticker")]
    universe.sort(key=lambda item: (item.get("company_name", ""), item.get("ticker", "")))
    get_logger(__name__).info("Ticker universe available: %s records", len(universe))
    return universe


def preliminary_score(record: dict[str, Any]) -> float:
    """Cheap metadata-only triage score used before fundamentals are loaded."""
    return float(score_metadata_only(record)["composite_score"])


def _priority_rank(record: dict[str, Any]) -> int:
    priority = str(record.get("priority", "")).lower()
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def rank_metadata_universe(
    records: list[dict[str, Any]],
    limit: int = DEFAULT_UNIVERSE_LIMIT,
) -> list[dict[str, Any]]:
    ranked = sorted(
        records,
        key=lambda record: (
            -preliminary_score(record),
            _priority_rank(record),
            record.get("company_name", ""),
            record.get("ticker", ""),
        ),
    )
    return ranked[:limit]


def search_ticker_universe(
    query: str,
    records: list[dict[str, Any]] | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if len(query) < 2:
        return []

    records = records if records is not None else load_ticker_universe()
    tokens = [token.lower() for token in re.split(r"\s+", query) if token.strip()]
    matches: list[tuple[int, dict[str, Any]]] = []

    for record in records:
        searchable_parts = [
            record.get("ticker", ""),
            record.get("company_name", ""),
            record.get("exchange", ""),
            record.get("country", ""),
            record.get("sector", ""),
            " ".join(_split_tags(record.get("commodity_tags"))),
            record.get("supply_chain_role", ""),
            record.get("stage", ""),
            record.get("market_cap_tier", ""),
        ]
        searchable = " ".join(str(part).lower() for part in searchable_parts)
        if not all(token in searchable for token in tokens):
            continue

        ticker = str(record.get("ticker", "")).lower()
        company = str(record.get("company_name", "")).lower()
        rank = 100
        if query.lower() == ticker:
            rank = 0
        elif ticker.startswith(query.lower()):
            rank = 5
        elif company.startswith(query.lower()):
            rank = 10
        matches.append((rank, record))

    matches.sort(key=lambda item: (item[0], -preliminary_score(item[1]), item[1].get("company_name", "")))
    get_logger(__name__).info("Universe search query=%r matches=%s", query, len(matches))
    return [record for _, record in matches[:limit]]


def get_universe_record(ticker: str, records: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    ticker_key = _normalise_key(ticker)
    records = records if records is not None else load_ticker_universe()
    return next((record for record in records if record.get("ticker") == ticker_key), None)


def score_cache_path(ticker: str) -> Path:
    safe_ticker = re.sub(r"[^A-Za-z0-9_.-]+", "_", _normalise_key(ticker))
    return SCORE_CACHE_DIR / f"{safe_ticker}.json"


def cache_state(path: Path, ttl: timedelta | None = None) -> str:
    if not path.exists():
        return "missing"
    ttl = score_cache_ttl() if ttl is None else ttl
    if ttl <= timedelta(0):
        return "stale"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return "fresh" if datetime.now(timezone.utc) - modified < ttl else "stale"


def read_scored_stock_cache(ticker: str, *, allow_stale: bool = True) -> tuple[dict[str, Any] | None, str]:
    path = score_cache_path(ticker)
    state = cache_state(path)
    if state == "missing":
        get_logger(__name__).info("Score cache miss for %s", _normalise_key(ticker))
        return None, state
    if state == "stale" and not allow_stale:
        get_logger(__name__).info("Score cache stale for %s", _normalise_key(ticker))
        return None, state

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    get_logger(__name__).info("Score cache %s for %s", state, _normalise_key(ticker))
    return payload, state


def write_scored_stock_cache(ticker: str, payload: dict[str, Any]) -> None:
    path = score_cache_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["_cache_written_utc"] = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    get_logger(__name__).info("Score cache write for %s", _normalise_key(ticker))


def load_cached_scored_stocks(*, include_stale: bool = True) -> list[dict[str, Any]]:
    stocks: list[dict[str, Any]] = []
    if not SCORE_CACHE_DIR.exists():
        return stocks

    for path in SCORE_CACHE_DIR.glob("*.json"):
        state = cache_state(path)
        if state == "stale" and not include_stale:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                stock = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            get_logger(__name__).warning("Unable to read score cache %s: %s", path, exc)
            continue
        if state == "stale":
            stock["score_status"] = "stale"
        stocks.append(stock)

    get_logger(__name__).info("Loaded %s cached scored stocks", len(stocks))
    return stocks
