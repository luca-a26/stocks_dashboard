from __future__ import annotations

import csv
import html
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from data.market_snapshot import normalize_lse_ticker
from data.utils import CONFIG_DIR, PROJECT_ROOT, ensure_storage_path, get_logger

RNS_TECHNICAL_EVIDENCE_PATH = CONFIG_DIR / "rns_technical_evidence.csv"
RNS_TECHNICAL_EVIDENCE_SNAPSHOT_PATH = PROJECT_ROOT / "data" / "rns_technical_evidence.csv"
RNS_CACHE_DIR = ensure_storage_path("storage/cache/rns")
RNS_CACHE_TTL = timedelta(hours=float(os.getenv("RNS_CACHE_TTL_HOURS", "24")))
RNS_REQUEST_TIMEOUT = 20
RNS_PARSER_VERSION = "rns-technical-v2"
LSE_WEBSITE_BASE = "https://www.londonstockexchange.com"
LONDON_SOUTH_EAST_BASE = "https://www.lse.co.uk"

TECHNICAL_EVIDENCE_FIELDS = [
    "mineralogy",
    "metallurgical_testwork",
    "recovery_pct",
    "concentrate_grade_pct",
    "resource_category",
    "study_stage",
    "treo_grade_pct",
    "resource_tonnage_mt",
    "contained_treo_tonnes",
    "contained_ndpr_tonnes",
    "ndpr_pct_of_treo",
    "impurity_profile",
    "thorium_ppm",
    "uranium_ppm",
    "capex",
    "opex",
    "processing_depth",
]

CSV_FIELDS = [
    "ticker",
    "company",
    "announcement_date",
    "announcement_title",
    "source_url",
    "technical_evidence_status",
    "technical_field_count",
    *TECHNICAL_EVIDENCE_FIELDS,
    "source_name",
    "confidence",
    "notes",
    "last_verified",
]

TECHNICAL_HEADLINE_TERMS = (
    "resource",
    "reserve",
    "mineral",
    "metallurg",
    "test work",
    "testwork",
    "recovery",
    "flowsheet",
    "pilot",
    "scoping",
    "pea",
    "pfs",
    "dfs",
    "feasibility",
    "capex",
    "opex",
    "separation",
    "oxide",
    "impurity",
    "thorium",
    "uranium",
    "radio",
    "ndpr",
    "dytb",
    "treo",
)

TECHNICAL_SOURCE_TERMS = (
    *TECHNICAL_HEADLINE_TERMS,
    "assay",
    "drill",
    "drilling",
    "jorc",
    "ni 43-101",
    "mre",
    "mineral resource estimate",
    "resource estimate",
    "ore reserve",
    "project update",
    "operations update",
    "production update",
    "pilot plant",
    "plant",
    "economic assessment",
    "investor presentation",
    "presentation",
    "technical report",
    "annual report",
    "interim results",
    "preliminary results",
    "final results",
    "exploration update",
    "development update",
    "study",
    "bulk sample",
    "sampling",
    "grade",
    "tonnage",
    "concentrate",
    "deposit",
    "mine",
    "mining",
    "ore",
)

NON_TECHNICAL_RNS_TERMS = (
    "director dealing",
    "pdmr",
    "holding(s)",
    "holdings",
    "total voting rights",
    "issue of equity",
    "block listing",
    "agm",
    "general meeting",
    "notice of meeting",
    "shareholding",
    "warrant exercise",
    "grant of options",
)

NON_TECHNICAL_FINANCIAL_RESERVE_TERMS = (
    "share premium reserve",
    "unrestricted equity",
    "reserve for invested",
    "reduction of the share premium reserve",
    "distribution of assets from the reserve",
)


@dataclass(frozen=True)
class RnsAnnouncement:
    ticker: str
    title: str
    url: str
    released: str | None
    text: str


def rns_technical_refresh_enabled() -> bool:
    return os.getenv("ENABLE_RNS_TECHNICAL_REFRESH", "false").strip().lower() in {"1", "true", "yes"}


