from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.market_snapshot import normalize_lse_ticker
from data.rns import (
    CSV_FIELDS,
    TECHNICAL_EVIDENCE_FIELDS,
    build_rns_technical_metrics_from_announcements,
    extract_technical_evidence_from_text,
    fetch_recent_lse_rns_announcements,
    is_relevant_technical_source,
    write_rns_technical_evidence_csv,
    write_rns_technical_evidence_json,
)
from data.utils import PROJECT_ROOT, get_logger


def _resolve(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


def _load_input_companies(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        companies = []
        for row in reader:
            ticker = normalize_lse_ticker(row.get("ticker") or row.get("Ticker"))
            if not ticker:
                continue
            companies.append(
                {
                    "ticker": ticker,
                    "company": str(row.get("company_name") or row.get("Company") or ticker).strip(),
                }
            )
    return companies


def _announcement_to_row(ticker: str, company: str, announcement: Any) -> dict[str, Any] | None:
    if not is_relevant_technical_source(announcement.title, announcement.text):
        return None
    extracted = extract_technical_evidence_from_text(announcement.text, announcement.title)
    reasons = extracted.pop("reason_codes", [])
    field_count = sum(1 for field in TECHNICAL_EVIDENCE_FIELDS if extracted.get(field) not in (None, ""))
    row = {
        "ticker": ticker,
        "company": company,
        "announcement_date": announcement.released or "",
        "announcement_title": announcement.title,
        "source_url": announcement.url,
        "technical_evidence_status": (
            "structured_fields_extracted" if field_count else "rns_or_document_found_needs_review"
        ),
        "technical_field_count": field_count,
        "source_name": "London South East RNS mirror"
        if "lse.co.uk" in str(announcement.url).lower()
        else "London Stock Exchange RNS",
        "confidence": "Medium",
        "notes": "; ".join(reasons)
        if reasons
        else "Technical/project RNS found; structured fields require analyst review",
        "last_verified": datetime.now(timezone.utc).date().isoformat(),
    }
    for field in TECHNICAL_EVIDENCE_FIELDS:
        row[field] = extracted.get(field, "")
    return row


def refresh_rns_technical_evidence(
    input_path: Path,
    output_csv: Path,
    output_json: Path,
    *,
    limit_companies: int | None = None,
    announcements_per_company: int = 20,
    force_refresh: bool = False,
) -> dict[str, Any]:
    companies = _load_input_companies(input_path)
    if limit_companies is not None:
        companies = companies[:limit_companies]

    rows: list[dict[str, Any]] = []
    audit = {
        "input": str(input_path),
        "companies_checked": len(companies),
        "rows_with_technical_evidence": 0,
        "rows_requiring_review": 0,
        "tickers_with_technical_evidence": [],
        "tickers_with_rns_candidates": [],
        "tickers_without_rns_candidates": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    for company in companies:
        ticker = company["ticker"]
        try:
            announcements = fetch_recent_lse_rns_announcements(
                ticker,
                company["company"],
                limit=announcements_per_company,
                force_refresh=force_refresh,
            )
        except Exception as exc:
            get_logger(__name__).warning("RNS refresh failed for %s: %s", ticker, exc)
            continue

        company_rows: list[dict[str, Any]] = []
        # Build once as a validation pass, then write the row-level evidence for auditability.
        merged = build_rns_technical_metrics_from_announcements(announcements)
        if merged:
            audit["tickers_with_rns_candidates"].append(ticker)
            if merged.get("technical_field_count", 0) > 0:
                audit["tickers_with_technical_evidence"].append(ticker)
        for announcement in announcements:
            row = _announcement_to_row(ticker, company["company"], announcement)
            if row:
                company_rows.append(row)
        if not company_rows:
            audit["tickers_without_rns_candidates"].append(ticker)
        rows.extend(company_rows)

    audit["rows_with_technical_evidence"] = len(rows)
    audit["rows_requiring_review"] = sum(
        1 for row in rows if row.get("technical_evidence_status") == "rns_or_document_found_needs_review"
    )
    audit["technical_field_coverage"] = (
        len(audit["tickers_with_technical_evidence"]) / len(companies) if companies else 0
    )
    audit["technical_source_coverage"] = (
        len(audit["tickers_with_rns_candidates"]) / len(companies) if companies else 0
    )
    write_rns_technical_evidence_csv(rows, output_csv)
    write_rns_technical_evidence_json(audit, output_json)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh RNS-derived technical evidence for scoring.")
    parser.add_argument("--input", default="data/company_market_snapshot.csv")
    parser.add_argument("--output-csv", default="data/rns_technical_evidence.csv")
    parser.add_argument("--output-json", default="storage/audit/rns_technical_evidence_audit.json")
    parser.add_argument("--limit-companies", type=int, default=None)
    parser.add_argument("--announcements-per-company", type=int, default=20)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    audit = refresh_rns_technical_evidence(
        _resolve(args.input),
        _resolve(args.output_csv),
        _resolve(args.output_json),
        limit_companies=args.limit_companies,
        announcements_per_company=args.announcements_per_company,
        force_refresh=args.force_refresh,
    )
    print(
        "RNS technical evidence refresh: "
        f"{audit['rows_with_technical_evidence']} rows across "
        f"{len(audit['tickers_with_technical_evidence'])} tickers; "
        f"source coverage {audit['technical_source_coverage']:.1%}; "
        f"structured-field coverage {audit['technical_field_coverage']:.1%}"
    )


if __name__ == "__main__":
    main()
