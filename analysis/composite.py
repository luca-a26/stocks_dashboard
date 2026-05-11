from __future__ import annotations

from typing import Any

from analysis.fundamentals import analyze_stock as fundamental_analyze
from analysis.rare_earth_scoring import score_company, score_metadata_only
from data.universe import (
    DEFAULT_UNIVERSE_LIMIT,
    get_universe_record,
    load_cached_scored_stocks,
    load_ticker_universe,
    preliminary_score,
    rank_metadata_universe,
    read_scored_stock_cache,
    write_scored_stock_cache,
)
from data.utils import get_logger, load_tickers


def _metadata_stock(record: dict[str, Any]) -> dict[str, Any]:
    scored = score_metadata_only(record)
    score = float(scored["composite_score"])
    return {
        "ticker": record.get("ticker", ""),
        "name": record.get("company_name") or record.get("ticker", ""),
        "exchange": record.get("exchange"),
        "country": record.get("country"),
        "sector": record.get("sector"),
        "commodity_tags": record.get("commodity_tags", []),
        "supply_chain_role": record.get("supply_chain_role"),
        "stage": record.get("stage"),
        "market_cap_tier": record.get("market_cap_tier"),
        "source": record.get("source"),
        "notes": record.get("notes"),
        "former_name": record.get("former_name") or None,
        "former_ticker": record.get("former_ticker") or None,
        "requested_name": record.get("requested_name") or None,
        "preliminary_score": score,
        "full_score": None,
        "score_status": "metadata_only",
        "composite_score": score,
        "technical_asset_score": scored["technical_asset_score"],
        "commercial_financial_score": scored["commercial_financial_score"],
        "strategic_supply_chain_score": scored["strategic_supply_chain_score"],
        "scoring_confidence": scored["scoring_confidence"],
        "data_quality_score": scored["data_quality_score"],
        "rating_label": scored["rating_label"],
        "score_breakdown": scored["score_breakdown"],
        "missing_data_fields": scored["missing_data_fields"],
        "applied_stage_gates": scored["applied_stage_gates"],
        "reason_codes": scored["reason_codes"],
        "explanation_bullets": scored["explanation_bullets"],
        "fundamental": {
            "fundamentals": {
                "score": score,
                "drivers": scored["reason_codes"],
            },
            "metrics": {
                "source": record.get("source") or "Ticker universe metadata",
                "retrieved": "",
            },
        },
    }


def _score_status(metrics: dict[str, Any], cache_state: str | None = None) -> str:
    if cache_state == "stale":
        return "stale"
    if not metrics:
        return "metadata_only"

    has_market_data = metrics.get("market_cap") is not None or metrics.get("last_price") is not None
    has_fundamental_data = (
        metrics.get("revenue_lfy") is not None
        or metrics.get("long_term_debt_to_capital_pct") is not None
        or metrics.get("net_debt_to_equity_pct") is not None
    )
    return "full" if has_market_data and has_fundamental_data else "partial"


