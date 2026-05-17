from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data.market_snapshot import NON_APPLICABLE_STATUSES, normalize_lse_ticker
from data.utils import CONFIG_DIR, get_logger

PARSER_VERSION = "financial_pipeline_v1"
OVERRIDES_PATH = CONFIG_DIR / "company_financial_overrides.csv"
DISPLAY_SAFE_TARGET = 0.95

KEY_FIELDS = (
    "last_price",
    "shares_outstanding",
    "market_cap",
    "revenue_status",
    "volume",
    "fifty_two_week_low",
    "fifty_two_week_high",
)

STRICT_REVENUE_STATUSES = {"reported", "confirmed_zero", "pre_revenue_confirmed", "manual"}
DISPLAY_SAFE_REVENUE_STATUSES = STRICT_REVENUE_STATUSES | {
    "likely_pre_revenue_unconfirmed",
    "not_found",
    "stale",
    "conflicting",
}
PRE_REVENUE_TERMS = ("explorer", "exploration", "developer", "development", "pre-revenue", "pre revenue")
DISPLAY_SAFE_CORE_FIELDS = ("last_price", "shares_outstanding", "market_cap", "revenue_status")
DISPLAY_SAFE_MISSING_STATUSES = {
    "not_available_gdr_zero_shares_on_source",
    "not_applicable_preference_share_no_market_cap",
}


