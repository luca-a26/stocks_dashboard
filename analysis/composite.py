from __future__ import annotations

import os
from typing import Any

from analysis.fundamentals import analyze_stock as fundamental_analyze
from analysis.rare_earth_scoring import score_company, score_metadata_only
from data.financial_pipeline import build_company_identity, coverage_audit, normalise_company_financials
from data.london_south_east import fetch_share_price_snapshot
from data.market_snapshot import (
    get_market_snapshot_for_ticker,
    live_market_refresh_enabled,
    load_market_snapshot,
    normalize_lse_ticker,
)
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

STARTUP_BASIC_MARKET_FALLBACK = os.getenv("STARTUP_BASIC_MARKET_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}
if "STARTUP_BASIC_MARKET_FALLBACK" not in os.environ:
    STARTUP_BASIC_MARKET_FALLBACK = live_market_refresh_enabled()


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_metrics_from_metadata(
    record: dict[str, Any],
    market_snapshot: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = build_company_identity(record)
    sources: dict[str, dict[str, Any]] = {"metadata": record}
    snapshot_row = get_market_snapshot_for_ticker(str(record.get("ticker") or ""), market_snapshot)
    if snapshot_row:
        sources["market_snapshot"] = snapshot_row
    should_fetch_basic = (
        STARTUP_BASIC_MARKET_FALLBACK
        and _to_float(record.get("market_cap")) is None
        and "London South East" in str(record.get("source", ""))
        and record.get("ticker")
    )
    if should_fetch_basic:
        try:
            fallback = fetch_share_price_snapshot(str(record["ticker"]), str(record.get("company_name") or ""))
            if fallback:
                sources["london_south_east_share"] = fallback
        except Exception as exc:
            get_logger(__name__).warning("Startup basic market fallback failed for %s: %s", record.get("ticker"), exc)
    return normalise_company_financials(identity, sources)


def _basic_coverage_ratio(metrics: dict[str, Any]) -> float:
    checks = [
        metrics.get("market_cap") is not None,
        metrics.get("last_price") is not None,
        metrics.get("volume") is not None,
        metrics.get("fifty_two_week_low") is not None and metrics.get("fifty_two_week_high") is not None,
        metrics.get("shares_outstanding_lfy") is not None,
    ]
    return round(sum(checks) / len(checks), 3)


def _merge_basic_market_fallback(metrics: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        return metrics
    merged = dict(metrics)
    notes: list[str] = list(merged.get("data_fallbacks") or [])
    for field in (
        "market_cap",
        "last_price",
        "currency",
        "volume",
        "fifty_two_week_low",
        "fifty_two_week_high",
        "shares_outstanding_lfy",
        "trades",
    ):
        if merged.get(field) is None and fallback.get(field) is not None:
            merged[field] = fallback[field]
            notes.append(f"{field} from London South East share page")
    if fallback.get("country") and not merged.get("country"):
        merged["country"] = fallback["country"]
    if fallback.get("share_price_url"):
        merged["share_price_url"] = fallback["share_price_url"]
    if notes:
        source = str(merged.get("source") or "Ticker universe metadata")
        if "London South East share page" not in source:
            merged["source"] = f"{source} + London South East share page"
        merged["data_fallbacks"] = sorted(dict.fromkeys(notes))
    return merged


def _merge_metadata_metric_fallbacks(metrics: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    sources = {"lse": metrics, "metadata": metadata}
    snapshot_row = get_market_snapshot_for_ticker(str(metadata.get("ticker") or metrics.get("source_ticker") or ""))
    if snapshot_row:
        sources["market_snapshot"] = snapshot_row
    identity = build_company_identity(metadata, metrics)
    return normalise_company_financials(identity, sources)


def _metadata_stock(
    record: dict[str, Any],
    market_snapshot: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scored = score_metadata_only(record)
    score = float(scored["composite_score"])
    market_metrics = _market_metrics_from_metadata(record, market_snapshot)
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
        "benchmark_score": scored.get("benchmark_score"),
        "benchmark_breakdown": scored.get("benchmark_breakdown"),
        "scoring_confidence": scored["scoring_confidence"],
        "data_quality_score": scored["data_quality_score"],
        "data_completeness_score": scored.get("data_completeness_score"),
        "confidence_level": scored.get("confidence_level"),
        "suggested_peer_group": scored.get("suggested_peer_group"),
        "rating_label": scored["rating_label"],
        "score_breakdown": scored["score_breakdown"],
        "missing_data_fields": scored["missing_data_fields"],
        "applied_stage_gates": scored["applied_stage_gates"],
        "reason_codes": scored["reason_codes"],
        "explanation_bullets": scored["explanation_bullets"],
        "top_positive_drivers": scored.get("top_positive_drivers"),
        "top_negative_drivers": scored.get("top_negative_drivers"),
        "fundamental": {
            "fundamentals": {
                "score": score,
                "drivers": scored["reason_codes"],
            },
            "metrics": market_metrics,
        },
    }


def _audit_snapshot_ingestion(
    stocks: list[dict[str, Any]],
    market_snapshot: dict[str, dict[str, Any]],
) -> None:
    logger = get_logger(__name__)
    matched = 0
    using_snapshot_market_cap = 0
    lost_market_cap: list[str] = []
    snapshot_market_caps = {
        ticker: row
        for ticker, row in market_snapshot.items()
        if row.get("market_cap") is not None
    }

    for stock in stocks:
        ticker = normalize_lse_ticker(stock.get("ticker"))
        metrics = stock.get("fundamental", {}).get("metrics", {})
        snapshot_row = market_snapshot.get(ticker)
        if snapshot_row:
            matched += 1
        if not snapshot_row or snapshot_row.get("market_cap") is None:
            continue

        provenance = metrics.get("field_provenance", {}).get("market_cap", {})
        source = str(provenance.get("source") or metrics.get("source") or "")
        if "snapshot" in source.lower():
            using_snapshot_market_cap += 1
        if metrics.get("market_cap") is None:
            lost_market_cap.append(ticker)

    logger.info(
        "Snapshot ingestion audit: snapshot_rows=%s snapshot_market_caps=%s dashboard_rows=%s matched=%s using_snapshot_market_cap=%s lost_market_cap=%s",
        len(market_snapshot),
        len(snapshot_market_caps),
        len(stocks),
        matched,
        using_snapshot_market_cap,
        len(lost_market_cap),
    )
    if lost_market_cap:
        logger.error(
            "Snapshot ingestion regression. Snapshot contains market cap but final metrics lost it for: %s",
            ", ".join(lost_market_cap[:50]),
        )


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
    metrics = _merge_metadata_metric_fallbacks(fundamental.get("metrics", {}), metadata)
    status = _score_status(metrics, cache_state)
    hybrid = score_company(metadata, metrics, score_status=status)
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
        "metrics": metrics,
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
        "benchmark_score": hybrid.get("benchmark_score"),
        "benchmark_breakdown": hybrid.get("benchmark_breakdown"),
        "scoring_confidence": hybrid["scoring_confidence"],
        "data_quality_score": hybrid["data_quality_score"],
        "data_completeness_score": hybrid.get("data_completeness_score"),
        "confidence_level": hybrid.get("confidence_level"),
        "suggested_peer_group": hybrid.get("suggested_peer_group"),
        "rating_label": hybrid["rating_label"],
        "score_breakdown": hybrid["score_breakdown"],
        "missing_data_fields": hybrid["missing_data_fields"],
        "applied_stage_gates": hybrid["applied_stage_gates"],
        "reason_codes": hybrid["reason_codes"],
        "explanation_bullets": hybrid["explanation_bullets"],
        "top_positive_drivers": hybrid.get("top_positive_drivers"),
        "top_negative_drivers": hybrid.get("top_negative_drivers"),
        "fundamental": fundamental,
    }


def load_detailed_stock(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    ticker = normalize_lse_ticker(ticker)
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


def load_default_ranked_stocks(limit: int | None = DEFAULT_UNIVERSE_LIMIT) -> tuple[list[dict[str, Any]], str]:
    universe = load_ticker_universe()
    market_snapshot = load_market_snapshot()
    by_ticker = {record["ticker"]: record for record in universe}
    cached_stocks = load_cached_scored_stocks(include_stale=True)
    selection_limit = len(universe) if limit is None else limit

    stocks_by_ticker: dict[str, dict[str, Any]] = {}
    for stock in cached_stocks:
        ticker = normalize_lse_ticker(stock.get("ticker", ""))
        if ticker:
            metadata = by_ticker.get(ticker, {})
            metrics = stock.get("fundamental", {}).get("metrics", {})
            if metrics or ticker in market_snapshot:
                sources = {"metadata": metadata, "lse": metrics}
                if ticker in market_snapshot:
                    sources["market_snapshot"] = market_snapshot[ticker]
                identity = build_company_identity(metadata or {"ticker": ticker}, metrics)
                stock.setdefault("fundamental", {}).setdefault("metrics", {})
                normalised_metrics = normalise_company_financials(identity, sources)
                if stock.get("score_cache_state") == "stale":
                    notes = list(normalised_metrics.get("data_fallbacks") or [])
                    notes.append("Score cache is expired; use Load financials to refresh detailed score")
                    normalised_metrics["data_fallbacks"] = sorted(dict.fromkeys(notes))
                stock["fundamental"]["metrics"] = normalised_metrics
            stocks_by_ticker[ticker] = stock

    ranked_metadata = rank_metadata_universe(universe, limit=max(selection_limit, len(universe)))
    for record in ranked_metadata:
        ticker = record["ticker"]
        stocks_by_ticker.setdefault(ticker, _metadata_stock(record, market_snapshot))

    ranked_all = sorted(
        stocks_by_ticker.values(),
        key=lambda stock: (
            -float(stock.get("composite_score") or 0),
            str(stock.get("score_status") or ""),
            stock.get("name") or stock.get("ticker") or "",
        ),
    )
    ranked = ranked_all if limit is None else ranked_all[:selection_limit]
    _audit_snapshot_ingestion(ranked, market_snapshot)

    has_lse_sector = any(
        "London South East Industrial Metals" in str(record.get("source", ""))
        for record in universe
    )

    if cached_stocks and market_snapshot:
        source = "cached scores plus company market snapshot and metadata fallback"
    elif cached_stocks:
        source = "cached scores plus metadata fallback"
    elif market_snapshot:
        source = "company market snapshot plus metadata preliminary ranking"
    elif has_lse_sector:
        source = "London South East Industrial Metals comparison universe plus curated metadata ranking"
    elif load_tickers():
        source = "curated watchlist plus metadata preliminary ranking"
    else:
        source = "metadata preliminary ranking"

    get_logger(__name__).info("Default comparison selection size=%s source: %s", len(ranked), source)
    audit = coverage_audit(ranked)
    get_logger(__name__).info("Financial coverage audit\n%s", audit["summary"])
    source = f"{source}; display-safe coverage {audit['display_safe_coverage']['ratio']:.1%} ({'PASS' if audit['passed'] else 'FAIL'})"
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
