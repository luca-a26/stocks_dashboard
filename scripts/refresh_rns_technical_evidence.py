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
    extracted = extract_technical_evidence_from_text(announcement.text, announcement.title)
    if not extracted:
        return None
    reasons = extracted.pop("reason_codes", [])
    row = {
        "ticker": ticker,
        "company": company,
        "announcement_date": announcement.released or "",
        "announcement_title": announcement.title,
        "source_url": announcement.url,
        "source_name": "London Stock Exchange RNS",
        "confidence": "Medium",
        "notes": "; ".join(reasons),
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
        "tickers_with_technical_evidence": [],
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

        # Build once as a validation pass, then write the row-level evidence for auditability.
        merged = build_rns_technical_metrics_from_announcements(announcements)
        if merged:
            audit["tickers_with_technical_evidence"].append(ticker)
        for announcement in announcements:
            row = _announcement_to_row(ticker, company["company"], announcement)
            if row:
                rows.append(row)

    audit["rows_with_technical_evidence"] = len(rows)
    write_rns_technical_evidence_csv(rows, output_csv)
    write_rns_technical_evidence_json(audit, output_json)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh RNS-derived technical evidence for scoring.")
    parser.add_argument("--input", default="config/ticker_universe.csv")
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
        f"{len(audit['tickers_with_technical_evidence'])} tickers"
    )


if __name__ == "__main__":
    main()
