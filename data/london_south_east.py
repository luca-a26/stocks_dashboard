from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from data.utils import ensure_storage_path, get_logger

INDUSTRIAL_METALS_URL = (
    "https://www.lse.co.uk/share-prices/sectors/industrial-metals/constituents.html"
)
CACHE_DIR = ensure_storage_path("storage/cache/london_south_east")
INDUSTRIAL_METALS_HTML_CACHE = CACHE_DIR / "industrial_metals_constituents.html"
INDUSTRIAL_METALS_CACHE = CACHE_DIR / "industrial_metals_universe.csv"
REQUEST_TIMEOUT = 30
SHARE_PRICE_URL = "https://www.lse.co.uk/SharePrice.html?shareprice={ticker}&share={slug}"

UNIVERSE_EXPORT_FIELDS = [
    "ticker",
    "exchange",
    "company_name",
    "country",
    "sector",
    "commodity_tags",
    "supply_chain_role",
    "stage",
    "market_cap_tier",
    "source",
    "notes",
    "priority",
    "last_price",
    "currency",
    "market_cap",
    "shares_outstanding_lfy",
    "volume",
    "day_change_pct",
    "day_low",
    "day_high",
    "fifty_two_week_low",
    "fifty_two_week_high",
    "trades",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "strategic-metals-dashboard/0.1 (+sector-universe-refresh)",
}

SHARE_PRICE_TEXT_PATTERN = re.compile(
    r"^(?P<company>.+?)\s+\((?P<ticker>[A-Z0-9.]{1,8})\)\s+Share Price$",
    re.IGNORECASE,
)


def sector_cache_ttl() -> timedelta:
    """Return the London South East sector-list cache TTL."""
    days = float(os.getenv("LSE_SECTOR_CACHE_TTL_DAYS", "7"))
    return timedelta(days=days)


def _cache_is_fresh(path: Path, ttl: timedelta | None = None) -> bool:
    if not path.exists():
        return False
    ttl = sector_cache_ttl() if ttl is None else ttl
    if ttl <= timedelta(0):
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified < ttl


def _normalise_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _valid_ticker(value: str) -> bool:
    ticker = value.strip().upper()
    return bool(re.fullmatch(r"[A-Z0-9.]{1,8}", ticker)) and not ticker.startswith("NMX")


def _ticker_from_href(href: str) -> str:
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    for key in ("shareprice", "tidm", "ticker"):
        values = query.get(key)
        if values and _valid_ticker(values[0]):
            return values[0].upper()

    match = re.search(r"(?:shareprice|tidm|ticker)=([A-Z0-9.]{1,8})", href, re.IGNORECASE)
    if match and _valid_ticker(match.group(1)):
        return match.group(1).upper()
    return ""


def _to_number(value: str) -> float | None:
    text = (
        value.strip()
        .replace(",", "")
        .replace("%", "")
        .replace("£", "")
        .replace("$", "")
        .replace("€", "")
    )
    if text in {"", "-", "n/a", "N/A"}:
        return None
    multiplier = 1.0
    lowered = text.lower()
    for suffix, factor in (("bn", 1_000_000_000), ("b", 1_000_000_000), ("m", 1_000_000), ("k", 1_000)):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _slugify(value: str) -> str:
    text = value.strip().replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return text.strip("-") or "Company"


def _html_text_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return [_normalise_ws(line) for line in soup.get_text("\n").splitlines() if _normalise_ws(line)]


def _value_after_label(lines: list[str], *labels: str) -> str | None:
    labels_lower = {label.lower() for label in labels}
    for index, line in enumerate(lines):
        if line.lower() not in labels_lower:
            continue
        for candidate in lines[index + 1 : index + 6]:
            if candidate and candidate.lower() not in {"-", "n/a"}:
                return candidate
    return None


def _regex_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return _to_number(match.group(1)) if match else None


