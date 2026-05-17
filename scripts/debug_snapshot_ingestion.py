from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from analysis.composite import load_default_ranked_stocks
from dashboard.view_model import build_dashboard_rows
from data.financial_pipeline import build_company_identity, normalise_company_financials
from data.market_snapshot import (
    get_market_snapshot_for_ticker,
    load_market_snapshot,
    market_snapshot_path,
    normalise_market_snapshot_row,
    normalize_lse_ticker,
)
from data.universe import load_ticker_universe


DEFAULT_TICKERS = ["BHP", "RIO", "PREM", "RBW", "ZNWD", "FOX", "ZCC", "70GD", "SAUD"]


def _read_raw_snapshot_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_lse_ticker(row.get("Ticker") or row.get("ticker")): row
            for row in csv.DictReader(handle)
        }


def _format_payload(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def trace_ticker(
    ticker: str,
    *,
    raw_snapshot: dict[str, dict[str, Any]],
    normalized_snapshot: dict[str, dict[str, Any]],
    universe_by_ticker: dict[str, dict[str, Any]],
    stocks_by_ticker: dict[str, dict[str, Any]],
    rows_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = normalize_lse_ticker(ticker)
    raw_row = raw_snapshot.get(key)
    normalized_row = get_market_snapshot_for_ticker(key, normalized_snapshot)
    universe_row = universe_by_ticker.get(key)
    if normalized_row:
        identity = build_company_identity(universe_row or {"ticker": key}, normalized_row)
        final_financial = normalise_company_financials(
            identity,
            {
                "metadata": universe_row or {"ticker": key},
                "market_snapshot": normalized_row,
            },
            overrides=[],
        )
    else:
        identity = build_company_identity(universe_row or {"ticker": key})
        final_financial = normalise_company_financials(
            identity,
            {"metadata": universe_row or {"ticker": key}},
            overrides=[],
        )

    stock = stocks_by_ticker.get(key)
    dashboard_row = rows_by_ticker.get(key)
    stock_metrics = (stock or {}).get("fundamental", {}).get("metrics", {})
    market_cap_source = (
        stock_metrics.get("field_provenance", {})
        .get("market_cap", {})
        .get("source")
        or final_financial.get("field_provenance", {}).get("market_cap", {}).get("source")
        or "not_found"
    )
    snapshot_value = normalized_row.get("market_cap") if normalized_row else None
    final_value = stock_metrics.get("market_cap") if stock_metrics else final_financial.get("market_cap")
    if snapshot_value is None:
        reason = "Snapshot has no numeric market cap or explicit non-applicable status."
    elif final_value in (None, "", "n/a", "N/A", "Not found"):
        reason = "BUG: snapshot market cap exists but final metrics/display did not use it."
    elif "snapshot" in str(market_cap_source).lower() or final_value == snapshot_value:
        reason = "Snapshot market cap is used or preserved in final metrics."
    else:
        reason = "Snapshot value was superseded by a higher-priority computed/manual/source value."

    return {
        "requested_ticker": ticker,
        "normalized_ticker": key,
        "raw_snapshot_row": raw_row,
        "normalized_snapshot_row": normalized_row,
        "universe_row": universe_row,
        "matched_company_id": identity.get("company_id"),
        "final_financial_before_dashboard_formatting": final_financial,
        "cached_or_ranked_stock_metrics": stock_metrics,
        "final_dashboard_row_values": {
            field: (dashboard_row or {}).get(field)
            for field in (
                "Ticker",
                "Company",
                "Market Cap",
                "Last Price",
                "Shares Outstanding",
                "Volume",
                "52W Range",
                "Data Notes",
                "Source",
            )
        },
        "market_cap_source_chosen": market_cap_source,
        "snapshot_value_used_reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace snapshot CSV ingestion through final dashboard rows.")
    parser.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS)
    parser.add_argument("--snapshot-path", default=str(market_snapshot_path()))
    args = parser.parse_args()

    path = Path(args.snapshot_path)
    raw_snapshot = _read_raw_snapshot_rows(path)
    normalized_snapshot = load_market_snapshot(path)
    stocks, source = load_default_ranked_stocks(limit=None)
    rows = build_dashboard_rows(stocks)
    universe_by_ticker = {normalize_lse_ticker(row.get("ticker")): row for row in load_ticker_universe()}
    stocks_by_ticker = {normalize_lse_ticker(stock.get("ticker")): stock for stock in stocks}
    rows_by_ticker = {normalize_lse_ticker(row.get("Ticker")): row for row in rows}

    print(f"Snapshot path: {path}")
    print(f"Snapshot exists: {path.exists()}")
    print(f"Raw snapshot rows: {len(raw_snapshot)}")
    print(f"Normalized snapshot rows: {len(normalized_snapshot)}")
    print(f"Dashboard rows: {len(rows)}")
    print(f"Dashboard source: {source}")
    print(f"First 10 normalized tickers: {list(normalized_snapshot.keys())[:10]}")
    print()

    for ticker in args.tickers:
        print("=" * 88)
        print(_format_payload(trace_ticker(
            ticker,
            raw_snapshot=raw_snapshot,
            normalized_snapshot=normalized_snapshot,
            universe_by_ticker=universe_by_ticker,
            stocks_by_ticker=stocks_by_ticker,
            rows_by_ticker=rows_by_ticker,
        )))


if __name__ == "__main__":
    main()