def _cache_is_fresh(path: Path, ttl: timedelta = RNS_CACHE_TTL) -> bool:
    if not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified < ttl


def _safe_cache_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "strategic-metals-dashboard/0.1",
        }
    )
    return session


def _get_text(url: str, cache_path: Path, *, force_refresh: bool = False) -> str:
    if not force_refresh and _cache_is_fresh(cache_path):
        return cache_path.read_text(encoding="utf-8")

    try:
        response = _session().get(url, timeout=RNS_REQUEST_TIMEOUT)
        response.raise_for_status()
        text = response.text
    except Exception:
        if cache_path.exists():
            get_logger(__name__).warning("Using stale RNS cache for %s", url)
            return cache_path.read_text(encoding="utf-8")
        raise

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def _slugify_company(value: str, *, strip_legal_suffixes: bool = False) -> str:
    text = str(value or "").lower()
    if strip_legal_suffixes:
        text = re.sub(r"\b(plc|ltd|limited|inc|corp|corporation|company)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "company"


def _slug_candidates(company_name: str, ticker: str) -> list[str]:
    candidates = [
        _slugify_company(company_name),
        _slugify_company(company_name, strip_legal_suffixes=True),
        normalize_lse_ticker(ticker).lower(),
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "-", "n/a", "na", "none", "null", "not found"}
    return True


def _to_float(value: Any) -> float | None:
    if not _present(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    text = re.sub(r"[£$€]", "", text)
    multiplier = 1.0
    lower = text.lower()
    for suffix, factor in (
        ("billion", 1_000_000_000.0),
        ("bn", 1_000_000_000.0),
        ("million", 1_000_000.0),
        ("m", 1_000_000.0),
        ("k", 1_000.0),
    ):
        if lower.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _to_bool(value: Any) -> bool | None:
    if not _present(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "published", "complete", "completed"}:
        return True
    if text in {"false", "no", "n", "0", "unavailable", "not available"}:
        return False
    return None


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    normalised = {key.strip().lower().replace(" ", "_"): value for key, value in row.items()}
    ticker = normalize_lse_ticker(normalised.get("ticker"))
    if not ticker:
        return {}
    output: dict[str, Any] = {
        "ticker": ticker,
        "company": str(normalised.get("company") or "").strip(),
        "announcement_date": str(normalised.get("announcement_date") or "").strip(),
        "announcement_title": str(normalised.get("announcement_title") or "").strip(),
        "source_url": str(normalised.get("source_url") or "").strip(),
        "technical_evidence_status": str(normalised.get("technical_evidence_status") or "").strip(),
        "technical_field_count": _to_float(normalised.get("technical_field_count")),
        "source_name": str(normalised.get("source_name") or "RNS technical evidence").strip(),
        "confidence": str(normalised.get("confidence") or "").strip(),
        "notes": str(normalised.get("notes") or "").strip(),
        "last_verified": str(normalised.get("last_verified") or "").strip(),
    }
    for field in TECHNICAL_EVIDENCE_FIELDS:
        value = normalised.get(field)
        if field in {"metallurgical_testwork"}:
            output[field] = _to_bool(value)
        elif field.endswith("_pct") or field.endswith("_ppm") or field.endswith("_mt") or field.endswith("_tonnes"):
            output[field] = _to_float(value)
        else:
            output[field] = str(value or "").strip()
    return output


def _row_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("announcement_date") or row.get("last_verified") or "")


@lru_cache(maxsize=8)
def _load_rns_technical_evidence_rows_from_path(path: str) -> tuple[dict[str, Any], ...]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    if not resolved.exists():
        return ()

    with resolved.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [_normalise_row(row) for row in reader]
    rows = [row for row in rows if row]
    get_logger(__name__).info("Loaded %s RNS technical evidence rows from %s", len(rows), resolved)
    return tuple(rows)


def load_rns_technical_evidence_rows(path: Path | str | None = None) -> list[dict[str, Any]]:
    if path is not None:
        return list(_load_rns_technical_evidence_rows_from_path(str(path)))
    rows = [
        *_load_rns_technical_evidence_rows_from_path(str(RNS_TECHNICAL_EVIDENCE_SNAPSHOT_PATH)),
        *_load_rns_technical_evidence_rows_from_path(str(RNS_TECHNICAL_EVIDENCE_PATH)),
    ]
    return rows


def _merge_evidence_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=_row_sort_key, reverse=True)
    merged: dict[str, Any] = {
        "technical_evidence_sources": [],
        "technical_data_source": "RNS technical evidence",
        "rns_parser_version": RNS_PARSER_VERSION,
    }
    notes: list[str] = []
    structured_field_count = 0
    for row in rows:
        populated_fields: list[str] = []
        for field in TECHNICAL_EVIDENCE_FIELDS:
            value = row.get(field)
            if _present(value) and merged.get(field) in (None, "", []):
                merged[field] = value
                populated_fields.append(field)
        structured_field_count += len(populated_fields)
        if row.get("notes"):
            notes.append(str(row["notes"]))
        if row.get("source_url") or row.get("announcement_title"):
            merged["technical_evidence_sources"].append(
                {
                    "date": row.get("announcement_date"),
                    "title": row.get("announcement_title"),
                    "url": row.get("source_url"),
                    "source": row.get("source_name") or "RNS",
                    "fields": populated_fields,
                    "confidence": row.get("confidence"),
                    "status": row.get("technical_evidence_status"),
                }
            )

    if merged["technical_evidence_sources"]:
        representative = next(
            (source for source in merged["technical_evidence_sources"] if source.get("fields")),
            merged["technical_evidence_sources"][0],
        )
        merged["rns_latest_date"] = representative.get("date")
        merged["rns_latest_title"] = representative.get("title")
    merged["technical_evidence_status"] = (
        "structured_fields_extracted"
        if structured_field_count > 0
        else "rns_or_document_found_needs_review"
    )
    merged["technical_field_count"] = structured_field_count
    if notes:
        merged["rns_technical_notes"] = "; ".join(dict.fromkeys(notes))
    merged["rns_evidence_count"] = len(rows)
    merged["data_fallbacks"] = [
        f"RNS technical evidence applied ({len(rows)} announcement{'s' if len(rows) != 1 else ''})"
    ]
    return {key: value for key, value in merged.items() if _present(value)}


