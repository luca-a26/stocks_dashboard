from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from data.utils import ensure_storage_path, get_logger

BASE_URL = "https://api.londonstockexchange.com/api/gw/lse"
WEBSITE_BASE_URL = "https://www.londonstockexchange.com"
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


def _get_text(url: str, cache_path: Path, force_refresh: bool = False) -> str:
    if not force_refresh and _cache_is_fresh(cache_path):
        return cache_path.read_text(encoding="utf-8")

    try:
        response = _session().get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        text = response.text
    except Exception:
        if cache_path.exists():
            get_logger(__name__).warning("Using stale LSE website cache for %s", url)
            return cache_path.read_text(encoding="utf-8")
        raise

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


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


def _first_number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value))
    return _to_float(match.group(0)) if match else None


def _parse_range_pair(value: Any) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if len(numbers) < 2:
        return None, None
    first = _to_float(numbers[0])
    second = _to_float(numbers[1])
    if first is None or second is None:
        return None, None
    return min(first, second), max(first, second)


def _estimate_market_cap(last_price: float | None, shares: float | None, currency: str | None) -> float | None:
    if last_price is None or shares is None:
        return None
    adjusted_price = last_price / 100 if str(currency or "").upper() in {"GBX", "GBPX"} else last_price
    return adjusted_price * shares


def _coverage_ratio(metrics: dict[str, Any]) -> float:
    checks = [
        metrics.get("market_cap") is not None,
        metrics.get("last_price") is not None,
        metrics.get("volume") is not None,
        metrics.get("fifty_two_week_low") is not None and metrics.get("fifty_two_week_high") is not None,
        metrics.get("revenue_lfy") is not None,
        metrics.get("long_term_debt_to_capital_pct") is not None or metrics.get("net_debt_to_equity_pct") is not None,
        metrics.get("shares_outstanding_lfy") is not None,
    ]
    return round(sum(checks) / len(checks), 3)


