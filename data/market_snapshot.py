from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from data.utils import PROJECT_ROOT, get_logger

DEFAULT_MARKET_SNAPSHOT_PATH = PROJECT_ROOT / "data" / "company_market_snapshot.csv"
DEFAULT_MARKET_SNAPSHOT_JSON_PATH = PROJECT_ROOT / "data" / "company_market_snapshot.json"
DEFAULT_MAX_AGE_HOURS = 6
DEFAULT_REQUIRED_COVERAGE = 0.95

SNAPSHOT_SOURCE_NAME = "company market snapshot"
SNAPSHOT_STATUSES = {
    "reported",
    "computed",
    "manual",
    "found_lse_share_page",
    "found_via_non_constituent_search",
    "found_suspended_security",
    "not_available_gdr_zero_shares_on_source",
    "not_applicable_preference_share_no_market_cap",
    "not_found",
    "stale",
    "conflicting",
}
NON_APPLICABLE_STATUSES = {
    "not_available_gdr_zero_shares_on_source",
    "not_applicable_preference_share_no_market_cap",
}
STATUS_FLAGS = {
    "found_suspended_security": "suspended_security",
    "not_available_gdr_zero_shares_on_source": "gdr_zero_shares",
    "not_applicable_preference_share_no_market_cap": "preference_share_no_market_cap",
    "conflicting": "market_cap_vendor_conflict",
}

CANONICAL_CSV_FIELDS = [
    "Ticker",
    "Company",
    "Market Cap",
    "Market Cap Currency",
    "Market Cap Numeric",
    "Magnitude",
    "Shares in Issue",
    "Status",
    "Primary Source",
    "Snapshot Date",
    "Notes",
    "Last Price",
    "Price Currency",
    "Price Unit",
    "Volume",
    "52 Week Low",
    "52 Week High",
]


def normalize_lse_ticker(value: Any) -> str:
    """Return the canonical London ticker key used to join snapshot, cache, and UI rows."""
    if value is None:
        return ""
    ticker = str(value).strip().upper()
    ticker = re.sub(r"^(LON|LSE|XLON):\s*", "", ticker)
    ticker = ticker.replace(" LON:", "").replace("LON:", "")
    ticker = ticker.replace(" LSE:", "").replace("LSE:", "")
    ticker = ticker.replace(" XLON:", "").replace("XLON:", "")
    if ticker.endswith(".L"):
        ticker = ticker[:-2]
    if ticker.endswith(" LN"):
        ticker = ticker[:-3]
    return ticker.strip()


def market_snapshot_path(path: Path | str | None = None) -> Path:
    if path is not None:
        resolved = Path(path)
    else:
        resolved = Path(os.getenv("MARKET_SNAPSHOT_PATH", str(DEFAULT_MARKET_SNAPSHOT_PATH)))
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def market_snapshot_json_path(path: Path | str | None = None) -> Path:
    if path is not None:
        resolved = Path(path)
    else:
        resolved = Path(os.getenv("MARKET_SNAPSHOT_JSON_PATH", str(DEFAULT_MARKET_SNAPSHOT_JSON_PATH)))
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def market_snapshot_max_age() -> timedelta:
    return timedelta(hours=float(os.getenv("MARKET_SNAPSHOT_MAX_AGE_HOURS", str(DEFAULT_MAX_AGE_HOURS))))


def market_snapshot_required_coverage() -> float:
    return float(os.getenv("MARKET_SNAPSHOT_REQUIRED_COVERAGE", str(DEFAULT_REQUIRED_COVERAGE)))


def live_market_refresh_enabled() -> bool:
    return os.getenv("ENABLE_LIVE_MARKET_REFRESH", "false").strip().lower() in {"1", "true", "yes"}


def market_refresh_action_enabled() -> bool:
    return os.getenv("ENABLE_MARKET_REFRESH_ACTION", "false").strip().lower() in {"1", "true", "yes"}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "-", "n/a", "na", "none", "null", "not found"}
    return True


