from __future__ import annotations

from functools import lru_cache
from typing import Any

from data.market_snapshot import get_market_snapshot_for_ticker, load_market_snapshot

TABLE_COLUMNS = [
    "Company",
    "Ticker",
    "Alias",
    "Exchange",
    "Country",
    "Role",
    "Segment",
    "Score",
    "Score Status",
    "Full Score",
    "Prelim Score",
    "Tech Score",
    "Commercial Score",
    "Strategic Score",
    "Benchmark Score",
    "Confidence",
    "Confidence Level",
    "Data Coverage",
    "Rating",
    "Peer Group",
    "Market Cap",
    "Last Price",
    "Revenue LFY",
    "Debt Metric",
    "Shares Outstanding",
    "Volume",
    "52W Range",
    "Mineralogy",
    "Recovery",
    "Study Stage",
    "Resource Confidence",
    "Impurity Profile",
    "Technical Source",
    "Commodity",
    "Stage Gates",
    "Missing Data",
    "Drivers",
    "Positive Drivers",
    "Negative Drivers",
    "Data Notes",
    "Source",
    "Retrieved UTC",
]

SEARCH_COLUMNS = [
    "Ticker",
    "Company",
    "Exchange",
    "Country",
    "Commodity",
    "Role",
    "Stage",
    "Prelim Score",
    "Source",
]

MISSING_DISPLAY_VALUES = {
    "",
    "-",
    "n/a",
    "na",
    "none",
    "null",
    "not found",
    "not found after fallback",
    "not loaded",
}


@lru_cache(maxsize=1)
def _market_snapshot_rows() -> dict[str, dict[str, Any]]:
    return load_market_snapshot()


