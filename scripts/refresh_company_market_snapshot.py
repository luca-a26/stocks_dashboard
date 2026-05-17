from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from data.financial_pipeline import build_company_identity, coverage_audit, normalise_company_financials
from data.london_south_east import (
    HEADERS,
    REQUEST_TIMEOUT,
    SHARE_PRICE_URL,
    _parse_share_price_page,
    _slugify,
    fetch_share_price_snapshot,
)
from data.lse import fetch_company_snapshot
from data.market_snapshot import (
    CANONICAL_CSV_FIELDS,
    NON_APPLICABLE_STATUSES,
    market_snapshot_path,
    normalise_market_snapshot_row,
    normalize_lse_ticker,
    snapshot_rows_for_output,
)
from data.utils import PROJECT_ROOT, get_logger
from data.yahoo import fetch_yahoo_london_fallback


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_input_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("Ticker") or row.get("ticker")]


def _ticker(row: dict[str, Any]) -> str:
    return normalize_lse_ticker(row.get("Ticker") or row.get("ticker"))


def _company(row: dict[str, Any]) -> str:
    return str(row.get("Company") or row.get("company_name") or row.get("name") or _ticker(row)).strip()


def _source_url(row: dict[str, Any]) -> str:
    return str(row.get("Primary Source") or row.get("source_url") or row.get("share_price_url") or "").strip()


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
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
    except (TypeError, ValueError):
        return None


def _fetch_lse_share_page_from_url(url: str) -> dict[str, Any]:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    parsed = _parse_share_price_page(response.text)
    if parsed:
        parsed["source"] = "London South East share page"
        parsed["share_price_url"] = url
    return parsed


def _fetch_lse_share_page(ticker: str, company: str, url: str, *, force_refresh: bool) -> dict[str, Any]:
    if url:
        return _fetch_lse_share_page_from_url(url)
    return fetch_share_price_snapshot(ticker, company, force_refresh=force_refresh)


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_positive_number(*values: Any) -> float | None:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _normalised_price(value: Any, currency: str | None) -> float | None:
    price = _first_positive_number(value)
    if price is None:
        return None
    if str(currency or "").upper() in {"GBX", "GBPENCE", "GBP PENCE", "PENCE"}:
        return price / 100
    return price


def _repair_share_count_units(
    shares: float | None,
    *,
    market_cap: float | None,
    last_price: float | None,
    price_currency: str,
) -> float | None:
    """Use price and market cap to repair unitless LSE share counts.

    Some LSE.co.uk pages expose "Shares in Issue" as a display-scaled number
    (for example 5.08 for 5.08b). When market cap and price are available,
    the implied share count is a safer persisted snapshot value.
    """
    normalised = _normalised_price(last_price, price_currency)
    if market_cap is None or market_cap <= 0 or normalised is None or normalised <= 0:
        return shares
    implied_shares = market_cap / normalised
    if shares is None:
        return implied_shares
    if shares < 1_000 and implied_shares > shares * 1_000:
        return implied_shares
    return shares


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text not in {"-", "n/a", "N/A"}:
            return text
    return ""


def _format_scaled(value: float | None, currency: str = "", *, money: bool = False) -> tuple[str, str]:
    if value is None:
        return "-", ""
    prefix = ""
    if money:
        prefix = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper(), "")
    for suffix, divisor in (("b", 1_000_000_000), ("m", 1_000_000), ("k", 1_000)):
        if abs(value) >= divisor:
            return f"{prefix}{value / divisor:.2f}{suffix}", suffix
    return f"{prefix}{value:.2f}", ""


def _status_for_row(existing_status: str, market_cap: float | None, shares: float | None) -> str:
    status = existing_status.lower().strip()
    if status in NON_APPLICABLE_STATUSES and (market_cap is None or market_cap <= 0):
        return status
    if status == "found_suspended_security":
        return status
    if market_cap is not None and market_cap > 0:
        return status if status == "found_via_non_constituent_search" else "found_lse_share_page"
    if shares == 0 and status == "not_available_gdr_zero_shares_on_source":
        return status
    return "not_found"


