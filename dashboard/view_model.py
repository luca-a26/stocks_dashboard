from __future__ import annotations

from typing import Any

TABLE_COLUMNS = [
    "Ticker",
    "Company",
    "Alias",
    "Exchange",
    "Segment",
    "Score",
    "Rating",
    "Market Cap",
    "Last Price",
    "Revenue LFY",
    "Debt Metric",
    "Shares Outstanding",
    "Volume",
    "52W Range",
    "Drivers",
    "Source",
    "Retrieved UTC",
]


def _format_money(value: Any) -> str:
    if value is None:
        return "n/a"
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


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= divisor:
            return f"{number / divisor:.1f}{suffix}"
    return f"{number:,.0f}"


def _format_price(value: Any, currency: str | None = None) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    suffix = f" {currency}" if currency else ""
    return f"{number:g}{suffix}"


def _format_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_debt_metric(metrics: dict[str, Any]) -> str:
    debt_to_capital = metrics.get("long_term_debt_to_capital_pct")
    if debt_to_capital is not None:
        return f"{float(debt_to_capital):.1f}% LT debt/cap"

    net_debt_to_equity = metrics.get("net_debt_to_equity_pct")
    if net_debt_to_equity is not None:
        return f"{float(net_debt_to_equity):.1f}% net debt/equity"

    return "n/a"


def _format_range(low: Any, high: Any) -> str:
    if low is None or high is None:
        return "n/a"
    return f"{float(low):g} - {float(high):g}"


def _rating(score: float) -> str:
    if score >= 7:
        return "High conviction"
    if score >= 5:
        return "Constructive"
    if score >= 3:
        return "Watch"
    return "Review"


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

    return "; ".join(aliases) if aliases else ""


def build_dashboard_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stock in results:
        fundamentals = stock.get("fundamental", {}).get("fundamentals", {})
        metrics = stock.get("fundamental", {}).get("metrics", {})
        score = float(stock.get("composite_score") or fundamentals.get("score") or 0)
        drivers = fundamentals.get("drivers") or ["No material driver recorded"]
        company = metrics.get("issuer_name") or stock.get("name", stock.get("ticker", ""))

        rows.append(
            {
                "Ticker": stock.get("ticker", ""),
                "Company": company,
                "Alias": _alias(stock, company),
                "Exchange": metrics.get("market") or stock.get("exchange", "n/a"),
                "Segment": metrics.get("segment", "n/a"),
                "Score": round(score, 2),
                "Rating": _rating(score),
                "Market Cap": _format_money(metrics.get("market_cap")),
                "Last Price": _format_price(metrics.get("last_price"), metrics.get("currency")),
                "Revenue LFY": _format_money(metrics.get("revenue_lfy")),
                "Debt Metric": _format_debt_metric(metrics),
                "Shares Outstanding": _format_number(metrics.get("shares_outstanding_lfy")),
                "Volume": _format_number(metrics.get("volume")),
                "52W Range": _format_range(
                    metrics.get("fifty_two_week_low"),
                    metrics.get("fifty_two_week_high"),
                ),
                "Drivers": "; ".join(drivers),
                "Source": metrics.get("source", "n/a"),
                "Retrieved UTC": str(metrics.get("retrieved", "n/a"))[:19],
            }
        )
    return rows