def _fill_from_market_snapshot(metrics: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Final table safety net: fill broad-market fields directly from the CSV snapshot."""
    snapshot = get_market_snapshot_for_ticker(ticker, _market_snapshot_rows())
    if not snapshot:
        return metrics

    filled = dict(metrics)
    provenance = dict(filled.get("field_provenance") or {})
    notes = list(filled.get("data_fallbacks") or filled.get("data_notes") or [])
    status = snapshot.get("snapshot_status") or snapshot.get("status") or "reported"

    field_map = {
        "market_cap": ("market_cap", "market_cap"),
        "last_price": ("last_price", "last_price"),
        "shares_outstanding_lfy": ("shares_outstanding", "shares_outstanding"),
        "volume": ("volume", "volume"),
        "fifty_two_week_low": ("fifty_two_week_low", "fifty_two_week_low"),
        "fifty_two_week_high": ("fifty_two_week_high", "fifty_two_week_high"),
    }
    for display_field, (snapshot_field, provenance_field) in field_map.items():
        value = snapshot.get(snapshot_field)
        if provenance_field in {"market_cap", "shares_outstanding"} and status in {
            "not_applicable_preference_share_no_market_cap",
            "not_available_gdr_zero_shares_on_source",
        }:
            value = None
        if _is_missing_value(filled.get(display_field)) and value is not None:
            filled[display_field] = value
            notes.append(f"{display_field} from company_market_snapshot.csv ({status})")
            provenance[provenance_field] = {
                "value": value,
                "source": "company_market_snapshot.csv",
                "source_rank": 2,
                "as_of_date": snapshot.get("snapshot_date"),
                "status": status,
                "confidence": 0.86,
                "notes": snapshot.get("notes") or "",
                "source_url": snapshot.get("source_url") or "",
            }
    if _is_missing_value(filled.get("currency")) and not _is_missing_value(snapshot.get("price_currency")):
        filled["currency"] = snapshot.get("price_currency")

    for field in ("market_cap", "shares_outstanding"):
        if field not in provenance and status in {
            "not_applicable_preference_share_no_market_cap",
            "not_available_gdr_zero_shares_on_source",
            "found_suspended_security",
            "stale",
            "conflicting",
        }:
            provenance[field] = {
                "value": None,
                "source": "company_market_snapshot.csv",
                "source_rank": 2,
                "as_of_date": snapshot.get("snapshot_date"),
                "status": status,
                "confidence": 0.8,
                "notes": snapshot.get("notes") or "",
                "source_url": snapshot.get("source_url") or "",
            }

    if not filled.get("source") or filled.get("source") in {"Unknown", "not_found"}:
        filled["source"] = "company_market_snapshot.csv"
    elif "company_market_snapshot.csv" not in str(filled.get("source")):
        filled["source"] = f"{filled['source']} + company_market_snapshot.csv"

    filled["field_provenance"] = provenance
    filled["data_fallbacks"] = list(dict.fromkeys(notes))
    return filled


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "-", "n/a", "na", "none", "null", "not found"}
    return False


def _is_missing_display_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_DISPLAY_VALUES
    return False


def _format_money(value: Any) -> str:
    if _is_missing_value(value):
        return "Not found"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    for suffix, divisor in (
        ("T", 1_000_000_000_000),
        ("B", 1_000_000_000),
        ("M", 1_000_000),
        ("K", 1_000),
    ):
        if abs(number) >= divisor:
            return f"{number / divisor:.1f}{suffix}"
    return f"{number:,.0f}"


def _field_status(metrics: dict[str, Any], field: str) -> str:
    return str(metrics.get("field_provenance", {}).get(field, {}).get("status") or "").lower()


def _format_missing_market_field(metrics: dict[str, Any], field: str, default: str = "Not found") -> str:
    status = _field_status(metrics, field)
    if status == "not_applicable_preference_share_no_market_cap":
        return "Not applicable - preference share"
    if status == "not_available_gdr_zero_shares_on_source":
        return "Not available - GDR source shows zero shares"
    if status == "found_suspended_security":
        return "Suspended security"
    if status == "stale":
        return "Stale snapshot"
    if status == "conflicting":
        return "Conflicting sources"
    return default


def _format_market_cap(metrics: dict[str, Any]) -> str:
    status = _field_status(metrics, "market_cap")
    if status in {
        "not_applicable_preference_share_no_market_cap",
        "not_available_gdr_zero_shares_on_source",
        "found_suspended_security",
        "stale",
        "conflicting",
    } and _is_missing_value(metrics.get("market_cap")):
        return _format_missing_market_field(metrics, "market_cap")
    value = metrics.get("market_cap")
    if value is None:
        return _format_missing_market_field(metrics, "market_cap")
    return _format_money(value)


def _format_number(value: Any) -> str:
    if _is_missing_value(value):
        return "Not found"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= divisor:
            return f"{number / divisor:.1f}{suffix}"
    return f"{number:,.0f}"


def _format_shares(metrics: dict[str, Any]) -> str:
    status = _field_status(metrics, "shares_outstanding")
    if status in {
        "not_applicable_preference_share_no_market_cap",
        "not_available_gdr_zero_shares_on_source",
    }:
        return _format_missing_market_field(metrics, "shares_outstanding")
    value = metrics.get("shares_outstanding_lfy")
    if value is None:
        return _format_missing_market_field(metrics, "shares_outstanding")
    return _format_number(value)


def _format_price(value: Any, currency: str | None = None) -> str:
    if _is_missing_value(value):
        return "Not found"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    suffix = f" {currency}" if currency else ""
    return f"{number:g}{suffix}"


def _format_last_price(metrics: dict[str, Any]) -> str:
    value = metrics.get("last_price")
    if value is None:
        return _format_missing_market_field(metrics, "last_price")
    return _format_price(value, metrics.get("currency"))


def _format_percent(value: Any) -> str:
    if _is_missing_value(value):
        return "Not found"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_coverage(value: Any) -> str:
    if value is None:
        return "Not assessed"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_debt_metric(metrics: dict[str, Any]) -> str:
    debt_to_capital = metrics.get("long_term_debt_to_capital_pct")
    if debt_to_capital is not None:
        return f"{float(debt_to_capital):.1f}% LT debt/cap"

    net_debt_to_equity = metrics.get("net_debt_to_equity_pct")
    if net_debt_to_equity is not None:
        return f"{float(net_debt_to_equity):.1f}% net debt/equity"

    return "Not found after fallback"


def _format_revenue(metrics: dict[str, Any]) -> str:
    revenue = metrics.get("revenue_lfy")
    if revenue is not None:
        try:
            if float(revenue) == 0:
                return "No operating revenue reported"
        except (TypeError, ValueError):
            pass
        return _format_money(revenue)

    status = str(metrics.get("revenue_status") or "").lower()
    if status == "confirmed_zero":
        return "No operating revenue reported"
    if status == "pre_revenue_confirmed":
        return "Pre-revenue confirmed"
    if status == "likely_pre_revenue_unconfirmed":
        return "Likely pre-revenue - not confirmed"
    if status == "stale":
        return "Revenue stale"
    if status == "conflicting":
        return "Revenue conflicting"
    return "Revenue not found"


def _format_range(low: Any, high: Any) -> str:
    if _is_missing_value(low) or _is_missing_value(high):
        return "Not found"
    return f"{float(low):g} - {float(high):g}"


def _rating(score: float) -> str:
    if score >= 7.5:
        return "High-quality / advanced"
    if score >= 6.0:
        return "Strong watchlist"
    if score >= 4.5:
        return "Developing opportunity"
    if score >= 3.0:
        return "Early / speculative"
    return "Low confidence / insufficient evidence"


def _format_score(value: Any) -> float | str:
    if value is None:
        return "Not loaded"
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return str(value)


def _format_tags(value: Any) -> str:
    if value is None:
        return "Unclassified"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item)) or "Unclassified"
    return str(value).replace("|", ", ") or "Unclassified"


def _format_list(value: Any) -> str:
    if not value:
        return "None"
    if isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, dict):
                reason = item.get("reason")
                cap = item.get("cap")
                items.append(f"{reason} (cap {cap:g})" if reason and cap is not None else str(item))
            else:
                items.append(str(item))
        return "; ".join(items)
    return str(value) or "None"


def _format_technical_text(value: Any, default: str = "Not found in RNS yet") -> str:
    if _is_missing_value(value):
        return default
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item)) or default
    return str(value)


def _format_recovery(metrics: dict[str, Any]) -> str:
    if not _is_missing_value(metrics.get("recovery_pct")):
        return _format_percent(metrics.get("recovery_pct"))
    if metrics.get("metallurgical_testwork") is True:
        return "Testwork found; recovery not extracted"
    return "Not found in RNS yet"


def _alias(stock: dict[str, Any], company: str) -> str:
    aliases = []
    former_name = stock.get("former_name")
    former_ticker = stock.get("former_ticker")
    requested_name = stock.get("requested_name")

    if former_name:
        aliases.append(f"Formerly {former_name}")
    if former_ticker:
        aliases.append(f"Former ticker {former_ticker}")
    if requested_name and requested_name.lower() not in company.lower():
        aliases.append(f"Requested as {requested_name}")

    return "; ".join(aliases) if aliases else "None"


def build_dashboard_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stock in results:
        fundamentals = stock.get("fundamental", {}).get("fundamentals", {})
        metrics = _fill_from_market_snapshot(
            stock.get("fundamental", {}).get("metrics", {}),
            str(stock.get("ticker") or ""),
        )
        full_score = stock.get("full_score")
        preliminary = stock.get("preliminary_score")
        score = float(stock.get("composite_score") or full_score or preliminary or fundamentals.get("score") or 0)
        drivers = fundamentals.get("drivers") or ["No material driver recorded"]
        company = metrics.get("issuer_name") or stock.get("name", stock.get("ticker", "")) or "Unknown company"
        score_status = stock.get("score_status") or ("full" if full_score is not None else "metadata_only")

        rows.append(
            {
                "Ticker": stock.get("ticker", ""),
                "Company": company,
                "Alias": _alias(stock, company),
                "Exchange": metrics.get("market") or stock.get("exchange") or "Unknown",
                "Country": stock.get("country") or "Unknown",
                "Commodity": _format_tags(stock.get("commodity_tags")),
                "Role": stock.get("supply_chain_role") or "Unclassified",
                "Segment": metrics.get("segment") or "Not found",
                "Score": round(score, 2),
                "Score Status": score_status,
                "Full Score": _format_score(full_score),
                "Prelim Score": _format_score(preliminary),
                "Tech Score": _format_score(stock.get("technical_asset_score")),
                "Commercial Score": _format_score(stock.get("commercial_financial_score")),
                "Strategic Score": _format_score(stock.get("strategic_supply_chain_score")),
                "Benchmark Score": _format_score(stock.get("benchmark_score")),
                "Confidence": _format_score(stock.get("scoring_confidence") or stock.get("data_quality_score")),
                "Confidence Level": stock.get("confidence_level") or "Not assessed",
                "Data Coverage": _format_coverage(metrics.get("data_coverage_ratio")),
                "Rating": stock.get("rating_label") or _rating(score),
                "Peer Group": stock.get("suggested_peer_group") or "Unclassified",
                "Market Cap": _format_market_cap(metrics),
                "Last Price": _format_last_price(metrics),
                "Revenue LFY": _format_revenue(metrics),
                "Debt Metric": _format_debt_metric(metrics),
                "Shares Outstanding": _format_shares(metrics),
                "Volume": _format_number(metrics.get("volume")),
                "52W Range": _format_range(
                    metrics.get("fifty_two_week_low"),
                    metrics.get("fifty_two_week_high"),
                ),
                "Mineralogy": _format_technical_text(metrics.get("mineralogy")),
                "Recovery": _format_recovery(metrics),
                "Study Stage": _format_technical_text(metrics.get("study_stage")),
                "Resource Confidence": _format_technical_text(metrics.get("resource_category")),
                "Impurity Profile": _format_technical_text(metrics.get("impurity_profile")),
                "Technical Source": _format_technical_text(
                    metrics.get("rns_latest_title") or metrics.get("technical_data_source")
                ),
                "Stage Gates": _format_list(stock.get("applied_stage_gates")),
                "Missing Data": _format_list(stock.get("missing_data_fields")),
                "Drivers": "; ".join(drivers),
                "Positive Drivers": _format_list(stock.get("top_positive_drivers")),
                "Negative Drivers": _format_list(stock.get("top_negative_drivers")),
                "Data Notes": _format_list(metrics.get("data_fallbacks")),
                "Source": metrics.get("source") or "Unknown",
                "Retrieved UTC": str(metrics.get("retrieved") or "Not loaded")[:19],
            }
        )
    return rows


def _snapshot_display_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    status = snapshot.get("snapshot_status") or snapshot.get("status") or "reported"
    provenance = {
        "market_cap": {"status": status},
        "shares_outstanding": {"status": status},
    }
    return {
        "market_cap": snapshot.get("market_cap"),
        "last_price": snapshot.get("last_price"),
        "currency": snapshot.get("price_currency"),
        "shares_outstanding_lfy": snapshot.get("shares_outstanding"),
        "volume": snapshot.get("volume"),
        "fifty_two_week_low": snapshot.get("fifty_two_week_low"),
        "fifty_two_week_high": snapshot.get("fifty_two_week_high"),
        "field_provenance": provenance,
    }


def _append_display_note(record: dict[str, Any], note: str) -> None:
    existing = str(record.get("Data Notes") or "").strip()
    if not existing or existing.lower() in MISSING_DISPLAY_VALUES:
        record["Data Notes"] = note
        return
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if note not in parts:
        parts.append(note)
    record["Data Notes"] = "; ".join(parts)


def hydrate_dashboard_records_from_snapshot(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair display rows from the committed market snapshot before Dash renders them.

    Dash table pagination works from the ``data`` prop. If that prop contains stale
    cached display rows, later pages can show old ``n/a`` values even though the
    snapshot has valid market caps. This function is intentionally display-level:
    it only fills explicit missing labels and never overwrites a populated value.
    """
    hydrated: list[dict[str, Any]] = []
    for record in records:
        next_record = dict(record)
        snapshot = get_market_snapshot_for_ticker(str(next_record.get("Ticker") or ""), _market_snapshot_rows())
        if not snapshot:
            hydrated.append(next_record)
            continue

        metrics = _snapshot_display_metrics(snapshot)
        filled_fields: list[str] = []
        field_values = {
            "Market Cap": _format_market_cap(metrics),
            "Last Price": _format_last_price(metrics),
            "Shares Outstanding": _format_shares(metrics),
            "Volume": _format_number(metrics.get("volume")),
            "52W Range": _format_range(metrics.get("fifty_two_week_low"), metrics.get("fifty_two_week_high")),
        }
        for field, value in field_values.items():
            if _is_missing_display_value(next_record.get(field)) and not _is_missing_display_value(value):
                next_record[field] = value
                filled_fields.append(field)

        if filled_fields:
            status = snapshot.get("snapshot_status") or snapshot.get("status") or "reported"
            _append_display_note(
                next_record,
                f"{', '.join(filled_fields)} from company_market_snapshot.csv ({status})",
            )
            source = str(next_record.get("Source") or "").strip()
            if not source or source.lower() in MISSING_DISPLAY_VALUES:
                next_record["Source"] = "company_market_snapshot.csv"
            elif "company_market_snapshot.csv" not in source:
                next_record["Source"] = f"{source} + company_market_snapshot.csv"

        hydrated.append(next_record)
    return hydrated


def build_universe_search_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "Ticker": record.get("ticker", ""),
                "Company": record.get("company_name", ""),
                "Exchange": record.get("exchange", ""),
                "Country": record.get("country", ""),
                "Commodity": _format_tags(record.get("commodity_tags")),
                "Role": record.get("supply_chain_role", ""),
                "Stage": record.get("stage", ""),
                "Prelim Score": _format_score(record.get("preliminary_score")),
                "Source": record.get("source", ""),
            }
        )
    return rows
