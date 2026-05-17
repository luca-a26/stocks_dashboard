from __future__ import annotations

from typing import Any

from data.financial_pipeline import build_company_identity, normalise_company_financials
from data.london_south_east import fetch_share_price_snapshot
from data.lse import fetch_company_snapshot
from data.market_snapshot import get_market_snapshot_for_ticker, normalize_lse_ticker
from data.utils import get_logger
from data.yahoo import fetch_yahoo_london_fallback

FALLBACK_FIELDS = (
    "market_cap",
    "last_price",
    "currency",
    "volume",
    "fifty_two_week_low",
    "fifty_two_week_high",
    "revenue_lfy",
    "net_debt_to_equity_pct",
    "shares_outstanding_lfy",
    "price_to_sales",
    "price_to_book",
)


def _debt_available(metrics: dict[str, Any]) -> bool:
    return metrics.get("long_term_debt_to_capital_pct") is not None or metrics.get("net_debt_to_equity_pct") is not None


def _needs_fallback(metrics: dict[str, Any]) -> bool:
    required = (
        metrics.get("market_cap") is not None,
        metrics.get("last_price") is not None,
        metrics.get("volume") is not None,
        metrics.get("fifty_two_week_low") is not None and metrics.get("fifty_two_week_high") is not None,
        metrics.get("revenue_lfy") is not None,
        _debt_available(metrics),
        metrics.get("shares_outstanding_lfy") is not None,
    )
    return sum(required) / len(required) < 0.95


def _coverage_ratio(metrics: dict[str, Any]) -> float:
    required = (
        metrics.get("market_cap") is not None,
        metrics.get("last_price") is not None,
        metrics.get("volume") is not None,
        metrics.get("fifty_two_week_low") is not None and metrics.get("fifty_two_week_high") is not None,
        metrics.get("revenue_lfy") is not None,
        _debt_available(metrics),
        metrics.get("shares_outstanding_lfy") is not None,
    )
    return round(sum(required) / len(required), 3)