def _slugify(value: str | None) -> str:
    text = str(value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "company"


def _page_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return [line.strip() for line in _normalise_text(soup.get_text("\n")).splitlines() if line.strip()]


def _value_after_label(lines: list[str], *labels: str) -> str | None:
    skip_values = {"what's this?", "what's this", "-"}
    label_options = {label.lower() for label in labels}
    for index, line in enumerate(lines):
        normalised = line.lower()
        if normalised not in label_options:
            continue
        for candidate in lines[index + 1 : index + 8]:
            if candidate.strip().lower() not in skip_values:
                return candidate.strip()
    return None


def _parse_lse_company_page(html: str) -> dict[str, Any]:
    """Parse public LSE stock pages for fields missing from API/PDF routes."""
    lines = _page_lines(html)
    if not lines:
        return {}

    parsed: dict[str, Any] = {}
    price_label = next((line for line in lines if re.fullmatch(r"Price \([A-Z]{2,4}\)", line)), None)
    if price_label:
        parsed["currency"] = price_label[price_label.find("(") + 1 : price_label.find(")")]
        parsed["last_price"] = _first_number(_value_after_label(lines, price_label))

    market_cap_m = _first_number(
        _value_after_label(lines, "Instrument market cap (£m)", "Issuer Market Cap £m", "Market Cap (£m)")
    )
    if market_cap_m is not None:
        parsed["market_cap"] = market_cap_m * 1_000_000

    volume = _first_number(_value_after_label(lines, "Volume"))
    if volume is not None:
        parsed["volume"] = volume

    low, high = _parse_range_pair(_value_after_label(lines, "52 week range", "52-Week Range"))
    if low is not None and high is not None:
        parsed["fifty_two_week_low"] = low
        parsed["fifty_two_week_high"] = high

    field_map = {
        "market": ("Market",),
        "segment": ("Market segment",),
        "trading_service": ("Trading service",),
        "isin": ("ISIN",),
        "country_of_share_register": ("Country of share register",),
        "country_of_incorporation": ("Country of Incorporation",),
        "ftse_sector": ("FTSE sector",),
        "ftse_subsector": ("FTSE subsector",),
    }
    for field, labels in field_map.items():
        value = _value_after_label(lines, *labels)
        if value:
            parsed[field] = value

    return parsed


def _fetch_lse_website_section(
    ticker_code: str,
    issuer_name: str | None,
    section: str,
    force_refresh: bool = False,
) -> tuple[str, str]:
    ticker = ticker_code.upper()
    slug = _slugify(issuer_name)
    url = f"{WEBSITE_BASE_URL}/stock/{ticker}/{slug}/{section}"
    html = _get_text(url, CACHE_DIR / f"{ticker}_{section}.html", force_refresh)
    return url, html


def fetch_lse_website_data(
    ticker_code: str,
    issuer_name: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch public LSE website fields used to correct API/PDF inconsistencies."""
    combined: dict[str, Any] = {}
    urls: list[str] = []
    for section in ("company-page", "our-story", "fundamentals"):
        try:
            url, html = _fetch_lse_website_section(ticker_code, issuer_name, section, force_refresh)
        except Exception as exc:
            get_logger(__name__).warning("LSE website %s fetch failed for %s: %s", section, ticker_code, exc)
            continue
        parsed = _parse_lse_company_page(html)
        if parsed:
            combined.update({key: value for key, value in parsed.items() if value not in (None, "")})
            urls.append(url)

    if combined:
        combined["lse_website_urls"] = urls
        get_logger(__name__).info("LSE website fallback parsed %s fields for %s", len(combined), ticker_code.upper())
    return combined


def _merge_lse_website_data(snapshot: dict[str, Any], website: dict[str, Any]) -> dict[str, Any]:
    if not website:
        return snapshot

    merged = dict(snapshot)
    notes: list[str] = list(merged.get("data_fallbacks") or [])
    for field in (
        "last_price",
        "currency",
        "volume",
        "fifty_two_week_low",
        "fifty_two_week_high",
        "market",
        "segment",
        "trading_service",
        "isin",
        "country_of_share_register",
        "country_of_incorporation",
        "ftse_sector",
        "ftse_subsector",
    ):
        if merged.get(field) in (None, "") and website.get(field) not in (None, ""):
            merged[field] = website[field]
            notes.append(f"{field} from LSE company page")

    website_market_cap = website.get("market_cap")
    existing_market_cap = merged.get("market_cap")
    if website_market_cap is not None and existing_market_cap is None:
        merged["market_cap"] = website_market_cap
        notes.append("market_cap from LSE company page")
    elif website_market_cap is not None and existing_market_cap:
        difference = abs(float(existing_market_cap) - float(website_market_cap)) / max(abs(float(website_market_cap)), 1)
        if difference > 0.15:
            merged["market_cap"] = website_market_cap
            notes.append("market_cap corrected using LSE company page")

    if website.get("lse_website_urls"):
        merged["lse_website_urls"] = website["lse_website_urls"]
    if notes:
        merged["data_fallbacks"] = sorted(dict.fromkeys(notes))
    return merged


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
    analytics = fetch_ftse_analytics_data(ticker_code, force_refresh)

    currency = instrument.get("currency")
    last_price = _to_float(instrument.get("lastprice"))
    shares = tearsheet.get("shares_outstanding_lfy")
    market_cap = _to_float(instrument.get("marketcapitalization"))
    fallbacks: list[str] = []
    if market_cap is None and tearsheet.get("tearsheet_market_value") is not None:
        market_cap = tearsheet.get("tearsheet_market_value")
        fallbacks.append("market_cap from LSE tearsheet market value")
    estimated_market_cap = _estimate_market_cap(last_price, shares, currency)
    if market_cap is None and estimated_market_cap is not None:
        market_cap = estimated_market_cap
        fallbacks.append("market_cap estimated from last price and shares outstanding")

    low = _to_float(instrument.get("fiftyTwoWeeksMin"))
    high = _to_float(instrument.get("fiftyTwoWeeksMax"))
    if low is None or high is None:
        range_low, range_high = _parse_range_pair(tearsheet.get("fifty_two_week_range"))
        low = low if low is not None else range_low
        high = high if high is not None else range_high
        if range_low is not None and range_high is not None:
            fallbacks.append("52-week range from LSE tearsheet")

    revenue = tearsheet.get("revenue_lfy")
    revenue_source = "LSE tearsheet" if revenue is not None else None
    price_to_sales = analytics.get("price_to_sales")
    if revenue is None and market_cap is not None and price_to_sales not in (None, 0):
        revenue = market_cap / price_to_sales
        revenue_source = "FTSE analytics price/sales estimate"
        fallbacks.append("revenue estimated from market cap and price/sales")

    issuer_name = instrument.get("issuername") or instrument.get("shortname")
    snapshot = {
        "source": "London Stock Exchange",
        "source_ticker": instrument.get("tidm", ticker_code.upper()),
        "issuer_name": issuer_name,
        "short_name": instrument.get("shortname"),
        "isin": instrument.get("isin"),
        "currency": currency,
        "market": instrument.get("market"),
        "segment": instrument.get("segment"),
        "sector_code": instrument.get("sectorcode"),
        "subsector_code": instrument.get("subsectorcode"),
        "issuer_code": instrument.get("issuercode"),
        "market_cap": market_cap,
        "market_cap_estimated": estimated_market_cap if "market_cap estimated from last price and shares outstanding" in fallbacks else None,
        "last_price": last_price,
        "bid": _to_float(instrument.get("bid")),
        "offer": _to_float(instrument.get("offer")),
        "volume": _to_float(instrument.get("volume")),
        "turnover": _to_float(instrument.get("turnover")),
        "fifty_two_week_low": low,
        "fifty_two_week_high": high,
        "listing_admission_date": instrument.get("listingadmissiondate"),
        "last_price_date": instrument.get("lastpricedate") or instrument.get("lastclosedate"),
        "revenue_lfy": revenue,
        "revenue_lfy_source": revenue_source,
        "revenue_lfy_is_estimated": revenue_source == "FTSE analytics price/sales estimate",
        "revenue_lfy_m": tearsheet.get("revenue_lfy_m"),
        "long_term_debt_to_capital_pct": tearsheet.get("long_term_debt_to_capital_pct"),
        "net_debt_to_equity_pct": analytics.get("net_debt_to_equity_pct"),
        "price_to_sales": price_to_sales,
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
        "data_fallbacks": fallbacks,
        "retrieved": datetime.now(timezone.utc).isoformat(),
    }
    if _coverage_ratio(snapshot) < 0.95:
        snapshot = _merge_lse_website_data(
            snapshot,
            fetch_lse_website_data(ticker_code, issuer_name, force_refresh=force_refresh),
        )
    snapshot["data_coverage_ratio"] = _coverage_ratio(snapshot)
    return snapshot
