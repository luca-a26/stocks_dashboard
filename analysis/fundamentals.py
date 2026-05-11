from __future__ import annotations

from typing import Any

from data.lse import fetch_company_snapshot


def fetch_fundamentals(ticker_code: str) -> dict[str, Any]:
    """Fetch company fundamentals and market statistics from LSE sources."""
    return fetch_company_snapshot(ticker_code)


def score_fundamentals(metrics: dict[str, Any]) -> dict[str, Any]:
    """Score reliable LSE-backed signals on a conservative 0-10 scale."""
    drivers: list[str] = []
    score = 5.0

    market_cap = metrics.get("market_cap")
    if market_cap:
        drivers.append("LSE market cap available")

    revenue = metrics.get("revenue_lfy")
    if revenue is None:
        drivers.append("Revenue LFY unavailable")
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

    if not drivers:
        drivers.append("LSE data unavailable")

    score = min(max(score, 0), 10)
    return {"score": round(score, 2), "drivers": drivers}


def analyze_stock(ticker_code: str) -> dict[str, Any]:
    metrics = fetch_fundamentals(ticker_code)
    scored = score_fundamentals(metrics)
    return {"fundamentals": scored, "metrics": metrics}