def load_tracked_rns_technical_metrics(ticker: str, path: Path | str | None = None) -> dict[str, Any]:
    ticker_key = normalize_lse_ticker(ticker)
    if not ticker_key:
        return {}
    rows = [row for row in load_rns_technical_evidence_rows(path) if row.get("ticker") == ticker_key]
    return _merge_evidence_rows(rows) if rows else {}


def parse_lse_news_links(index_html: str, ticker: str) -> list[dict[str, str]]:
    ticker_key = normalize_lse_ticker(ticker)
    soup = BeautifulSoup(index_html or "", "html.parser")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if f"/news-article/{ticker_key.lower()}/" not in href.lower():
            continue
        url = href if href.startswith("http") else f"{LSE_WEBSITE_BASE}{href}"
        if url in seen:
            continue
        seen.add(url)
        title = " ".join(anchor.get_text(" ", strip=True).split())
        links.append({"url": url, "title": title})
    return links


def parse_lse_news_article(article_html: str, url: str, ticker: str) -> RnsAnnouncement:
    soup = BeautifulSoup(article_html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
    text = html.unescape(" ".join(soup.get_text(" ", strip=True).split()))
    date_match = re.search(r"Released\s+\d{2}:\d{2}:\d{2}\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
    released = date_match.group(1) if date_match else None
    return RnsAnnouncement(ticker=normalize_lse_ticker(ticker), title=title, url=url, released=released, text=text)


def _extract_lse_news_id(url: str) -> str | None:
    match = re.search(r"/news-article/[^/]+/[^/]+/(\d+)", str(url or ""), flags=re.IGNORECASE)
    return match.group(1) if match else None


def parse_lse_news_article_payload(payload: dict[str, Any], url: str, ticker: str) -> RnsAnnouncement | None:
    """Parse the official LSE news-article JSON payload.

    The London Stock Exchange article page is client-rendered, but the public
    page API exposes the RNS title, timestamp, company code, and HTML body. This
    parser keeps that extraction isolated so tests can cover it without network
    calls.
    """

    for component in payload.get("components") or []:
        if component.get("type") != "news-article-content":
            continue
        for item in component.get("content") or []:
            if item.get("name") != "newsarticle":
                continue
            article = item.get("value") or {}
            body_html = str(article.get("body") or "")
            soup = BeautifulSoup(body_html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = html.unescape(" ".join(soup.get_text(" ", strip=True).split()))
            return RnsAnnouncement(
                ticker=normalize_lse_ticker(article.get("companycode") or ticker),
                title=str(article.get("title") or article.get("headlinename") or "").strip(),
                url=url,
                released=str(article.get("datetime") or "").strip() or None,
                text=text,
            )
    return None


def fetch_lse_news_article_from_url(
    url: str,
    ticker: str,
    *,
    force_refresh: bool = False,
) -> RnsAnnouncement | None:
    news_id = _extract_lse_news_id(url)
    if not news_id:
        return None
    ticker_key = normalize_lse_ticker(ticker)
    cache_path = RNS_CACHE_DIR / ticker_key / f"official_article_{news_id}.json"
    if not force_refresh and _cache_is_fresh(cache_path):
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        api_url = f"https://api.londonstockexchange.com/api/v1/pages?path=news-article&parameters=newsId%253D{news_id}"
        response = _session().get(api_url, timeout=RNS_REQUEST_TIMEOUT, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return parse_lse_news_article_payload(payload, url, ticker_key)


def parse_london_south_east_rns_links(index_html: str, ticker: str) -> list[dict[str, str]]:
    ticker_key = normalize_lse_ticker(ticker)
    soup = BeautifulSoup(index_html or "", "html.parser")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = f"/rns/{ticker_key}/".lower()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if pattern not in href.lower() or not href.lower().endswith(".html"):
            continue
        url = href if href.startswith("http") else f"{LONDON_SOUTH_EAST_BASE}{href}"
        if url in seen:
            continue
        seen.add(url)
        title = " ".join(anchor.get_text(" ", strip=True).split())
        released = ""
        row = anchor.find_parent("tr")
        if row:
            cells = row.find_all("td")
            if cells:
                date_part = " ".join(cells[0].get_text(" ", strip=True).split())
                time_part = " ".join(cells[1].get_text(" ", strip=True).split()) if len(cells) > 1 else ""
                released = " ".join(part for part in (date_part, time_part) if part)
        links.append({"url": url, "title": title, "released": released})
    return links


def parse_london_south_east_rns_article(
    article_html: str,
    url: str,
    ticker: str,
    *,
    title: str = "",
    released: str | None = None,
) -> RnsAnnouncement:
    soup = BeautifulSoup(article_html or "", "html.parser")
    article_node = soup.select_one(".rns__article-content") or soup
    for tag in article_node(["script", "style", "noscript"]):
        tag.decompose()
    date_node = article_node.select_one(".rns__date")
    article_released = released or (date_node.get_text(" ", strip=True) if date_node else None)
    text = html.unescape(" ".join(article_node.get_text(" ", strip=True).split()))
    return RnsAnnouncement(
        ticker=normalize_lse_ticker(ticker),
        title=title.strip(),
        url=url,
        released=article_released,
        text=text,
    )


def fetch_london_south_east_rns_announcements(
    ticker: str,
    *,
    limit: int = 20,
    force_refresh: bool = False,
) -> list[RnsAnnouncement]:
    ticker_key = normalize_lse_ticker(ticker)
    if not ticker_key:
        return []
    index_url = f"{LONDON_SOUTH_EAST_BASE}/rns/{ticker_key}/"
    index_cache = RNS_CACHE_DIR / ticker_key / "london_south_east_index.html"
    try:
        index_html = _get_text(index_url, index_cache, force_refresh=force_refresh)
    except Exception as exc:
        get_logger(__name__).debug("London South East RNS index unavailable for %s: %s", ticker_key, exc)
        return []

    links = [
        link
        for link in parse_london_south_east_rns_links(index_html, ticker_key)
        if is_relevant_technical_source(link.get("title", ""))
    ][:limit]
    announcements: list[RnsAnnouncement] = []
    for link in links:
        article_url = link["url"]
        cache_path = RNS_CACHE_DIR / ticker_key / f"london_south_east_{_safe_cache_name(article_url)}.html"
        try:
            article_html = _get_text(article_url, cache_path, force_refresh=force_refresh)
            announcements.append(
                parse_london_south_east_rns_article(
                    article_html,
                    article_url,
                    ticker_key,
                    title=link.get("title", ""),
                    released=link.get("released") or None,
                )
            )
        except Exception as exc:
            get_logger(__name__).warning("London South East RNS article fetch/parse failed for %s: %s", article_url, exc)
    return announcements


def fetch_recent_lse_rns_announcements(
    ticker: str,
    company_name: str = "",
    *,
    limit: int = 20,
    force_refresh: bool = False,
) -> list[RnsAnnouncement]:
    ticker_key = normalize_lse_ticker(ticker)
    if not ticker_key:
        return []
    links: list[dict[str, str]] = []
    for slug in _slug_candidates(company_name or ticker_key, ticker_key):
        index_url = f"{LSE_WEBSITE_BASE}/stock/{ticker_key}/{slug}/analysis"
        index_cache = RNS_CACHE_DIR / ticker_key / f"analysis_{_safe_cache_name(slug)}.html"
        try:
            index_html = _get_text(index_url, index_cache, force_refresh=force_refresh)
        except Exception as exc:
            get_logger(__name__).debug("RNS analysis page unavailable for %s/%s: %s", ticker_key, slug, exc)
            continue
        links = parse_lse_news_links(index_html, ticker_key)
        if links:
            break
    links = links[:limit]
    announcements: list[RnsAnnouncement] = []
    for link in links:
        article_url = link["url"]
        cache_path = RNS_CACHE_DIR / ticker_key / f"{_safe_cache_name(article_url)}.html"
        try:
            official = fetch_lse_news_article_from_url(article_url, ticker_key, force_refresh=force_refresh)
            if official:
                announcements.append(official)
                continue
            article_html = _get_text(article_url, cache_path, force_refresh=force_refresh)
            announcements.append(parse_lse_news_article(article_html, article_url, ticker_key))
        except Exception as exc:
            get_logger(__name__).warning("RNS article fetch/parse failed for %s: %s", article_url, exc)
    if len(announcements) < limit:
        seen_urls = {announcement.url for announcement in announcements}
        for announcement in fetch_london_south_east_rns_announcements(
            ticker_key,
            limit=limit - len(announcements),
            force_refresh=force_refresh,
        ):
            if announcement.url not in seen_urls:
                announcements.append(announcement)
                seen_urls.add(announcement.url)
    return announcements


def is_relevant_technical_source(title: str, text: str = "") -> bool:
    searchable = f"{title} {text}".lower()
    if any(term in searchable for term in NON_TECHNICAL_FINANCIAL_RESERVE_TERMS):
        return False
    if any(term in searchable for term in TECHNICAL_SOURCE_TERMS):
        return True
    if any(term in searchable for term in NON_TECHNICAL_RNS_TERMS):
        return False
    return False


def _technical_field_count(row: dict[str, Any]) -> int:
    return sum(1 for field in TECHNICAL_EVIDENCE_FIELDS if _present(row.get(field)))


def _rns_source_name(url: str) -> str:
    return "London South East RNS mirror" if "lse.co.uk" in str(url).lower() else "London Stock Exchange RNS"


def _first_percentage_near(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = _to_float(match.group(1))
            if value is not None and 0 <= value <= 100:
                return value
    return None


def _find_numeric_near(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _to_float(match.group(1))
    return None


def _resource_category_context_found(lower_text: str, marker: str) -> bool:
    if marker == "exploration target":
        return "exploration target" in lower_text
    if marker == "reserve":
        return bool(
            re.search(
                r"\b(?:ore|mineral)\s+reserves?\b|\breserves?\b[^.]{0,80}(?:estimate|statement|category|resource)",
                lower_text,
            )
        )
    marker_pattern = re.escape(marker).replace("\\ ", r"\s+")
    return bool(
        re.search(
            rf"(?:mineral\s+resource|resource|jorc|ni\s*43-101|m&i|measured\s+and\s+indicated)[^.]{{0,100}}\b{marker_pattern}\b"
            rf"|\b{marker_pattern}\b[^.]{{0,100}}(?:mineral\s+resource|resource|jorc|ni\s*43-101)",
            lower_text,
        )
    )


def extract_technical_evidence_from_text(text: str, title: str = "") -> dict[str, Any]:
    combined = f"{title} {text}".strip()
    lower = combined.lower()
    evidence: dict[str, Any] = {}
    reason_codes: list[str] = []

    mineral_terms = [
        "monazite",
        "bastnaesite",
        "xenotime",
        "ionic clay",
        "eudialyte",
        "steenstrupine",
        "phosphogypsum",
        "apatite",
        "carbonatite",
    ]
    found_minerals = [term for term in mineral_terms if term in lower]
    if found_minerals:
        evidence["mineralogy"] = ", ".join(dict.fromkeys(found_minerals))
        reason_codes.append("RNS mineralogy evidence found")

    if any(term in lower for term in ("metallurgical", "testwork", "test work", "pilot plant", "flowsheet", "leach", "solvent extraction", "cix", "sx")):
        evidence["metallurgical_testwork"] = True
        reason_codes.append("RNS metallurgical testwork found")

    recovery = _first_percentage_near(
        combined,
        (
            r"(?:recovery|recoveries|extraction|leach(?:ing)?)[^.]{0,120}?(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%[^.]{0,80}?(?:recovery|recoveries|extraction|leach(?:ing)?)",
        ),
    )
    if recovery is not None:
        evidence["recovery_pct"] = recovery
        reason_codes.append("RNS recovery percentage found")

    concentrate_grade = _first_percentage_near(
        combined,
        (
            r"(?:concentrate grade|grade of concentrate|treo concentrate|mixed rare earth concentrate)[^.]{0,120}?(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%[^.]{0,80}?(?:treo concentrate|concentrate grade|mixed rare earth concentrate)",
        ),
    )
    if concentrate_grade is not None:
        evidence["concentrate_grade_pct"] = concentrate_grade
        reason_codes.append("RNS concentrate grade found")

    treo_grade = _first_percentage_near(
        combined,
        (
            r"(?:treo grade|total rare earth oxide grade|reo grade)[^.]{0,100}?(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%[^.]{0,60}?(?:treo|total rare earth oxide|reo)",
        ),
    )
    if treo_grade is not None and concentrate_grade != treo_grade:
        evidence["treo_grade_pct"] = treo_grade
        reason_codes.append("RNS TREO grade found")

    ndpr_pct = _first_percentage_near(
        combined,
        (
            r"(?:ndpr|neodymium\s+and\s+praseodymium)[^.]{0,100}?(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%[^.]{0,60}?(?:ndpr|neodymium\s+and\s+praseodymium)",
        ),
    )
    if ndpr_pct is not None:
        evidence["ndpr_pct_of_treo"] = ndpr_pct
        reason_codes.append("RNS NdPr basket evidence found")

    resource_tonnage = _find_numeric_near(
        combined,
        (
            r"(?:resource|mineral resource)[^.]{0,100}?(\d+(?:\.\d+)?)\s*(?:mt|million tonnes)",
            r"(\d+(?:\.\d+)?)\s*(?:mt|million tonnes)[^.]{0,100}?(?:resource|mineral resource)",
        ),
    )
    if resource_tonnage is not None:
        evidence["resource_tonnage_mt"] = resource_tonnage
        reason_codes.append("RNS resource tonnage found")

    contained_treo = _find_numeric_near(
        combined,
        (
            r"(?:contained\s+treo|treo contained|contained rare earth oxide)[^.]{0,100}?(\d[\d,]*(?:\.\d+)?)\s*(?:t|tonnes)",
            r"(\d[\d,]*(?:\.\d+)?)\s*(?:t|tonnes)[^.]{0,100}?(?:contained\s+treo|treo contained)",
        ),
    )
    if contained_treo is not None:
        evidence["contained_treo_tonnes"] = contained_treo
        reason_codes.append("RNS contained TREO found")

    contained_ndpr = _find_numeric_near(
        combined,
        (
            r"(?:contained\s+ndpr|ndpr contained)[^.]{0,100}?(\d[\d,]*(?:\.\d+)?)\s*(?:t|tonnes)",
            r"(\d[\d,]*(?:\.\d+)?)\s*(?:t|tonnes)[^.]{0,100}?(?:contained\s+ndpr|ndpr contained)",
        ),
    )
    if contained_ndpr is not None:
        evidence["contained_ndpr_tonnes"] = contained_ndpr
        reason_codes.append("RNS contained NdPr found")

    category_priority = (
        ("reserve", "Reserve"),
        ("proven", "Proven"),
        ("probable", "Probable"),
        ("measured", "Measured"),
        ("indicated", "Indicated"),
        ("inferred", "Inferred"),
        ("exploration target", "Exploration target"),
    )
    for marker, label in category_priority:
        if marker in lower:
            if not _resource_category_context_found(lower, marker):
                continue
            evidence["resource_category"] = label
            reason_codes.append(f"RNS resource confidence found: {label}")
            break

    study_priority = (
        ("definitive feasibility", "DFS"),
        ("bankable feasibility", "DFS"),
        ("dfs", "DFS"),
        ("front-end engineering", "FEED"),
        ("feed", "FEED"),
        ("pre-feasibility", "PFS"),
        ("pfs", "PFS"),
        ("preliminary economic assessment", "PEA"),
        ("pea", "PEA"),
        ("scoping", "Scoping"),
        ("concept", "Concept"),
        ("pilot", "Pilot"),
    )
    for marker, label in study_priority:
        if marker in lower:
            evidence["study_stage"] = label
            reason_codes.append(f"RNS study stage found: {label}")
            break

    impurity_terms: list[str] = []
    if any(term in lower for term in ("low thorium", "low uranium", "low radionuclide", "clean impurity")):
        impurity_terms.append("clean/low radioactivity profile indicated")
    if any(term in lower for term in ("thorium", "uranium", "radionuclide", "radioactive", "radioactivity")):
        impurity_terms.append("radioactivity/radionuclide handling referenced")
    if impurity_terms:
        evidence["impurity_profile"] = "; ".join(dict.fromkeys(impurity_terms))
        reason_codes.append("RNS impurity/radioactivity evidence found")

    thorium = _find_numeric_near(combined, (r"thorium[^.]{0,80}?(\d+(?:\.\d+)?)\s*ppm",))
    uranium = _find_numeric_near(combined, (r"uranium[^.]{0,80}?(\d+(?:\.\d+)?)\s*ppm",))
    if thorium is not None:
        evidence["thorium_ppm"] = thorium
    if uranium is not None:
        evidence["uranium_ppm"] = uranium

    if any(term in lower for term in ("magnet recycling", "rare earth alloy", "alloy production", "magnet")):
        evidence["processing_depth"] = "metals/alloys/recycling"
    elif "separated oxide" in lower or "separation" in lower or "solvent extraction" in lower:
        evidence["processing_depth"] = "separated oxide / separation route"
    elif "mixed rare earth carbonate" in lower or "mrec" in lower or "carbonate" in lower:
        evidence["processing_depth"] = "mixed rare earth carbonate"
    elif "concentrate" in lower:
        evidence["processing_depth"] = "concentrate route"

    capex = _find_numeric_near(combined, (r"capex[^.]{0,80}?([£$€]?\s?\d[\d,.]*(?:\s?(?:m|million|bn|billion))?)",))
    opex = _find_numeric_near(combined, (r"opex[^.]{0,80}?([£$€]?\s?\d[\d,.]*(?:\s?(?:m|million|bn|billion))?)",))
    if capex is not None:
        evidence["capex"] = capex
    if opex is not None:
        evidence["opex"] = opex

    if reason_codes:
        evidence["reason_codes"] = reason_codes
    return evidence


def build_rns_technical_metrics_from_announcements(announcements: list[RnsAnnouncement]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for announcement in announcements:
        if not is_relevant_technical_source(announcement.title, announcement.text):
            continue
        extracted = extract_technical_evidence_from_text(announcement.text, announcement.title)
        reasons = extracted.pop("reason_codes", [])
        field_count = _technical_field_count(extracted)
        rows.append(
            {
                "ticker": announcement.ticker,
                "announcement_date": announcement.released or "",
                "announcement_title": announcement.title,
                "source_url": announcement.url,
                "technical_evidence_status": (
                    "structured_fields_extracted" if field_count else "rns_or_document_found_needs_review"
                ),
                "technical_field_count": field_count,
                "source_name": _rns_source_name(announcement.url),
                "confidence": "Medium",
                "notes": "; ".join(reasons)
                if reasons
                else "Technical/project RNS found; structured fields require analyst review",
                **extracted,
            }
        )
    return _merge_evidence_rows(rows) if rows else {}


def build_rns_technical_metrics(
    ticker: str,
    company_name: str = "",
    *,
    force_refresh: bool = False,
    use_live: bool | None = None,
) -> dict[str, Any]:
    ticker_key = normalize_lse_ticker(ticker)
    if not ticker_key:
        return {}

    tracked = load_tracked_rns_technical_metrics(ticker_key)
    use_live = rns_technical_refresh_enabled() if use_live is None else use_live
    if not use_live:
        return tracked

    try:
        announcements = fetch_recent_lse_rns_announcements(
            ticker_key,
            company_name,
            force_refresh=force_refresh,
        )
        live_metrics = build_rns_technical_metrics_from_announcements(announcements)
    except Exception as exc:
        get_logger(__name__).warning("RNS technical refresh unavailable for %s: %s", ticker_key, exc)
        return tracked

    if not live_metrics:
        return tracked
    if not tracked:
        return live_metrics
    merged = dict(tracked)
    for field in TECHNICAL_EVIDENCE_FIELDS:
        if _present(live_metrics.get(field)):
            merged[field] = live_metrics[field]
    merged["technical_evidence_sources"] = [
        *(live_metrics.get("technical_evidence_sources") or []),
        *(tracked.get("technical_evidence_sources") or []),
    ]
    merged["rns_latest_date"] = live_metrics.get("rns_latest_date") or tracked.get("rns_latest_date")
    merged["rns_latest_title"] = live_metrics.get("rns_latest_title") or tracked.get("rns_latest_title")
    merged["rns_evidence_count"] = len(merged.get("technical_evidence_sources") or [])
    merged["data_fallbacks"] = [
        f"RNS technical evidence applied ({merged['rns_evidence_count']} announcement{'s' if merged['rns_evidence_count'] != 1 else ''})"
    ]
    return merged


def write_rns_technical_evidence_csv(rows: list[dict[str, Any]], path: Path | str) -> None:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def write_rns_technical_evidence_json(payload: dict[str, Any], path: Path | str) -> None:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