def _to_float(value: Any) -> float | None:
    if not _present(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("£", "")
        .replace("Ł", "")
        .replace("\u00c2", "")
        .replace("$", "")
        .replace("€", "")
        .replace("â‚¬", "")
    )
    multiplier = 1.0
    lowered = text.lower()
    for suffix, factor in (
        ("billion", 1_000_000_000),
        ("bn", 1_000_000_000),
        ("b", 1_000_000_000),
        ("million", 1_000_000),
        ("m", 1_000_000),
        ("k", 1_000),
    ):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _text(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if _present(value):
            return str(value).strip()
    return ""


def _number(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _to_float(row.get(name))
        if value is not None:
            return value
    return None


def parse_snapshot_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime.combine(parsed_date, time(23, 59, 59), tzinfo=timezone.utc)
    normalised = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return None
        parsed = datetime.combine(parsed_date, time(23, 59, 59), tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def snapshot_is_stale(
    snapshot_date: Any,
    *,
    max_age: timedelta | None = None,
    now: datetime | None = None,
) -> bool:
    parsed = parse_snapshot_datetime(snapshot_date)
    if parsed is None:
        return True
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - parsed > (max_age or market_snapshot_max_age())


def normalise_market_snapshot_row(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    ticker = normalize_lse_ticker(_text(row, "ticker", "Ticker", "primary_ticker", "symbol"))
    company = _text(row, "company_name", "Company", "company", "name")
    status = _text(row, "status", "Status").lower() or "reported"
    if status not in SNAPSHOT_STATUSES:
        status = "reported" if status else "not_found"

    snapshot_date = _text(row, "snapshot_date", "Snapshot Date", "as_of_date", "fetched_at")
    stale = snapshot_is_stale(snapshot_date, now=now) if snapshot_date else True
    market_cap = _number(row, "market_cap_native", "market_cap", "Market Cap Numeric", "Market Cap")
    shares = _number(row, "shares_outstanding", "shares_outstanding_lfy", "Shares in Issue")
    last_price = _number(row, "last_price", "Last Price", "price")
    volume = _number(row, "volume", "Volume")
    fifty_two_week_low = _number(row, "fifty_two_week_low", "52 Week Low", "52W Low")
    fifty_two_week_high = _number(row, "fifty_two_week_high", "52 Week High", "52W High")
    source_url = _text(row, "source_url", "Primary Source", "share_price_url")
    notes = _text(row, "notes", "Notes")
    flags = [flag for snapshot_status, flag in STATUS_FLAGS.items() if snapshot_status == status]
    if stale:
        flags.append("stale_snapshot")
    if market_cap is None and status not in NON_APPLICABLE_STATUSES:
        flags.append("missing_market_cap")
    if shares is None or shares <= 0:
        flags.append("missing_shares_outstanding")
    if last_price is None:
        flags.append("missing_price")

    return {
        "ticker": ticker,
        "company_id": _text(row, "company_id", "Company ID") or f"LSE:{ticker}",
        "company_name": company,
        "market_cap_native": market_cap,
        "market_cap": market_cap,
        "market_cap_currency": _text(row, "market_cap_currency", "Market Cap Currency"),
        "market_cap_display": _text(row, "market_cap_display", "Market Cap"),
        "magnitude": _text(row, "magnitude", "Magnitude"),
        "shares_outstanding": shares,
        "shares_outstanding_lfy": shares,
        "revenue_status": _text(row, "revenue_status", "Revenue Status"),
        "last_price": last_price,
        "price_currency": _text(row, "price_currency", "Price Currency", "Quote Currency"),
        "price_unit": _text(row, "price_unit", "Price Unit"),
        "volume": volume,
        "fifty_two_week_low": fifty_two_week_low,
        "fifty_two_week_high": fifty_two_week_high,
        "source": SNAPSHOT_SOURCE_NAME,
        "source_url": source_url,
        "share_price_url": source_url,
        "snapshot_date": snapshot_date,
        "fetched_at": snapshot_date,
        "status": status,
        "snapshot_status": status,
        "snapshot_stale": stale,
        "notes": notes,
        "data_quality_flags": list(dict.fromkeys(flags)),
    }


def _load_snapshot_csv(path: Path, *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        snapshot_rows = [normalise_market_snapshot_row(row, now=now) for row in rows]
    return {normalize_lse_ticker(row["ticker"]): row for row in snapshot_rows if row.get("ticker")}


def _load_snapshot_json(path: Path, *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_rows = payload.get("rows") or payload.get("companies") or []
    else:
        raw_rows = payload
    snapshot_rows = [normalise_market_snapshot_row(row, now=now) for row in raw_rows if isinstance(row, dict)]
    return {normalize_lse_ticker(row["ticker"]): row for row in snapshot_rows if row.get("ticker")}


def load_market_snapshot(path: Path | str | None = None, *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    resolved = market_snapshot_path(path)
    if not resolved.exists():
        get_logger(__name__).warning("Market snapshot file not found at %s", resolved)
        return {}
    try:
        if resolved.suffix.lower() == ".json":
            rows = _load_snapshot_json(resolved, now=now)
        else:
            rows = _load_snapshot_csv(resolved, now=now)
    except Exception as exc:
        get_logger(__name__).warning("Unable to load market snapshot %s: %s", resolved, exc)
        return {}
    stale_count = sum(1 for row in rows.values() if row.get("snapshot_stale"))
    market_cap_count = sum(1 for row in rows.values() if row.get("market_cap") is not None)
    price_count = sum(1 for row in rows.values() if row.get("last_price") is not None)
    shares_count = sum(1 for row in rows.values() if row.get("shares_outstanding") not in (None, 0))
    sample_tickers = list(rows.keys())[:10]
    sample_records = {
        ticker: rows[ticker]
        for ticker in ("BHP", "RIO", "PREM")
        if ticker in rows
    }
    get_logger(__name__).info(
        "Loaded %s market snapshot rows from %s exists=%s stale=%s market_cap=%s price=%s shares=%s first_tickers=%s samples=%s",
        len(rows),
        resolved,
        resolved.exists(),
        stale_count,
        market_cap_count,
        price_count,
        shares_count,
        sample_tickers,
        sample_records,
    )
    return rows


def get_market_snapshot_for_ticker(
    ticker: str,
    snapshot: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    rows = snapshot if snapshot is not None else load_market_snapshot()
    return rows.get(normalize_lse_ticker(ticker))


def snapshot_rows_for_output(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in sorted(rows.values(), key=lambda item: (item.get("company_name") or "", item.get("ticker") or "")):
        output.append(
            {
                "Ticker": row.get("ticker", ""),
                "Company": row.get("company_name", ""),
                "Market Cap": row.get("market_cap_display", ""),
                "Market Cap Currency": row.get("market_cap_currency", ""),
                "Market Cap Numeric": row.get("market_cap_native", ""),
                "Magnitude": row.get("magnitude", ""),
                "Shares in Issue": row.get("shares_outstanding", ""),
                "Status": row.get("snapshot_status") or row.get("status", ""),
                "Primary Source": row.get("source_url", ""),
                "Snapshot Date": row.get("snapshot_date", ""),
                "Notes": row.get("notes", ""),
                "Last Price": row.get("last_price", ""),
                "Price Currency": row.get("price_currency", ""),
                "Price Unit": row.get("price_unit", ""),
                "Volume": row.get("volume", ""),
                "52 Week Low": row.get("fifty_two_week_low", ""),
                "52 Week High": row.get("fifty_two_week_high", ""),
            }
        )
    return output