def _parse_share_price_page(html: str) -> dict[str, Any]:
    """Parse London South East share pages for basic market fields."""
    text = _normalise_ws(BeautifulSoup(html, "html.parser").get_text(" "))
    lines = _html_text_lines(html)
    parsed: dict[str, Any] = {}

    market_cap = _regex_number(text, r"Market Cap:\s*£\s*([0-9,.]+[mbk]?)")
    if market_cap is None:
        market_cap = _regex_number(text, r"Market Cap\s+£\s*([0-9,.]+[mbk]?)")
    if market_cap is not None:
        parsed["market_cap"] = market_cap

    price = _regex_number(text, r"Share Price is delayed by 15 minutes\s+Get Live Data\s+([0-9,.]+)")
    if price is None:
        price = _to_number(_value_after_label(lines, "Price"))
    if price is not None:
        parsed["last_price"] = price

    volume = _to_number(_value_after_label(lines, "Volume") or "")
    if volume is not None:
        parsed["volume"] = volume

    shares = _regex_number(text, r"Shares in Issue\s+([0-9,.]+[mbk]?)")
    if shares is not None:
        parsed["shares_outstanding_lfy"] = shares

    year_high = _to_number(_value_after_label(lines, "Year High") or "")
    year_low = _to_number(_value_after_label(lines, "Year Low") or "")
    if year_low is not None:
        parsed["fifty_two_week_low"] = year_low
    if year_high is not None:
        parsed["fifty_two_week_high"] = year_high

    currency = _value_after_label(lines, "Currency")
    if currency:
        parsed["currency"] = currency
    issue_country = _value_after_label(lines, "Issue Country")
    if issue_country:
        parsed["country"] = issue_country
    trades = _to_number(_value_after_label(lines, "# Trades", "Trades") or "")
    if trades is not None:
        parsed["trades"] = trades

    return parsed


