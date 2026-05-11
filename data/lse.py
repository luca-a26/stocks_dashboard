from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from data.utils import ensure_storage_path, get_logger

BASE_URL = "https://api.londonstockexchange.com/api/gw/lse"
CACHE_DIR = ensure_storage_path("storage/cache/lse")
CACHE_TTL = timedelta(hours=6)
REQUEST_TIMEOUT = 20

HEADERS = {
    "Accept": "application/json,application/pdf,text/plain,*/*",
    "User-Agent": "strategic-metals-dashboard/0.1",
}

TEARSHEET_FIELDS = [
    "employees",
    "revenue_lfy_m",
    "eps_diluted_lfy",
    "market_value_m",
    "shares_outstanding_lfy_000",
    "book_value_per_share",
    "ebitda_margin_pct",
    "net_margin_pct",
    "long_term_debt_to_capital_pct",
    "dividends_and_yield_ttm",
    "payout_ratio_ttm_pct",
    "average_volume_60d_000",
    "fifty_two_week_range",
    "price_to_52_week_range",
]


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


def _get_json(url: str, cache_path: Path, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh and _cache_is_fresh(cache_path):
        return _read_json_cache(cache_path)

    try:
        response = _session().get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        if cache_path.exists():
            get_logger(__name__).warning("Using stale LSE JSON cache for %s", url)
            return _read_json_cache(cache_path)
        raise

    _write_json_cache(cache_path, payload)
    return payload


def _get_bytes(url: str, cache_path: Path, force_refresh: bool = False) -> bytes:
    if not force_refresh and _cache_is_fresh(cache_path):
        return cache_path.read_bytes()

    try:
        response = _session().get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content = response.content
    except Exception:
        if cache_path.exists():
            get_logger(__name__).warning("Using stale LSE PDF cache for %s", url)
            return cache_path.read_bytes()
        raise

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(content)
    return content


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if text in {"", "-", "N/A", "None"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _normalise_text(text: str) -> str:
    return text.replace("\u0141", "L").replace("\ufffd", "?")


def _parse_tearsheet_page(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in _normalise_text(text).splitlines() if line.strip()]
    country_index = next((index for index, line in enumerate(lines) if line == "GBR"), None)
    if country_index is None:
        return {}

    values = lines[country_index + 1 : country_index + 1 + len(TEARSHEET_FIELDS)]
    if len(values) < 5:
        return {}

    parsed = dict(zip(TEARSHEET_FIELDS, values))
    numeric_fields = {
        "employees",
        "revenue_lfy_m",
        "eps_diluted_lfy",
        "market_value_m",
        "shares_outstanding_lfy_000",
        "book_value_per_share",
        "ebitda_margin_pct",
        "net_margin_pct",
        "long_term_debt_to_capital_pct",
        "payout_ratio_ttm_pct",
        "average_volume_60d_000",
    }

    for field in numeric_fields:
        parsed[field] = _to_float(parsed.get(field))

    if parsed.get("revenue_lfy_m") is not None:
        parsed["revenue_lfy"] = parsed["revenue_lfy_m"] * 1_000_000
    if parsed.get("market_value_m") is not None:
        parsed["tearsheet_market_value"] = parsed["market_value_m"] * 1_000_000
    if parsed.get("shares_outstanding_lfy_000") is not None:
        parsed["shares_outstanding_lfy"] = parsed["shares_outstanding_lfy_000"] * 1_000

    return parsed


def _parse_ftse_analytics_page(text: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", " ", _normalise_text(text))
    parsed: dict[str, Any] = {}

    net_debt_match = re.search(r"Net Debt/Equity\s+(-?\d+(?:\.\d+)?)", compact, re.IGNORECASE)
    if net_debt_match:
        parsed["net_debt_to_equity_pct"] = _to_float(net_debt_match.group(1))

    price_sales_match = re.search(r"Price/Sales\s+(-?\d+(?:\.\d+)?)", compact, re.IGNORECASE)
    if price_sales_match:
        parsed["price_to_sales"] = _to_float(price_sales_match.group(1))

    price_book_match = re.search(r"\bPB\s+(-?\d+(?:\.\d+)?)", compact, re.IGNORECASE)
    if price_book_match:
        parsed["price_to_book"] = _to_float(price_book_match.group(1))

    return parsed


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - depends on installed optional package
        get_logger(__name__).warning("pypdf is unavailable; cannot parse LSE tearsheet: %s", exc)
        return ""

    reader = PdfReader(io.BytesIO(content))
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def fetch_instrument_data(ticker_code: str, force_refresh: bool = False) -> dict[str, Any]:
    ticker = ticker_code.upper()
    url = f"{BASE_URL}/instruments/alldata/{ticker}"
    return _get_json(url, CACHE_DIR / f"{ticker}_alldata.json", force_refresh)


def fetch_tearsheet_data(
    ticker_code: str,
    issuer_code: str | None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not issuer_code:
        return {}

    ticker = ticker_code.upper()
    safe_issuer = re.sub(r"[^A-Za-z0-9_.-]+", "_", issuer_code)
    url = f"{BASE_URL}/download/{issuer_code}/tearsheet"
    try:
        content = _get_bytes(url, CACHE_DIR / f"{ticker}_{safe_issuer}_tearsheet.pdf", force_refresh)
    except Exception as exc:
        get_logger(__name__).warning("LSE tearsheet fetch failed for %s: %s", ticker, exc)
        return {}

    if content.lstrip().startswith(b"{"):
        get_logger(__name__).warning("LSE tearsheet unavailable for %s", ticker)
        return {}

    return _parse_tearsheet_page(_extract_pdf_text(content))


def fetch_ftse_analytics_data(ticker_code: str, force_refresh: bool = False) -> dict[str, Any]:
    ticker = ticker_code.upper()
    url = f"{BASE_URL}/download/{ticker}/ftse-analytics"
    try:
        content = _get_bytes(url, CACHE_DIR / f"{ticker}_ftse_analytics.pdf", force_refresh)
    except Exception as exc:
        get_logger(__name__).warning("LSE FTSE analytics fetch failed for %s: %s", ticker, exc)
        return {}

    if content.lstrip().startswith(b"{"):
        return {}
    return _parse_ftse_analytics_page(_extract_pdf_text(content))


def fetch_company_snapshot(ticker_code: str, force_refresh: bool = False) -> dict[str, Any]:
    instrument = fetch_instrument_data(ticker_code, force_refresh)
    tearsheet = fetch_tearsheet_data(
        ticker_code,
        instrument.get("issuercode"),
        force_refresh,
    )
    analytics = fetch_ftse_analytics_data(ticker_code, force_refresh) if not tearsheet else {}

    return {
        "source": "London Stock Exchange",
        "source_ticker": instrument.get("tidm", ticker_code.upper()),
        "issuer_name": instrument.get("issuername") or instrument.get("shortname"),
        "short_name": instrument.get("shortname"),
        "isin": instrument.get("isin"),
        "currency": instrument.get("currency"),
        "market": instrument.get("market"),
        "segment": instrument.get("segment"),
        "sector_code": instrument.get("sectorcode"),
        "subsector_code": instrument.get("subsectorcode"),
        "issuer_code": instrument.get("issuercode"),
        "market_cap": _to_float(instrument.get("marketcapitalization")),
        "last_price": _to_float(instrument.get("lastprice")),
        "bid": _to_float(instrument.get("bid")),
        "offer": _to_float(instrument.get("offer")),
        "volume": _to_float(instrument.get("volume")),
        "turnover": _to_float(instrument.get("turnover")),
        "fifty_two_week_low": _to_float(instrument.get("fiftyTwoWeeksMin")),
        "fifty_two_week_high": _to_float(instrument.get("fiftyTwoWeeksMax")),
        "listing_admission_date": instrument.get("listingadmissiondate"),
        "last_price_date": instrument.get("lastpricedate") or instrument.get("lastclosedate"),
        "revenue_lfy": tearsheet.get("revenue_lfy"),
        "revenue_lfy_m": tearsheet.get("revenue_lfy_m"),
        "long_term_debt_to_capital_pct": tearsheet.get("long_term_debt_to_capital_pct"),
        "net_debt_to_equity_pct": analytics.get("net_debt_to_equity_pct"),
        "price_to_sales": analytics.get("price_to_sales"),
        "price_to_book": analytics.get("price_to_book"),
        "shares_outstanding_lfy": tearsheet.get("shares_outstanding_lfy"),
        "average_volume_60d": (
            tearsheet.get("average_volume_60d_000") * 1_000
            if tearsheet.get("average_volume_60d_000") is not None
            else None
        ),
        "book_value_per_share": tearsheet.get("book_value_per_share"),
        "ebitda_margin_pct": tearsheet.get("ebitda_margin_pct"),
        "net_margin_pct": tearsheet.get("net_margin_pct"),
        "fifty_two_week_range": tearsheet.get("fifty_two_week_range"),
        "price_to_52_week_range": tearsheet.get("price_to_52_week_range"),
        "retrieved": datetime.now(timezone.utc).isoformat(),
    }
