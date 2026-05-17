from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from data.utils import ensure_storage_path, get_logger

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
SUMMARY_URL = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=price,summaryDetail,financialData,defaultKeyStatistics"
)
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
CACHE_DIR = ensure_storage_path("storage/cache/yahoo")
CACHE_TTL = timedelta(hours=6)
REQUEST_TIMEOUT = 20
CHART_REQUEST_TIMEOUT = 8

HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "User-Agent": "strategic-metals-dashboard/0.1 (+financial-fallback)",
}


def yahoo_london_symbol(ticker_code: str) -> str:
    """Return the Yahoo Finance symbol normally used for LSE-listed equities."""
    ticker = ticker_code.strip().upper()
    return ticker if ticker.endswith(".L") else f"{ticker}.L"


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)
    return session


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified < CACHE_TTL


def _read_json_cache(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def _get_json(
    url: str,
    cache_path: Path,
    force_refresh: bool = False,
    *,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    if not force_refresh and _cache_is_fresh(cache_path):
        return _read_json_cache(cache_path)

    try:
        response = _session().get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        if cache_path.exists():
            get_logger(__name__).warning("Using stale Yahoo Finance cache for %s", url)
            return _read_json_cache(cache_path)
        raise

    _write_json_cache(cache_path, payload)
    return payload


def _raw(value: Any) -> Any:
    if isinstance(value, dict) and "raw" in value:
        return value.get("raw")
    return value


def _to_float(value: Any) -> float | None:
    value = _raw(value)
    if value in (None, "", "-", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("quoteResponse", {}).get("result") or []
    if not result:
        return {}
    quote_data = result[0]
    return {
        "market_cap": _to_float(quote_data.get("marketCap")),
        "last_price": _to_float(quote_data.get("regularMarketPrice")),
        "currency": quote_data.get("currency"),
        "volume": _to_float(quote_data.get("regularMarketVolume")),
        "fifty_two_week_low": _to_float(quote_data.get("fiftyTwoWeekLow")),
        "fifty_two_week_high": _to_float(quote_data.get("fiftyTwoWeekHigh")),
        "shares_outstanding_lfy": _to_float(quote_data.get("sharesOutstanding")),
    }


def _summary_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("quoteSummary", {}).get("result") or []
    if not result:
        return {}
    summary = result[0]
    price = summary.get("price") or {}
    detail = summary.get("summaryDetail") or {}
    financial = summary.get("financialData") or {}
    key_stats = summary.get("defaultKeyStatistics") or {}
    return {
        "market_cap": _to_float(price.get("marketCap")),
        "last_price": _to_float(price.get("regularMarketPrice") or financial.get("currentPrice")),
        "currency": price.get("currency"),
        "volume": _to_float(price.get("regularMarketVolume") or detail.get("volume")),
        "fifty_two_week_low": _to_float(detail.get("fiftyTwoWeekLow")),
        "fifty_two_week_high": _to_float(detail.get("fiftyTwoWeekHigh")),
        "revenue_lfy": _to_float(financial.get("totalRevenue")),
        "revenue_lfy_source": "Yahoo Finance totalRevenue fallback",
        "total_debt": _to_float(financial.get("totalDebt")),
        "net_debt_to_equity_pct": _to_float(financial.get("debtToEquity")),
        "shares_outstanding_lfy": _to_float(key_stats.get("sharesOutstanding")),
        "price_to_sales": _to_float(detail.get("priceToSalesTrailing12Months")),
        "price_to_book": _to_float(key_stats.get("priceToBook")),
    }


def _clean_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if value is not None}


def _chart_points(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse Yahoo chart payloads into dashboard-safe close-price points."""
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return {}

    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote_rows = chart.get("indicators", {}).get("quote") or []
    closes = quote_rows[0].get("close") if quote_rows and isinstance(quote_rows[0], dict) else []
    if not timestamps or not closes:
        return {}

    points: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        close_value = _to_float(close)
        if close_value is None:
            continue
        try:
            date_value = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        points.append({"date": date_value, "close": close_value})

    meta = chart.get("meta") or {}
    return {
        "symbol": meta.get("symbol"),
        "currency": meta.get("currency"),
        "points": points,
    }


def fetch_yahoo_london_fallback(ticker_code: str, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch cached fallback market/fundamental data for a London-listed ticker.

    Yahoo is used only as a secondary enrichment source. The dashboard records
    fallback provenance so users can see when non-LSE data filled a missing LSE
    field.
    """
    symbol = yahoo_london_symbol(ticker_code)
    safe_symbol = quote(symbol, safe="")
    quote_payload = _get_json(
        QUOTE_URL.format(symbol=safe_symbol),
        CACHE_DIR / f"{symbol}_quote.json",
        force_refresh,
    )
    quote_metrics = _quote_metrics(quote_payload)

    try:
        summary_payload = _get_json(
            SUMMARY_URL.format(symbol=safe_symbol),
            CACHE_DIR / f"{symbol}_summary.json",
            force_refresh,
        )
        summary_metrics = _summary_metrics(summary_payload)
    except Exception as exc:
        get_logger(__name__).warning("Yahoo Finance summary fallback failed for %s: %s", symbol, exc)
        summary_metrics = {}

    metrics = _clean_metrics({**quote_metrics, **summary_metrics})
    if not metrics:
        return {}
    metrics.update(
        {
            "fallback_source": "Yahoo Finance",
            "yahoo_symbol": symbol,
            "retrieved_yahoo": datetime.now(timezone.utc).isoformat(),
        }
    )
    get_logger(__name__).info("Yahoo Finance fallback loaded for %s with %s fields", symbol, len(metrics))
    return metrics


def fetch_yahoo_price_history(
    ticker_code: str,
    *,
    range_value: str = "1y",
    interval: str = "1d",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch cached Yahoo close-price history for a London-listed ticker.

    This is used by the dashboard modal only after a company is selected; it is
    deliberately not part of startup data loading.
    """
    symbol = yahoo_london_symbol(ticker_code)
    safe_symbol = quote(symbol, safe="")
    cache_path = CACHE_DIR / f"{symbol}_chart_{range_value}_{interval}.json"
    payload = _get_json(
        CHART_URL.format(symbol=safe_symbol, range=range_value, interval=interval),
        cache_path,
        force_refresh,
        timeout=CHART_REQUEST_TIMEOUT,
    )
    parsed = _chart_points(payload)
    if not parsed.get("points"):
        return {}
    parsed.update(
        {
            "symbol": parsed.get("symbol") or symbol,
            "range": range_value,
            "interval": interval,
            "source": "Yahoo Finance chart",
            "retrieved_yahoo_chart": datetime.now(timezone.utc).isoformat(),
        }
    )
    return parsed