def fetch_share_price_snapshot(
    ticker: str,
    company_name: str = "",
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    slug = _slugify(company_name or ticker)
    url = SHARE_PRICE_URL.format(ticker=ticker, slug=slug)
    cache_path = CACHE_DIR / f"{ticker}_share_price.html"
    if not force_refresh and _cache_is_fresh(cache_path):
        html = cache_path.read_text(encoding="utf-8")
    else:
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            html = response.text
            cache_path.write_text(html, encoding="utf-8")
        except Exception:
            if cache_path.exists():
                get_logger(__name__).warning("Using stale London South East share page cache for %s", ticker)
                html = cache_path.read_text(encoding="utf-8")
            else:
                raise

    parsed = _parse_share_price_page(html)
    if parsed:
        parsed["source"] = "London South East share page"
        parsed["share_price_url"] = url
        get_logger(__name__).info("London South East share page parsed %s fields for %s", len(parsed), ticker)
    return parsed


def _record(ticker: str, company_name: str, market_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    market_fields = market_fields or {}
    return {
        "ticker": ticker.upper(),
        "exchange": "LSE",
        "company_name": company_name,
        "country": "",
        "sector": "Industrial Metals",
        "commodity_tags": "industrial metals",
        "supply_chain_role": "",
        "stage": "",
        "market_cap_tier": "",
        "source": "London South East Industrial Metals",
        "notes": "Imported from London South East Industrial Metals sector constituents.",
        "priority": "",
        "last_price": market_fields.get("last_price", ""),
        "currency": market_fields.get("currency", ""),
        "market_cap": market_fields.get("market_cap", ""),
        "shares_outstanding_lfy": market_fields.get("shares_outstanding_lfy", ""),
        "volume": market_fields.get("volume", ""),
        "day_change_pct": market_fields.get("day_change_pct", ""),
        "day_low": market_fields.get("day_low", ""),
        "day_high": market_fields.get("day_high", ""),
        "fifty_two_week_low": market_fields.get("fifty_two_week_low", ""),
        "fifty_two_week_high": market_fields.get("fifty_two_week_high", ""),
        "trades": market_fields.get("trades", ""),
    }


def fetch_industrial_metals_html(force_refresh: bool = False) -> str:
    """
    Fetch the London South East Industrial Metals constituents page with caching.

    This fetches only lightweight sector-list HTML. It deliberately does not
    download per-company market or financial data for every constituent.
    """
    if not force_refresh and _cache_is_fresh(INDUSTRIAL_METALS_HTML_CACHE):
        get_logger(__name__).info(
            "London South East sector HTML cache hit: %s", INDUSTRIAL_METALS_HTML_CACHE
        )
        return INDUSTRIAL_METALS_HTML_CACHE.read_text(encoding="utf-8")

    try:
        response = requests.get(INDUSTRIAL_METALS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        html = response.text
    except Exception:
        if INDUSTRIAL_METALS_HTML_CACHE.exists():
            get_logger(__name__).warning("Using stale London South East sector HTML cache")
            return INDUSTRIAL_METALS_HTML_CACHE.read_text(encoding="utf-8")
        raise

    INDUSTRIAL_METALS_HTML_CACHE.write_text(html, encoding="utf-8")
    get_logger(__name__).info("Fetched London South East Industrial Metals sector HTML")
    return html


def parse_industrial_metals_constituents(html: str) -> list[dict[str, Any]]:
    """Parse London South East sector constituent links into cheap universe metadata."""
    soup = BeautifulSoup(html, "html.parser")
    records_by_ticker: dict[str, dict[str, Any]] = {}
    scopes = soup.select("table.sp-constituents__table") or [soup]

    for scope in scopes:
        row_nodes = scope.find_all("tr")
        if row_nodes:
            candidate_nodes = row_nodes
        else:
            candidate_nodes = scope.find_all("a")

        for node in candidate_nodes:
            anchor = node.find("a", href=lambda href: href and "shareprice" in href.lower()) if node.name != "a" else node
            if anchor is None:
                continue
            text = _normalise_ws(anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "")
            if not text or "shareprice" not in href.lower():
                continue

            match = SHARE_PRICE_TEXT_PATTERN.match(text)
            ticker = match.group("ticker").upper() if match else _ticker_from_href(href)
            if not ticker or not _valid_ticker(ticker):
                continue

            company_name = match.group("company").strip() if match else text
            company_name = re.sub(r"\s*\([A-Z0-9.]{1,8}\)\s*", " ", company_name)
            company_name = company_name.replace("Share Price", "")
            company_name = _normalise_ws(company_name)

            if not company_name or company_name.lower() == "industrial metals":
                continue
            if len(company_name) > 120:
                continue

            cells = node.find_all("td") if node.name == "tr" else []
            market_fields: dict[str, Any] = {}
            if len(cells) >= 7:
                market_fields = {
                    "last_price": _to_number(cells[1].get_text(" ", strip=True)),
                    "volume": _to_number(cells[2].get_text(" ", strip=True)),
                    "day_change_pct": _to_number(cells[3].get_text(" ", strip=True)),
                    "day_low": _to_number(cells[4].get_text(" ", strip=True)),
                    "day_high": _to_number(cells[5].get_text(" ", strip=True)),
                    "trades": _to_number(cells[6].get_text(" ", strip=True)),
                }

            records_by_ticker[ticker] = _record(ticker, company_name, market_fields)

    if not records_by_ticker:
        for line in soup.get_text("\n", strip=True).splitlines():
            match = SHARE_PRICE_TEXT_PATTERN.match(_normalise_ws(line))
            if not match:
                continue
            ticker = match.group("ticker").upper()
            if _valid_ticker(ticker):
                records_by_ticker[ticker] = _record(ticker, match.group("company").strip())

    records = sorted(records_by_ticker.values(), key=lambda item: item["company_name"])
    get_logger(__name__).info(
        "Parsed %s London South East Industrial Metals constituents", len(records)
    )
    return records


def write_universe_csv(records: list[dict[str, Any]], path: Path = INDUSTRIAL_METALS_CACHE) -> Path:
    """Write parsed sector metadata as a lightweight ignored cache CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNIVERSE_EXPORT_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in UNIVERSE_EXPORT_FIELDS})
    get_logger(__name__).info("Wrote %s London South East universe rows to %s", len(records), path)
    return path


def refresh_industrial_metals_universe(force_refresh: bool = True) -> list[dict[str, Any]]:
    """Refresh the local cached Industrial Metals sector universe."""
    html = fetch_industrial_metals_html(force_refresh=force_refresh)
    records = parse_industrial_metals_constituents(html)
    if not records:
        raise ValueError("London South East Industrial Metals parse returned no constituents")
    write_universe_csv(records)
    return records


def main() -> None:
    records = refresh_industrial_metals_universe(force_refresh=True)
    print(f"Wrote {len(records)} Industrial Metals constituents to {INDUSTRIAL_METALS_CACHE}")


if __name__ == "__main__":
    main()