@dataclass(frozen=True)
class Candidate:
    field: str
    value: Any
    source: str
    source_rank: int
    status: str = "reported"
    confidence: float = 0.7
    as_of_date: str | None = None
    notes: str = ""
    currency: str | None = None
    unit: str | None = None
    source_url: str | None = None


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
    for suffix, factor in (("billion", 1_000_000_000), ("bn", 1_000_000_000), ("b", 1_000_000_000), ("million", 1_000_000), ("m", 1_000_000), ("k", 1_000)):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def build_company_identity(record: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a canonical identity block from config metadata and fetched metrics."""
    record = record or {}
    metrics = metrics or {}
    ticker = normalize_lse_ticker(
        record.get("primary_ticker")
        or record.get("ticker")
        or metrics.get("source_ticker")
        or metrics.get("ticker")
        or ""
    )
    legal_name = (
        metrics.get("issuer_name")
        or record.get("legal_name")
        or record.get("company_name")
        or record.get("name")
        or ticker
    )
    display_name = record.get("display_name") or record.get("company_name") or metrics.get("issuer_name") or legal_name
    exchange = record.get("exchange") or metrics.get("market") or ""
    lse_slug = record.get("lse_slug") or _slugify(str(legal_name))
    return {
        "company_id": record.get("company_id") or f"{exchange or 'UNKNOWN'}:{ticker}",
        "display_name": display_name,
        "legal_name": legal_name,
        "primary_ticker": ticker,
        "exchange": exchange,
        "mic": record.get("mic") or metrics.get("mic") or "",
        "isin": metrics.get("isin") or record.get("isin") or "",
        "sedol": record.get("sedol") or metrics.get("sedol") or "",
        "figi": record.get("figi") or "",
        "share_class_figi": record.get("share_class_figi") or "",
        "quote_currency": metrics.get("price_currency") or metrics.get("currency") or record.get("quote_currency") or "",
        "reporting_currency": record.get("reporting_currency") or metrics.get("reporting_currency") or "",
        "lse_issuer_code": metrics.get("issuer_code") or record.get("lse_issuer_code") or "",
        "lse_slug": lse_slug,
        "yahoo_symbol": record.get("yahoo_symbol") or f"{ticker}.L",
        "company_stage": record.get("company_stage") or record.get("stage") or "",
        "manual_review_status": record.get("manual_review_status") or "",
    }


def _slugify(value: str) -> str:
    text = value.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "company"


def price_unit(currency: str | None, explicit_unit: str | None = None) -> str:
    unit = str(explicit_unit or "").strip()
    if unit:
        return unit
    currency_text = str(currency or "").strip().lower()
    if currency_text in {"gbx", "gbpence", "gbp pence", "pence", "gbpenny"}:
        return "GBp"
    if currency_text in {"gbp", "£"}:
        return "GBP"
    return str(currency or "").strip() or "unknown"


def normalize_price(value: Any, currency: str | None, unit: str | None = None) -> tuple[float | None, str | None, str | None]:
    price = _to_float(value)
    if price is None or price <= 0:
        return None, None, None
    resolved_unit = price_unit(currency, unit)
    if resolved_unit == "GBp" or str(currency or "").upper() == "GBX":
        return price / 100, "GBP", "GBp"
    if resolved_unit.upper() == "GBP" or resolved_unit == "£":
        return price, "GBP", resolved_unit
    normalized_currency = str(currency or "").upper() or None
    return price, normalized_currency, resolved_unit if normalized_currency else None


def compute_market_cap(last_price: Any, shares_outstanding: Any, currency: str | None, unit: str | None = None) -> tuple[float | None, dict[str, Any]]:
    normalized_price, normalized_currency, resolved_unit = normalize_price(last_price, currency, unit)
    shares = _to_float(shares_outstanding)
    if normalized_price is None or shares is None or shares <= 0:
        return None, {
            "normalized_price": normalized_price,
            "normalized_price_currency": normalized_currency,
            "price_unit": resolved_unit,
        }
    return normalized_price * shares, {
        "normalized_price": normalized_price,
        "normalized_price_currency": normalized_currency,
        "price_unit": resolved_unit,
    }


def _candidate(candidates: dict[str, list[Candidate]], field: str, value: Any, source: str, source_rank: int, **kwargs: Any) -> None:
    if not _present(value):
        return
    candidates.setdefault(field, []).append(Candidate(field=field, value=value, source=source, source_rank=source_rank, **kwargs))


def _best(candidates: dict[str, list[Candidate]], field: str) -> Candidate | None:
    values = candidates.get(field, [])
    if not values:
        return None
    return sorted(values, key=lambda item: (item.source_rank, -item.confidence))[0]


def _add_source_candidates(candidates: dict[str, list[Candidate]], source_key: str, payload: dict[str, Any]) -> None:
    fetched_at = payload.get("retrieved") or payload.get("retrieved_yahoo") or payload.get("fetched_at")
    if source_key == "market_snapshot":
        source = "company market snapshot"
        status = payload.get("status") or payload.get("snapshot_status") or "reported"
        source_url = payload.get("source_url") or payload.get("share_price_url")
        notes = payload.get("notes") or ""
        _candidate(
            candidates,
            "last_price",
            payload.get("last_price"),
            source,
            2,
            status=status,
            confidence=0.82,
            as_of_date=payload.get("snapshot_date") or fetched_at,
            currency=payload.get("price_currency"),
            unit=payload.get("price_unit"),
            source_url=source_url,
            notes=notes,
        )
        _candidate(
            candidates,
            "price_currency",
            payload.get("price_currency"),
            source,
            2,
            status=status,
            confidence=0.82,
            as_of_date=payload.get("snapshot_date") or fetched_at,
            source_url=source_url,
            notes=notes,
        )
        _candidate(candidates, "volume", payload.get("volume"), source, 2, status=status, confidence=0.8, as_of_date=payload.get("snapshot_date") or fetched_at, source_url=source_url, notes=notes)
        _candidate(
            candidates,
            "market_cap_vendor",
            payload.get("market_cap") or payload.get("market_cap_native"),
            source,
            2,
            status=status,
            confidence=0.86,
            as_of_date=payload.get("snapshot_date") or fetched_at,
            currency=payload.get("market_cap_currency"),
            source_url=source_url,
            notes=notes,
        )
        _candidate(
            candidates,
            "shares_outstanding",
            payload.get("shares_outstanding") or payload.get("shares_outstanding_lfy"),
            source,
            2,
            status=status,
            confidence=0.84,
            as_of_date=payload.get("snapshot_date") or fetched_at,
            source_url=source_url,
            notes=notes,
        )
        _candidate(candidates, "fifty_two_week_low", payload.get("fifty_two_week_low"), source, 2, status=status, confidence=0.8, as_of_date=payload.get("snapshot_date") or fetched_at, source_url=source_url, notes=notes)
        _candidate(candidates, "fifty_two_week_high", payload.get("fifty_two_week_high"), source, 2, status=status, confidence=0.8, as_of_date=payload.get("snapshot_date") or fetched_at, source_url=source_url, notes=notes)
        _candidate(candidates, "revenue_status", payload.get("revenue_status"), source, 2, status=status, confidence=0.7, as_of_date=payload.get("snapshot_date") or fetched_at, source_url=source_url, notes=notes)
    elif source_key == "lse":
        rank = 3
        source = "LSE official/API/PDF"
        _candidate(candidates, "last_price", payload.get("last_price"), source, 1, confidence=0.95, as_of_date=payload.get("last_price_date") or fetched_at, currency=payload.get("currency"))
        _candidate(candidates, "price_currency", payload.get("currency"), source, 1, confidence=0.95, as_of_date=fetched_at)
        _candidate(candidates, "volume", payload.get("volume"), source, 1, confidence=0.9, as_of_date=fetched_at)
        _candidate(candidates, "market_cap_vendor", payload.get("market_cap"), source, rank, confidence=0.9, as_of_date=fetched_at)
        _candidate(candidates, "shares_outstanding", payload.get("shares_outstanding") or payload.get("shares_outstanding_lfy"), source, 2, confidence=0.88, as_of_date=fetched_at)
        _candidate(candidates, "revenue", payload.get("revenue_lfy"), source, 1, confidence=0.85, as_of_date=fetched_at)
        _candidate(candidates, "total_debt", payload.get("total_debt"), source, 1, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "debt_to_equity", payload.get("net_debt_to_equity_pct"), source, 2, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "long_term_debt_to_capital_pct", payload.get("long_term_debt_to_capital_pct"), source, 1, confidence=0.85, as_of_date=fetched_at)
        _candidate(candidates, "price_to_sales", payload.get("price_to_sales"), source, 2, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "price_to_book", payload.get("price_to_book"), source, 2, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_low", payload.get("fifty_two_week_low"), source, 1, confidence=0.9, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_high", payload.get("fifty_two_week_high"), source, 1, confidence=0.9, as_of_date=fetched_at)
        for field in ("isin", "market", "segment", "sector", "subsector", "country"):
            source_field = {"sector": "ftse_sector", "subsector": "ftse_subsector", "country": "country_of_incorporation"}.get(field, field)
            _candidate(candidates, field, payload.get(source_field), source, 1, confidence=0.85, as_of_date=fetched_at)
    elif source_key == "yahoo":
        source = "Yahoo Finance fallback"
        _candidate(candidates, "last_price", payload.get("last_price"), source, 2, confidence=0.75, as_of_date=fetched_at, currency=payload.get("currency"))
        _candidate(candidates, "price_currency", payload.get("currency"), source, 2, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "volume", payload.get("volume"), source, 2, confidence=0.7, as_of_date=fetched_at)
        _candidate(candidates, "market_cap_vendor", payload.get("market_cap"), source, 5, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "shares_outstanding", payload.get("shares_outstanding") or payload.get("shares_outstanding_lfy") or payload.get("impliedSharesOutstanding"), source, 4, confidence=0.7, as_of_date=fetched_at)
        _candidate(candidates, "revenue", payload.get("revenue_lfy"), source, 4, confidence=0.65, as_of_date=fetched_at, notes="trailing revenue fallback")
        _candidate(candidates, "total_debt", payload.get("total_debt"), source, 4, confidence=0.65, as_of_date=fetched_at)
        _candidate(candidates, "debt_to_equity", payload.get("net_debt_to_equity_pct"), source, 4, confidence=0.65, as_of_date=fetched_at)
        _candidate(candidates, "price_to_sales", payload.get("price_to_sales"), source, 4, confidence=0.65, as_of_date=fetched_at)
        _candidate(candidates, "price_to_book", payload.get("price_to_book"), source, 4, confidence=0.65, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_low", payload.get("fifty_two_week_low"), source, 2, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_high", payload.get("fifty_two_week_high"), source, 2, confidence=0.72, as_of_date=fetched_at)
    elif source_key == "london_south_east_share":
        source = "London South East share page"
        _candidate(candidates, "last_price", payload.get("last_price"), source, 4, confidence=0.75, as_of_date=fetched_at, currency=payload.get("currency"))
        _candidate(candidates, "price_currency", payload.get("currency"), source, 4, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "volume", payload.get("volume"), source, 4, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "market_cap_vendor", payload.get("market_cap"), source, 6, confidence=0.75, as_of_date=fetched_at)
        _candidate(candidates, "shares_outstanding", payload.get("shares_outstanding") or payload.get("shares_outstanding_lfy"), source, 5, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_low", payload.get("fifty_two_week_low"), source, 4, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_high", payload.get("fifty_two_week_high"), source, 4, confidence=0.72, as_of_date=fetched_at)
        _candidate(candidates, "country", payload.get("country"), source, 4, confidence=0.65, as_of_date=fetched_at)
    elif source_key == "metadata":
        source = str(payload.get("source") or "metadata")
        _candidate(candidates, "last_price", payload.get("last_price"), source, 5, confidence=0.55, as_of_date=fetched_at, currency=payload.get("currency"))
        _candidate(candidates, "price_currency", payload.get("currency"), source, 5, confidence=0.55, as_of_date=fetched_at)
        _candidate(candidates, "volume", payload.get("volume"), source, 5, confidence=0.55, as_of_date=fetched_at)
        _candidate(candidates, "market_cap_vendor", payload.get("market_cap"), source, 7, confidence=0.55, as_of_date=fetched_at)
        _candidate(candidates, "shares_outstanding", payload.get("shares_outstanding") or payload.get("shares_outstanding_lfy"), source, 5, confidence=0.55, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_low", payload.get("fifty_two_week_low"), source, 5, confidence=0.55, as_of_date=fetched_at)
        _candidate(candidates, "fifty_two_week_high", payload.get("fifty_two_week_high"), source, 5, confidence=0.55, as_of_date=fetched_at)
        for field in ("market", "segment", "sector", "subsector", "country"):
            _candidate(candidates, field, payload.get(field), source, 5, confidence=0.5, as_of_date=fetched_at)


def _field_dict(candidate: Candidate | None, status: str = "not_found") -> dict[str, Any]:
    if candidate is None:
        return {
            "value": None,
            "source": "not_found",
            "source_rank": 999,
            "as_of_date": None,
            "status": status,
            "confidence": 0.0,
            "notes": "",
        }
    return {
        "value": candidate.value,
        "source": candidate.source,
        "source_rank": candidate.source_rank,
        "as_of_date": candidate.as_of_date,
        "status": candidate.status,
        "confidence": candidate.confidence,
        "notes": candidate.notes,
        "currency": candidate.currency,
        "unit": candidate.unit,
        "source_url": candidate.source_url,
    }


def classify_revenue_status(value: Any, identity: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[str, str]:
    revenue = _to_float(value)
    if revenue is not None:
        if revenue > 0:
            return "reported", ""
        return "confirmed_zero", "No operating revenue reported"
    haystack = " ".join(
        str(part or "")
        for part in (
            identity.get("company_stage"),
            sources.get("metadata", {}).get("stage"),
            sources.get("metadata", {}).get("supply_chain_role"),
            sources.get("metadata", {}).get("notes"),
        )
    ).lower()
    if any(term in haystack for term in PRE_REVENUE_TERMS):
        return "likely_pre_revenue_unconfirmed", "Likely pre-revenue — not confirmed"
    return "not_found", "Revenue not found"


def load_manual_overrides(path: Path = OVERRIDES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("field") and row.get("value")]


def _override_matches(row: dict[str, Any], identity: dict[str, Any]) -> bool:
    company_id = str(row.get("company_id") or "").strip()
    ticker = normalize_lse_ticker(row.get("ticker"))
    return bool(
        (company_id and company_id == str(identity.get("company_id")))
        or (ticker and ticker == normalize_lse_ticker(identity.get("primary_ticker")))
    )


def _apply_manual_overrides(snapshot: dict[str, Any], identity: dict[str, Any], overrides: list[dict[str, Any]]) -> None:
    fields = snapshot["field_provenance"]
    notes = snapshot["data_notes"]
    flags = snapshot["data_quality_flags"]
    for row in overrides:
        if not _override_matches(row, identity):
            continue
        field = str(row.get("field") or "").strip()
        if not field:
            continue
        existing = fields.get(field, {})
        confidence = _to_float(row.get("confidence")) or 0.75
        explicit = "force" in str(row.get("notes") or "").lower() or confidence >= 0.95
        if existing.get("value") not in (None, "") and not explicit:
            notes.append(f"Manual override for {field} present but not applied over populated automated value")
            continue
        value: Any = row.get("value")
        if field not in {"revenue_status", "price_currency", "quote_currency", "reporting_currency", "revenue_display"}:
            numeric = _to_float(value)
            value = numeric if numeric is not None else value
        snapshot[field] = value
        fields[field] = {
            "value": value,
            "source": row.get("source_name") or "manual override",
            "source_rank": 0,
            "as_of_date": row.get("as_of_date") or row.get("last_verified"),
            "status": "manual",
            "confidence": confidence,
            "notes": row.get("notes") or "",
            "source_url": row.get("source_url") or "",
        }
        notes.append(f"{field} manual override used")
        flags.append("manual_override_used")


def normalise_company_financials(
    identity: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    *,
    overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates: dict[str, list[Candidate]] = {}
    for source_key, payload in sources.items():
        if isinstance(payload, dict):
            _add_source_candidates(candidates, source_key, payload)

    field_provenance: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    flags: list[str] = []
    snapshot: dict[str, Any] = {
        "company_identity": identity,
        "field_provenance": field_provenance,
        "data_quality_flags": flags,
        "data_notes": notes,
        "retrieved": _first_present_source_value(sources, "retrieved", "retrieved_yahoo", "fetched_at"),
    }

    for field in (
        "last_price",
        "price_currency",
        "volume",
        "shares_outstanding",
        "revenue",
        "revenue_status",
        "total_debt",
        "debt_to_equity",
        "long_term_debt_to_capital_pct",
        "price_to_sales",
        "price_to_book",
        "fifty_two_week_low",
        "fifty_two_week_high",
        "isin",
        "market",
        "segment",
        "sector",
        "subsector",
        "country",
    ):
        candidate = _best(candidates, field)
        if candidate and field in {
            "last_price",
            "volume",
            "shares_outstanding",
            "revenue",
            "total_debt",
            "debt_to_equity",
            "long_term_debt_to_capital_pct",
            "price_to_sales",
            "price_to_book",
            "fifty_two_week_low",
            "fifty_two_week_high",
        }:
            snapshot[field] = _to_float(candidate.value)
        else:
            snapshot[field] = candidate.value if candidate else None
        field_provenance[field] = _field_dict(candidate)

    market_snapshot = sources.get("market_snapshot", {})
    snapshot_status = str(market_snapshot.get("snapshot_status") or market_snapshot.get("status") or "").lower()
    if market_snapshot:
        for flag in market_snapshot.get("data_quality_flags") or []:
            flags.append(str(flag))
        if market_snapshot.get("snapshot_stale"):
            notes.append("Market snapshot is stale")
        if snapshot_status in NON_APPLICABLE_STATUSES:
            notes.append(f"Market snapshot status: {snapshot_status}")

    price = snapshot.get("last_price")
    price_currency = snapshot.get("price_currency") or identity.get("quote_currency") or sources.get("metadata", {}).get("currency")
    shares = snapshot.get("shares_outstanding")
    computed_market_cap, price_meta = compute_market_cap(price, shares, price_currency)
    snapshot.update(price_meta)
    snapshot["price_unit"] = price_meta.get("price_unit")
    snapshot["normalized_price"] = price_meta.get("normalized_price")
    snapshot["normalized_price_currency"] = price_meta.get("normalized_price_currency")

    vendor_cap = _best(candidates, "market_cap_vendor")
    vendor_value = _to_float(vendor_cap.value) if vendor_cap else None
    if computed_market_cap is not None and price_meta.get("normalized_price_currency"):
        snapshot["market_cap"] = computed_market_cap
        field_provenance["market_cap"] = {
            "value": computed_market_cap,
            "source": "computed price x shares",
            "source_rank": 0,
            "as_of_date": field_provenance.get("last_price", {}).get("as_of_date"),
            "status": "computed",
            "confidence": min(
                field_provenance.get("last_price", {}).get("confidence", 0.7),
                field_provenance.get("shares_outstanding", {}).get("confidence", 0.7),
            ),
            "currency": price_meta.get("normalized_price_currency"),
            "unit": None,
            "source_url": field_provenance.get("last_price", {}).get("source_url")
            or field_provenance.get("shares_outstanding", {}).get("source_url"),
            "notes": "market_cap = normalized_last_price * shares_outstanding",
        }
        flags.append("market_cap_computed")
        notes.append("Market cap computed from normalized price x shares outstanding")
        if vendor_value and vendor_value > 0:
            delta = abs(computed_market_cap - vendor_value) / vendor_value
            snapshot["market_cap_vendor"] = vendor_value
            snapshot["market_cap_vendor_delta_pct"] = round(delta * 100, 2)
            if delta > 0.15:
                flags.append("market_cap_vendor_conflict")
                notes.append(f"Computed market cap differs from vendor value by {delta:.0%}")
    elif vendor_value is not None and vendor_value > 0:
        snapshot["market_cap"] = vendor_value
        field_provenance["market_cap"] = _field_dict(vendor_cap)
    else:
        snapshot["market_cap"] = None
        if market_snapshot and snapshot_status in NON_APPLICABLE_STATUSES:
            field_provenance["market_cap"] = {
                "value": None,
                "source": "company market snapshot",
                "source_rank": 2,
                "as_of_date": market_snapshot.get("snapshot_date") or market_snapshot.get("fetched_at"),
                "status": snapshot_status,
                "confidence": 0.8,
                "currency": market_snapshot.get("market_cap_currency"),
                "unit": None,
                "source_url": market_snapshot.get("source_url"),
                "notes": market_snapshot.get("notes") or "",
            }
        else:
            field_provenance["market_cap"] = _field_dict(None)
            flags.append("missing_market_cap")

    supplied_revenue_status = snapshot.get("revenue_status")
    revenue_status, revenue_display = (
        (str(supplied_revenue_status), "")
        if _present(supplied_revenue_status)
        else classify_revenue_status(snapshot.get("revenue"), identity, sources)
    )
    snapshot["revenue_status"] = revenue_status
    snapshot["revenue_display"] = revenue_display
    revenue_status_source = field_provenance.get("revenue_status") if _present(supplied_revenue_status) else None
    field_provenance["revenue_status"] = {
        "value": revenue_status,
        "source": (revenue_status_source or field_provenance.get("revenue", {})).get("source", "classification"),
        "source_rank": (revenue_status_source or field_provenance.get("revenue", {})).get("source_rank", 999),
        "as_of_date": (revenue_status_source or field_provenance.get("revenue", {})).get("as_of_date"),
        "status": revenue_status,
        "confidence": (revenue_status_source or field_provenance.get("revenue", {})).get("confidence", 0.4),
        "notes": revenue_display,
    }
    if revenue_status == "likely_pre_revenue_unconfirmed":
        flags.append("likely_pre_revenue_unconfirmed")
    elif revenue_status == "not_found":
        flags.append("revenue_not_found")

    if not snapshot.get("last_price"):
        flags.append("missing_price")
    if not snapshot.get("shares_outstanding"):
        if market_snapshot and snapshot_status in NON_APPLICABLE_STATUSES:
            field_provenance["shares_outstanding"] = {
                "value": None,
                "source": "company market snapshot",
                "source_rank": 2,
                "as_of_date": market_snapshot.get("snapshot_date") or market_snapshot.get("fetched_at"),
                "status": snapshot_status,
                "confidence": 0.8,
                "currency": None,
                "unit": None,
                "source_url": market_snapshot.get("source_url"),
                "notes": market_snapshot.get("notes") or "",
            }
        else:
            flags.append("missing_shares_outstanding")
    if not snapshot.get("price_currency"):
        flags.append("currency_unit_ambiguous")

    for payload in sources.values():
        for key, value in payload.items():
            if key not in snapshot and _present(value):
                snapshot[key] = value

    _apply_manual_overrides(snapshot, identity, overrides if overrides is not None else load_manual_overrides())
    _append_source_notes(snapshot)
    _finalise_coverage(snapshot)
    _add_compatibility_aliases(snapshot)
    return snapshot


def _add_compatibility_aliases(snapshot: dict[str, Any]) -> None:
    snapshot["currency"] = snapshot.get("price_currency")
    snapshot["shares_outstanding_lfy"] = snapshot.get("shares_outstanding")
    snapshot["revenue_lfy"] = snapshot.get("revenue")
    snapshot["net_debt_to_equity_pct"] = snapshot.get("debt_to_equity")
    snapshot["source"] = _source_summary(snapshot)
    snapshot["data_fallbacks"] = list(dict.fromkeys(snapshot.get("data_notes", [])))


def _first_present_source_value(sources: dict[str, dict[str, Any]], *keys: str) -> Any:
    for payload in sources.values():
        for key in keys:
            if _present(payload.get(key)):
                return payload.get(key)
    return None


def _source_summary(snapshot: dict[str, Any]) -> str:
    sources = []
    for field in ("market_cap", "last_price", "shares_outstanding", "revenue_status"):
        source = snapshot.get("field_provenance", {}).get(field, {}).get("source")
        if source and source != "not_found":
            sources.append(source)
    return " + ".join(dict.fromkeys(sources)) or "not_found"


def _append_source_notes(snapshot: dict[str, Any]) -> None:
    notes = snapshot.get("data_notes", [])
    flags = snapshot.get("data_quality_flags", [])
    for field in ("market_cap", "last_price", "shares_outstanding", "volume", "fifty_two_week_low", "fifty_two_week_high"):
        provenance = snapshot.get("field_provenance", {}).get(field, {})
        source = provenance.get("source")
        if source == "company market snapshot":
            status = provenance.get("status") or "reported"
            notes.append(f"{field} from company market snapshot ({status})")
            if field == "market_cap":
                flags.append("market_cap_snapshot_used")
    snapshot["data_notes"] = list(dict.fromkeys(notes))
    snapshot["data_quality_flags"] = list(dict.fromkeys(flags))


def _field_populated(snapshot: dict[str, Any], field: str, *, strict: bool) -> bool:
    if field == "revenue_status":
        statuses = STRICT_REVENUE_STATUSES if strict else DISPLAY_SAFE_REVENUE_STATUSES
        return snapshot.get("revenue_status") in statuses
    provenance = snapshot.get("field_provenance", {}).get(field, {})
    status = provenance.get("status")
    if not strict and status in DISPLAY_SAFE_MISSING_STATUSES:
        return True
    if field == "fifty_two_week_high":
        return _present(snapshot.get("fifty_two_week_high"))
    if field == "fifty_two_week_low":
        return _present(snapshot.get("fifty_two_week_low"))
    return _present(snapshot.get(field))


def _finalise_coverage(snapshot: dict[str, Any]) -> None:
    strict = {field: _field_populated(snapshot, field, strict=True) for field in KEY_FIELDS}
    display = {field: _field_populated(snapshot, field, strict=False) for field in KEY_FIELDS}
    snapshot["strict_coverage_ratio"] = round(sum(strict.values()) / len(strict), 3)
    snapshot["display_safe_coverage_ratio"] = round(sum(display.values()) / len(display), 3)
    snapshot["data_coverage_ratio"] = snapshot["display_safe_coverage_ratio"]
    snapshot["coverage_fields"] = {"strict": strict, "display_safe": display}


def _field_excluded_from_coverage(metrics: dict[str, Any], field: str) -> bool:
    if field not in {"market_cap", "shares_outstanding"}:
        return False
    status = metrics.get("field_provenance", {}).get(field, {}).get("status")
    return status in NON_APPLICABLE_STATUSES


def financial_cache_state(
    path: Path,
    *,
    ttl: timedelta,
    negative_ttl: timedelta = timedelta(hours=24),
    parser_version: str = PARSER_VERSION,
) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "stale"
    if payload.get("parser_version") != parser_version:
        return "parser_stale"
    fetched_at_text = payload.get("fetched_at")
    try:
        fetched_at = datetime.fromisoformat(str(fetched_at_text))
    except Exception:
        return "stale"
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    if payload.get("negative_cache_reason"):
        return "fresh_negative" if age < negative_ttl else "expired_negative"
    return "fresh" if age < ttl else "stale"


def coverage_audit(stocks: list[dict[str, Any]], target: float = DISPLAY_SAFE_TARGET) -> dict[str, Any]:
    universe_count = len(stocks)
    field_counts = {field: 0 for field in KEY_FIELDS}
    field_eligible_counts = {field: 0 for field in KEY_FIELDS}
    strict_count = 0
    display_count = 0
    failures: dict[str, list[str]] = {field: [] for field in KEY_FIELDS}
    for stock in stocks:
        metrics = stock.get("fundamental", {}).get("metrics", stock.get("metrics", {}))
        name = stock.get("name") or stock.get("ticker") or metrics.get("company_identity", {}).get("display_name") or "unknown"
        strict_fields = metrics.get("coverage_fields", {}).get("strict")
        display_fields = metrics.get("coverage_fields", {}).get("display_safe")
        if not strict_fields or not display_fields:
            _finalise_coverage(metrics)
            strict_fields = metrics.get("coverage_fields", {}).get("strict", {})
            display_fields = metrics.get("coverage_fields", {}).get("display_safe", {})
        row_strict_ok = True
        row_display_ok = True
        for field in KEY_FIELDS:
            if _field_excluded_from_coverage(metrics, field):
                continue
            field_eligible_counts[field] += 1
            if display_fields.get(field):
                field_counts[field] += 1
            else:
                failures[field].append(str(name))
                if field in DISPLAY_SAFE_CORE_FIELDS:
                    row_display_ok = False
            if not strict_fields.get(field):
                row_strict_ok = False
        if row_strict_ok:
            strict_count += 1
        if row_display_ok:
            display_count += 1

    def ratio(count: int, denominator: int | None = None) -> float:
        denominator = universe_count if denominator is None else denominator
        return round(count / denominator, 4) if denominator else 0.0

    audit = {
        "universe_count": universe_count,
        "field_coverage": {
            field: {
                "count": count,
                "eligible_count": field_eligible_counts[field],
                "ratio": ratio(count, field_eligible_counts[field]),
            }
            for field, count in field_counts.items()
        },
        "strict_full_coverage": {"count": strict_count, "ratio": ratio(strict_count)},
        "display_safe_coverage": {"count": display_count, "ratio": ratio(display_count)},
        "target": target,
        "passed": ratio(display_count) >= target,
        "failures": failures,
    }
    audit["missing_by_field"] = failures
    audit["market_cap_coverage"] = audit["field_coverage"]["market_cap"]
    audit["price_coverage"] = audit["field_coverage"]["last_price"]
    audit["shares_outstanding_coverage"] = audit["field_coverage"]["shares_outstanding"]
    audit["revenue_status_coverage"] = audit["field_coverage"]["revenue_status"]
    audit["summary"] = coverage_audit_summary(audit)
    return audit


def coverage_audit_summary(audit: dict[str, Any]) -> str:
    lines = [f"Universe: {audit['universe_count']} companies"]
    labels = {
        "last_price": "Price coverage",
        "shares_outstanding": "Shares outstanding coverage",
        "market_cap": "Market cap coverage",
        "revenue_status": "Revenue status coverage",
        "volume": "Volume coverage",
        "fifty_two_week_low": "52-week low coverage",
        "fifty_two_week_high": "52-week high coverage",
    }
    for field, label in labels.items():
        item = audit["field_coverage"][field]
        lines.append(f"{label}: {item['count']} / {item['eligible_count']} = {item['ratio']:.1%}")
    strict = audit["strict_full_coverage"]
    display = audit["display_safe_coverage"]
    lines.append(f"Strict full coverage: {strict['count']} / {audit['universe_count']} = {strict['ratio']:.1%}")
    lines.append(f"Display-safe coverage: {display['count']} / {audit['universe_count']} = {display['ratio']:.1%}")
    lines.append(f"Display-safe target: {'PASS' if audit['passed'] else 'FAIL'} >= {audit['target']:.0%}")
    return "\n".join(lines)