def _merge_fallback_metrics(metrics: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        metrics["data_coverage_ratio"] = _coverage_ratio(metrics)
        return metrics

    merged = dict(metrics)
    filled: list[str] = list(merged.get("data_fallbacks") or [])
    for field in FALLBACK_FIELDS:
        if merged.get(field) is None and fallback.get(field) is not None:
            merged[field] = fallback[field]
            filled.append(f"{field} from Yahoo Finance fallback")

    if fallback.get("revenue_lfy") is not None and metrics.get("revenue_lfy") is None:
        merged["revenue_lfy_source"] = fallback.get("revenue_lfy_source") or "Yahoo Finance fallback"
        merged["revenue_lfy_is_estimated"] = True

    if filled:
        merged["source"] = "London Stock Exchange + Yahoo Finance fallback"
        merged["fallback_source"] = fallback.get("fallback_source", "Yahoo Finance")
        merged["yahoo_symbol"] = fallback.get("yahoo_symbol")
        merged["retrieved_yahoo"] = fallback.get("retrieved_yahoo")
        merged["data_fallbacks"] = sorted(dict.fromkeys(filled))
        get_logger(__name__).info(
            "Fallback data filled %s fields for %s",
            len(filled),
            merged.get("source_ticker") or fallback.get("yahoo_symbol"),
        )
    merged["data_coverage_ratio"] = _coverage_ratio(merged)
    return merged


def _merge_london_south_east_metrics(metrics: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        metrics["data_coverage_ratio"] = _coverage_ratio(metrics)
        return metrics

    merged = dict(metrics)
    filled: list[str] = list(merged.get("data_fallbacks") or [])
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
            filled.append(f"{field} from London South East share page")

    if fallback.get("share_price_url"):
        merged["share_price_url"] = fallback["share_price_url"]
    if filled:
        source = str(merged.get("source") or "London Stock Exchange")
        if "London South East share page" not in source:
            merged["source"] = f"{source} + London South East share page"
        merged["data_fallbacks"] = sorted(dict.fromkeys(filled))
    merged["data_coverage_ratio"] = _coverage_ratio(merged)
    return merged


def fetch_fundamentals(ticker_code: str, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch company fundamentals and market statistics from LSE sources."""
    ticker_code = normalize_lse_ticker(ticker_code)
    snapshot_row = get_market_snapshot_for_ticker(ticker_code)
    snapshot_sources: dict[str, dict[str, Any]] = {}
    if snapshot_row:
        identity = build_company_identity({"ticker": ticker_code, "company_name": snapshot_row.get("company_name")}, snapshot_row)
        snapshot_sources["market_snapshot"] = snapshot_row
        metrics = normalise_company_financials(identity, snapshot_sources)
        if metrics.get("display_safe_coverage_ratio", 0) >= 0.95:
            return metrics

    lse_metrics = fetch_company_snapshot(ticker_code, force_refresh=force_refresh)
    identity = build_company_identity({"ticker": ticker_code}, lse_metrics)
    sources: dict[str, dict[str, Any]] = {**snapshot_sources, "lse": lse_metrics}
    metrics = normalise_company_financials(identity, sources)
    if metrics.get("display_safe_coverage_ratio", 0) >= 0.95:
        return metrics

    try:
        lse_co_uk = fetch_share_price_snapshot(ticker_code, force_refresh=force_refresh)
        if lse_co_uk:
            sources["london_south_east_share"] = lse_co_uk
            metrics = normalise_company_financials(identity, sources)
    except Exception as exc:
        get_logger(__name__).warning("London South East share page fallback unavailable for %s: %s", ticker_code, exc)

    if metrics.get("display_safe_coverage_ratio", 0) >= 0.95:
        return metrics

    try:
        fallback = fetch_yahoo_london_fallback(ticker_code, force_refresh=force_refresh)
        if fallback:
            sources["yahoo"] = fallback
    except Exception as exc:
        get_logger(__name__).warning("Yahoo Finance fallback unavailable for %s: %s", ticker_code, exc)
    return normalise_company_financials(identity, sources)


def score_fundamentals(metrics: dict[str, Any]) -> dict[str, Any]:
    """Score reliable LSE-backed signals on a conservative 0-10 scale."""
    drivers: list[str] = []
    score = 5.0

    market_cap = metrics.get("market_cap")
    if market_cap:
        drivers.append("Market cap available")

    revenue = metrics.get("revenue_lfy")
    if revenue is None:
        drivers.append("Revenue LFY unavailable")
    elif metrics.get("revenue_lfy_is_estimated"):
        score += 0.5
        drivers.append("Revenue estimated from fallback data")
    elif revenue > 20_000_000:
        score += 1.0
        drivers.append("Revenue-generating (>20M LFY)")
    elif revenue > 0:
        score += 0.5
        drivers.append("Revenue-generating")
    else:
        score -= 1.0
        drivers.append("Pre-revenue / no LFY revenue")

    debt_to_capital = metrics.get("long_term_debt_to_capital_pct")
    net_debt_to_equity = metrics.get("net_debt_to_equity_pct")
    debt_metric = debt_to_capital if debt_to_capital is not None else net_debt_to_equity

    if debt_metric is None:
        drivers.append("Debt metric unavailable")
    elif debt_metric == 0:
        score += 1.0
        drivers.append("No LSE-reported debt burden")
    elif debt_metric <= 25:
        score += 0.5
        drivers.append("Moderate LSE-reported debt burden")
    elif debt_metric >= 50:
        score -= 1.5
        drivers.append("High LSE-reported debt burden")

    if metrics.get("fifty_two_week_low") is not None and metrics.get("fifty_two_week_high") is not None:
        drivers.append("52-week trading range available")

    coverage = metrics.get("data_coverage_ratio")
    if coverage is not None:
        drivers.append(f"Financial data coverage {coverage:.0%}")
    if metrics.get("data_fallbacks"):
        drivers.append("Fallback data source used")

    if not drivers:
        drivers.append("LSE data unavailable")

    score = min(max(score, 0), 10)
    return {"score": round(score, 2), "drivers": drivers}


def analyze_stock(ticker_code: str) -> dict[str, Any]:
    metrics = fetch_fundamentals(ticker_code)
    scored = score_fundamentals(metrics)
    return {"fundamentals": scored, "metrics": metrics}