def _refresh_record(row: dict[str, Any], *, force_refresh: bool) -> dict[str, Any]:
    ticker = _ticker(row)
    company = _company(row)
    url = _source_url(row)
    now_text = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors: list[str] = []
    lse_share: dict[str, Any] = {}
    lse_api: dict[str, Any] = {}
    yahoo: dict[str, Any] = {}

    try:
        lse_share = _fetch_lse_share_page(ticker, company, url, force_refresh=force_refresh)
    except Exception as exc:
        errors.append(f"London South East refresh failed: {exc}")

    market_cap = _first_positive_number(lse_share.get("market_cap"), row.get("Market Cap Numeric"), row.get("market_cap"))
    shares = _first_positive_number(
        lse_share.get("shares_outstanding_lfy"),
        lse_share.get("shares_outstanding"),
        row.get("Shares in Issue"),
        row.get("shares_outstanding_lfy"),
    )

    if market_cap is None or shares is None or lse_share.get("last_price") is None:
        try:
            lse_api = fetch_company_snapshot(ticker, force_refresh=force_refresh)
        except Exception as exc:
            errors.append(f"LSE API/PDF fallback failed: {exc}")

    if market_cap is None or shares is None or lse_share.get("last_price") is None:
        try:
            yahoo = fetch_yahoo_london_fallback(ticker, force_refresh=force_refresh)
        except Exception as exc:
            errors.append(f"Yahoo fallback failed: {exc}")

    market_cap = _first_positive_number(
        market_cap,
        lse_api.get("market_cap"),
        yahoo.get("market_cap"),
    )
    shares = _first_positive_number(
        shares,
        lse_api.get("shares_outstanding_lfy"),
        lse_api.get("shares_outstanding"),
        yahoo.get("shares_outstanding_lfy"),
        yahoo.get("shares_outstanding"),
    )
    currency = _first_text(row.get("Market Cap Currency"), lse_api.get("currency"), yahoo.get("currency"))
    price_currency = _first_text(lse_share.get("currency"), lse_api.get("currency"), yahoo.get("currency"))
    last_price = _first_number(lse_share.get("last_price"), lse_api.get("last_price"), yahoo.get("last_price"))
    shares = _repair_share_count_units(
        shares,
        market_cap=market_cap,
        last_price=last_price,
        price_currency=price_currency,
    )
    market_cap_display, magnitude = _format_scaled(market_cap, currency or "GBP", money=True)
    status = _status_for_row(str(row.get("Status") or row.get("status") or ""), market_cap, shares)

    notes = _first_text(row.get("Notes"), row.get("notes"))
    if errors:
        notes = "; ".join(part for part in [notes, *errors] if part)
    elif not notes:
        notes = "Refreshed from canonical market-data workflow; prefer source market cap, with price x shares retained as a validation cross-check."

    return {
        "Ticker": ticker,
        "Company": company,
        "Market Cap": market_cap_display,
        "Market Cap Currency": currency or ("GBP" if market_cap is not None else ""),
        "Market Cap Numeric": market_cap if market_cap is not None else "",
        "Magnitude": magnitude,
        "Shares in Issue": shares if shares is not None else "",
        "Status": status,
        "Primary Source": url or SHARE_PRICE_URL.format(ticker=ticker, slug=_slugify(company)),
        "Snapshot Date": now_text,
        "Notes": notes,
        "Last Price": last_price or "",
        "Price Currency": price_currency,
        "Price Unit": "GBp" if str(price_currency).upper() in {"GBX", "GBPENCE"} else price_currency,
        "Volume": _first_number(lse_share.get("volume"), lse_api.get("volume"), yahoo.get("volume")) or "",
        "52 Week Low": _first_number(
            lse_share.get("fifty_two_week_low"),
            lse_api.get("fifty_two_week_low"),
            yahoo.get("fifty_two_week_low"),
        )
        or "",
        "52 Week High": _first_number(
            lse_share.get("fifty_two_week_high"),
            lse_api.get("fifty_two_week_high"),
            yahoo.get("fifty_two_week_high"),
        )
        or "",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CANONICAL_CSV_FIELDS})


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = [normalise_market_snapshot_row(row) for row in rows]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_count": len(normalised),
        "rows": normalised,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_audit(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stocks = []
    for row in rows:
        normalised = normalise_market_snapshot_row(row)
        identity = build_company_identity(
            {"ticker": normalised.get("ticker"), "company_name": normalised.get("company_name")},
            normalised,
        )
        metrics = normalise_company_financials(identity, {"market_snapshot": normalised}, overrides=[])
        stocks.append(
            {
                "ticker": normalised.get("ticker"),
                "name": normalised.get("company_name"),
                "fundamental": {"metrics": metrics},
            }
        )
    audit = coverage_audit(stocks)
    audit["missing_by_field"] = audit.get("failures", {})
    path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return audit


def refresh_snapshot(
    input_path: Path,
    output_csv: Path,
    output_json: Path,
    audit_output: Path,
    *,
    force_refresh: bool,
    limit: int | None = None,
) -> dict[str, Any]:
    input_rows = _read_input_records(input_path)
    if limit is not None:
        input_rows = input_rows[:limit]
    output_rows = [_refresh_record(row, force_refresh=force_refresh) for row in input_rows]
    output_rows.sort(key=lambda item: (item.get("Company") or "", item.get("Ticker") or ""))
    _write_csv(output_csv, output_rows)
    normalised = {normalise_market_snapshot_row(row)["ticker"]: normalise_market_snapshot_row(row) for row in output_rows}
    _write_json(output_json, snapshot_rows_for_output(normalised))
    audit = _write_audit(audit_output, output_rows)
    get_logger(__name__).info("Market snapshot refreshed: %s", audit["summary"])
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the canonical company market snapshot.")
    parser.add_argument("--input", default=str(market_snapshot_path()))
    parser.add_argument("--output-csv", default=str(market_snapshot_path()))
    parser.add_argument("--output-json", default=str(PROJECT_ROOT / "data" / "company_market_snapshot.json"))
    parser.add_argument("--audit-output", default=str(PROJECT_ROOT / "storage" / "audit" / "company_market_snapshot_audit.json"))
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    audit = refresh_snapshot(
        _project_path(args.input),
        _project_path(args.output_csv),
        _project_path(args.output_json),
        _project_path(args.audit_output),
        force_refresh=args.force_refresh,
        limit=args.limit,
    )
    print(audit["summary"])


if __name__ == "__main__":
    main()
