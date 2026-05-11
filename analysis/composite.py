from __future__ import annotations

from typing import Any

from analysis.fundamentals import analyze_stock as fundamental_analyze
from data.utils import get_logger, load_tickers


def analyze_all_stocks() -> list[dict[str, Any]]:
    tickers = load_tickers()
    results: list[dict[str, Any]] = []

    for code, metadata in tickers.items():
        try:
            fund = fundamental_analyze(code)
        except Exception as exc:
            get_logger(__name__).exception("Failed to analyse %s", code)
            fund = {
                "fundamentals": {"score": 0, "drivers": [f"Analysis failed: {exc}"]},
                "metrics": {},
            }

        results.append(
            {
                "ticker": code,
                "name": metadata.get("name", code),
                "exchange": metadata.get("exchange"),
                "former_name": metadata.get("former_name"),
                "former_ticker": metadata.get("former_ticker"),
                "requested_name": metadata.get("requested_name"),
                "exchange_ticker": metadata.get("ticker", code),
                "composite_score": fund.get("fundamentals", {}).get("score", 0),
                "fundamental": fund,
            }
        )

    return results