def _detailed_stock(
    ticker: str,
    metadata: dict[str, Any] | None,
    fundamental: dict[str, Any],
    *,
    cache_state: str | None = None,
) -> dict[str, Any]:
    metadata = metadata or {"ticker": ticker, "company_name": ticker}
    prelim = preliminary_score(metadata)
    status = _score_status(fundamental.get("metrics", {}), cache_state)
    hybrid = score_company(metadata, fundamental.get("metrics", {}), score_status=status)
    full_score = float(hybrid["composite_score"])
    drivers = list(fundamental.get("fundamentals", {}).get("drivers") or [])
    drivers.extend(hybrid.get("reason_codes", []))

    if status == "partial":
        drivers.append("Partial detailed score; some LSE financial fields unavailable")
    elif status == "stale":
        drivers.append("Stale cached detailed score; refresh required")

    fundamental = {
        "fundamentals": {
            **fundamental.get("fundamentals", {}),
            "score": full_score,
            "drivers": drivers or ["Detailed data loaded"],
        },
        "metrics": fundamental.get("metrics", {}),
    }

    return {
        "ticker": ticker,
        "name": metadata.get("company_name") or ticker,
        "exchange": metadata.get("exchange"),
        "country": metadata.get("country"),
        "sector": metadata.get("sector"),
        "commodity_tags": metadata.get("commodity_tags", []),
        "supply_chain_role": metadata.get("supply_chain_role"),
        "stage": metadata.get("stage"),
        "market_cap_tier": metadata.get("market_cap_tier"),
        "source": metadata.get("source"),
        "notes": metadata.get("notes"),
        "former_name": metadata.get("former_name") or None,
        "former_ticker": metadata.get("former_ticker") or None,
        "requested_name": metadata.get("requested_name") or None,
        "preliminary_score": prelim,
        "full_score": full_score,
        "score_status": hybrid["score_status"],
        "composite_score": full_score,
        "technical_asset_score": hybrid["technical_asset_score"],
        "commercial_financial_score": hybrid["commercial_financial_score"],
        "strategic_supply_chain_score": hybrid["strategic_supply_chain_score"],
        "scoring_confidence": hybrid["scoring_confidence"],
        "data_quality_score": hybrid["data_quality_score"],
        "rating_label": hybrid["rating_label"],
        "score_breakdown": hybrid["score_breakdown"],
        "missing_data_fields": hybrid["missing_data_fields"],
        "applied_stage_gates": hybrid["applied_stage_gates"],
        "reason_codes": hybrid["reason_codes"],
        "explanation_bullets": hybrid["explanation_bullets"],
        "fundamental": fundamental,
    }


def load_detailed_stock(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    ticker = ticker.upper()
    metadata = get_universe_record(ticker)

    if not force_refresh:
        cached, state = read_scored_stock_cache(ticker, allow_stale=True)
        if cached and state == "fresh" and "technical_asset_score" in cached:
            return cached
    else:
        cached, state = None, "refresh"

    try:
        get_logger(__name__).info("On-demand detail fetch for %s", ticker)
        stock = _detailed_stock(ticker, metadata, fundamental_analyze(ticker))
        write_scored_stock_cache(ticker, stock)
        return stock
    except Exception as exc:
        get_logger(__name__).exception("On-demand detail fetch failed for %s", ticker)
        if cached:
            cached["score_status"] = "stale"
            cached.setdefault("fundamental", {}).setdefault("fundamentals", {}).setdefault("drivers", [])
            cached["fundamental"]["fundamentals"]["drivers"].append(f"Refresh failed: {exc}")
            return cached
        raise


def load_default_ranked_stocks(limit: int = DEFAULT_UNIVERSE_LIMIT) -> tuple[list[dict[str, Any]], str]:
    universe = load_ticker_universe()
    by_ticker = {record["ticker"]: record for record in universe}
    cached_stocks = load_cached_scored_stocks(include_stale=True)

    stocks_by_ticker: dict[str, dict[str, Any]] = {}
    for stock in cached_stocks:
        ticker = str(stock.get("ticker", "")).upper()
        if ticker:
            stocks_by_ticker[ticker] = stock

    ranked_metadata = rank_metadata_universe(universe, limit=max(limit, len(universe)))
    for record in ranked_metadata:
        ticker = record["ticker"]
        stocks_by_ticker.setdefault(ticker, _metadata_stock(record))

    ranked = sorted(
        stocks_by_ticker.values(),
        key=lambda stock: (
            -float(stock.get("composite_score") or 0),
            str(stock.get("score_status") or ""),
            stock.get("name") or stock.get("ticker") or "",
        ),
    )[:limit]

    if cached_stocks:
        source = "cached scores plus metadata fallback"
    elif load_tickers():
        source = "curated watchlist plus metadata preliminary ranking"
    else:
        source = "metadata preliminary ranking"

    get_logger(__name__).info("Default top %s selection source: %s", limit, source)
    return ranked, source


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
            _detailed_stock(
                code,
                {
                    "ticker": code,
                    "company_name": metadata.get("name", code),
                    "exchange": metadata.get("exchange"),
                    "commodity_tags": metadata.get("focus", []),
                    "former_name": metadata.get("former_name"),
                    "former_ticker": metadata.get("former_ticker"),
                    "requested_name": metadata.get("requested_name"),
                },
                fund,
            )
        )

    return results
