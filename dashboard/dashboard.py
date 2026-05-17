from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from analysis.composite import load_default_ranked_stocks, load_detailed_stock
from analysis.relative_comparison import (
    CRITERIA,
    MAX_COMPARISON_COMPANIES,
    SCORING_KEY,
    build_relative_comparison,
)
from dashboard.components import data_table, scroll_table, scroll_table_children
from dashboard.discovery_view_model import (
    CATALYST_COLUMNS,
    PROJECT_COLUMNS,
    SUPPLY_CHAIN_COLUMNS,
    build_catalyst_rows,
    build_project_rows,
    build_supply_chain_rows,
)
from dashboard.view_model import TABLE_COLUMNS, build_dashboard_rows, hydrate_dashboard_records_from_snapshot
from data.discovery import (
    count_by,
    load_catalysts,
    load_project_pipeline,
    load_supply_chain_rankings,
)
from data.market_snapshot import get_market_snapshot_for_ticker, load_market_snapshot, normalize_lse_ticker
from data.utils import get_logger
from data.yahoo import fetch_yahoo_price_history, yahoo_london_symbol

ASSET_DIR = Path(__file__).resolve().parent / "assets"
COMPARISON_PAGE_SIZE = 25
FINANCIAL_REFRESH_LIMIT = int(os.getenv("FINANCIAL_REFRESH_LIMIT", "100"))
OVERVIEW_TAB = "overview"
COMPARE_TAB = "compare"
COMPARISON_NUMERIC_COLUMNS = [
    "Score",
    "Full Score",
    "Prelim Score",
    "Tech Score",
    "Commercial Score",
    "Strategic Score",
    "Benchmark Score",
    "Confidence",
    "Data Coverage",
    "Market Cap",
    "Last Price",
    "Revenue LFY",
    "Debt Metric",
    "Shares Outstanding",
    "Volume",
]
COMPARISON_WIDE_COLUMNS = [
    "Company",
    "Alias",
    "Peer Group",
    "Commodity",
    "Role",
    "Stage Gates",
    "Missing Data",
    "Drivers",
    "Positive Drivers",
    "Negative Drivers",
    "Data Notes",
    "Source",
]
SEARCH_FIELDS = [
    "Ticker",
    "Company",
    "Alias",
    "Exchange",
    "Country",
    "Commodity",
    "Role",
    "Segment",
    "Score Status",
    "Rating",
    "Data Coverage",
    "Source",
]


def load_dashboard_frame() -> tuple[pd.DataFrame, str | None, str]:
    try:
        stocks, source = load_default_ranked_stocks(limit=None)
        rows = build_dashboard_rows(stocks)
        return pd.DataFrame(rows, columns=TABLE_COLUMNS), None, source
    except Exception as exc:
        get_logger(__name__).exception("Dashboard data load failed")
        return pd.DataFrame(columns=TABLE_COLUMNS), str(exc), "load failed"


def load_dashboard_data() -> tuple[pd.DataFrame, str | None, str, dict[str, dict[str, Any]]]:
    try:
        stocks, source = load_default_ranked_stocks(limit=None)
        rows = build_dashboard_rows(stocks)
        df = pd.DataFrame(rows, columns=TABLE_COLUMNS)
        return df, None, source, _build_comparison_payload(rows, stocks)
    except Exception as exc:
        get_logger(__name__).exception("Dashboard data load failed")
        return pd.DataFrame(columns=TABLE_COLUMNS), str(exc), "load failed", {}


def _metric_card(label: str, value: str, detail: str, accent: str) -> html.Div:
    return html.Div(
        [html.Span(label), html.Strong(value), html.Small(detail)],
        className=f"metric-card accent-{accent}",
    )


def _metric_cards(df: pd.DataFrame) -> list[html.Div]:
    if df.empty:
        return [
            _metric_card("Coverage", "0", "ranked companies", "teal"),
            _metric_card("Average Score", "n/a", "mixed score model", "gold"),
            _metric_card("Leader", "n/a", "highest score", "blue"),
            _metric_card("Review Queue", "0", "scores below 3", "red"),
        ]

    raw_scores = df["Score"] if "Score" in df else pd.Series([0] * len(df), index=df.index)
    scores = pd.to_numeric(raw_scores, errors="coerce").fillna(0)
    avg_score = scores.mean()
    scored_df = df.assign(_safe_score=scores)
    leader = scored_df.sort_values("_safe_score", ascending=False).iloc[0]
    review_count = int((scores < 3).sum())

    return [
        _metric_card("Coverage", str(len(df)), "ranked companies", "teal"),
        _metric_card("Average Score", f"{avg_score:.1f}", "mixed score model", "gold"),
        _metric_card("Leader", leader["Ticker"], str(leader["Company"]), "blue"),
        _metric_card("Review Queue", str(review_count), "scores below 3", "red"),
    ]


def _discovery_metric_cards(projects: list[dict[str, Any]], catalysts: list[dict[str, Any]]) -> list[html.Div]:
    early_stage = sum(1 for item in projects if str(item.get("drill_results_status", "")).lower() in {"monitor", "pending", "no drill results"})
    historic = sum(1 for item in projects if str(item.get("historic_mine_flag", "")).lower() == "yes")
    high_impact = sum(1 for item in catalysts if str(item.get("impact", "")).lower() == "high")

    return [
        _metric_card("Pipeline", str(len(projects)), "tracked projects", "teal"),
        _metric_card("Early Stage", str(early_stage), "pre/result-watch candidates", "gold"),
        _metric_card("Historic Districts", str(historic), "legacy mine flags", "blue"),
        _metric_card("High Impact", str(high_impact), "open catalyst items", "red"),
    ]


def _leaderboard(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No watchlist data available.", className="empty-state")

    items = []
    raw_scores = df["Score"] if "Score" in df else pd.Series([0] * len(df), index=df.index)
    scores = pd.to_numeric(raw_scores, errors="coerce").fillna(0)
    scored_df = df.assign(_safe_score=scores)
    for _, row in scored_df.sort_values("_safe_score", ascending=False).head(5).iterrows():
        items.append(
            html.Div(
                [
                    html.Div([html.Strong(row["Ticker"]), html.Span(row["Company"])]),
                    html.Div(f"{row['_safe_score']:.1f}", className="score-pill"),
                ],
                className="ranked-item",
            )
        )
    return html.Div(items, className="ranked-list")


def _filter_comparison_records(
    records: list[dict[str, Any]],
    query: str | None,
) -> list[dict[str, Any]]:
    records = [record for record in records or [] if isinstance(record, dict)]
    query = _safe_text(query).strip().lower()[:160]
    if not query:
        return records

    tokens = [token for token in query.split() if token][:8]
    filtered: list[dict[str, Any]] = []
    for record in records:
        searchable = " ".join(_safe_text(record.get(field, "")).lower() for field in SEARCH_FIELDS)
        if all(token in searchable for token in tokens):
            filtered.append(record)
    return filtered


def _search_count_label(filtered_count: int, total_count: int, query: str | None) -> str:
    if not query:
        return f"Showing all {total_count} companies"
    return f"Showing {filtered_count} of {total_count} companies"


def _as_score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_safe_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_safe_text(item) for item in value)
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(_safe_text(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, set, dict)) and not value:
            continue
        return value
    return None


def _build_comparison_payload(
    records: list[dict[str, Any]],
    stocks: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    raw_by_ticker = {
        normalize_lse_ticker(stock.get("ticker")): stock
        for stock in (stocks or [])
        if normalize_lse_ticker(stock.get("ticker"))
    }
    market_snapshot = load_market_snapshot()
    payload: dict[str, dict[str, Any]] = {}
    for record in records:
        ticker = normalize_lse_ticker(record.get("Ticker"))
        if not ticker:
            continue
        raw = raw_by_ticker.get(ticker, {})
        metrics = raw.get("fundamental", {}).get("metrics", {}) if isinstance(raw, dict) else {}
        provenance = metrics.get("field_provenance", {}) if isinstance(metrics, dict) else {}
        market_cap_provenance = provenance.get("market_cap", {}) if isinstance(provenance, dict) else {}
        snapshot = get_market_snapshot_for_ticker(ticker, market_snapshot) or {}
        share_price_url = _first_non_empty(
            metrics.get("share_price_url") if isinstance(metrics, dict) else None,
            snapshot.get("share_price_url"),
            snapshot.get("source_url"),
        )
        source_url = _first_non_empty(
            market_cap_provenance.get("source_url") if isinstance(market_cap_provenance, dict) else None,
            metrics.get("source_url") if isinstance(metrics, dict) else None,
            share_price_url,
            snapshot.get("source_url"),
        )
        payload[ticker] = {
            "ticker": ticker,
            "company_name": record.get("Company") or raw.get("name") or ticker,
            "alias": record.get("Alias") or raw.get("former_name") or "",
            "exchange": record.get("Exchange") or raw.get("exchange"),
            "country": record.get("Country") or raw.get("country"),
            "commodity_tags": record.get("Commodity") or raw.get("commodity_tags"),
            "supply_chain_role": record.get("Role") or raw.get("supply_chain_role"),
            "segment": record.get("Segment"),
            "composite_score": _as_score(record.get("Score") or raw.get("composite_score")),
            "technical_asset_score": _as_score(record.get("Tech Score") or raw.get("technical_asset_score")),
            "commercial_financial_score": _as_score(record.get("Commercial Score") or raw.get("commercial_financial_score")),
            "strategic_supply_chain_score": _as_score(record.get("Strategic Score") or raw.get("strategic_supply_chain_score")),
            "benchmark_score": _as_score(record.get("Benchmark Score") or raw.get("benchmark_score")),
            "scoring_confidence": _as_score(record.get("Confidence") or raw.get("scoring_confidence")),
            "confidence_level": record.get("Confidence Level") or raw.get("confidence_level"),
            "data_coverage_display": record.get("Data Coverage"),
            "score_status": record.get("Score Status") or raw.get("score_status"),
            "rating_label": record.get("Rating") or raw.get("rating_label"),
            "peer_group": record.get("Peer Group") or raw.get("suggested_peer_group"),
            "market_cap_display": record.get("Market Cap"),
            "last_price_display": record.get("Last Price"),
            "revenue_display": record.get("Revenue LFY"),
            "debt_metric_display": record.get("Debt Metric"),
            "shares_display": record.get("Shares Outstanding"),
            "volume_display": record.get("Volume"),
            "range_display": record.get("52W Range"),
            "missing_data_fields": record.get("Missing Data") or raw.get("missing_data_fields"),
            "stage_gates": record.get("Stage Gates") or raw.get("applied_stage_gates"),
            "drivers": record.get("Drivers") or raw.get("reason_codes"),
            "positive_drivers": record.get("Positive Drivers") or raw.get("top_positive_drivers"),
            "negative_drivers": record.get("Negative Drivers") or raw.get("top_negative_drivers"),
            "data_notes": record.get("Data Notes"),
            "source": record.get("Source") or raw.get("source"),
            "retrieved_utc": record.get("Retrieved UTC"),
            "source_url": source_url,
            "share_price_url": share_price_url,
            "lse_website_urls": metrics.get("lse_website_urls") if isinstance(metrics, dict) else [],
            "company_website": _first_non_empty(
                metrics.get("company_website") if isinstance(metrics, dict) else None,
                metrics.get("website") if isinstance(metrics, dict) else None,
                raw.get("company_website"),
                raw.get("website"),
            ),
            "yahoo_symbol": _first_non_empty(
                metrics.get("yahoo_symbol") if isinstance(metrics, dict) else None,
                raw.get("yahoo_symbol"),
                yahoo_london_symbol(ticker),
            ),
            "score_breakdown": raw.get("score_breakdown") or {},
        }
    return payload


def _normalise_comparison_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}

    normalised_payload: dict[str, dict[str, Any]] = {}
    for key, record in payload.items():
        if not isinstance(record, dict):
            continue
        ticker = normalize_lse_ticker(record.get("ticker") or record.get("Ticker") or key)
        if not ticker:
            continue
        next_record = dict(record)
        next_record["ticker"] = ticker
        next_record["company_name"] = _safe_text(
            next_record.get("company_name")
            or next_record.get("Company")
            or next_record.get("name")
            or ticker
        ) or ticker
        normalised_payload[ticker] = next_record
    return normalised_payload


def _normalise_selection(selection: Any) -> list[str]:
    normalised: list[str] = []
    if isinstance(selection, str):
        raw_selection = [selection]
    elif isinstance(selection, (list, tuple, set)):
        raw_selection = list(selection)
    else:
        raw_selection = []

    for ticker in raw_selection:
        value = normalize_lse_ticker(ticker)
        if value and value not in normalised:
            normalised.append(value)
        if len(normalised) == MAX_COMPARISON_COMPANIES:
            break
    return normalised


def _trigger_has_click(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_trigger_has_click(item) for item in value)
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return bool(value)


def _add_comparison_ticker(selection: list[str] | None, ticker: str | None) -> list[str]:
    selected = _normalise_selection(selection)
    value = normalize_lse_ticker(ticker)
    if value and value not in selected and len(selected) < MAX_COMPARISON_COMPANIES:
        selected.append(value)
    return selected


def _remove_comparison_ticker(selection: list[str] | None, ticker: str | None) -> list[str]:
    value = normalize_lse_ticker(ticker)
    return [ticker for ticker in _normalise_selection(selection) if ticker != value]


def _status_children(error: str | None = None, source: str | None = None) -> list[html.Span]:
    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "Data warning" if error else "Universe ready"
    class_name = "status-pill" if error else "status-pill status-live"
    return [
        html.Span(status, className=class_name),
        html.Span(f"Comparison: {source or 'metadata'}", className="status-pill"),
        html.Span(f"Refreshed {refreshed}", className="status-pill"),
    ]


def _panel(kicker: str, title: str, children: Any, class_name: str = "") -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.P(kicker, className="section-kicker"), html.H2(title)]),
                ],
                className="panel-heading",
            ),
            children,
        ],
        className=f"panel {class_name}".strip(),
    )


def _score_bar(score: int, *, source: str = "automatic") -> html.Div:
    score = max(1, min(5, int(score)))
    return html.Div(
        [
            html.Div(
                html.Span(style={"width": f"{score * 20}%"}),
                className=f"relative-score-bar relative-score-{score} relative-score-source-{source}",
            ),
            html.Strong(str(score)),
        ],
        className="relative-score-cell",
    )


def _company_card(company: dict[str, Any]) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Strong(company["ticker"]),
                            html.Span(company["company_name"]),
                        ],
                        className="comparison-card-title",
                    ),
                    html.Div(f"{company.get('composite_score') or 'n/a'}", className="comparison-card-score"),
                ],
                className="comparison-card-header",
            ),
            html.Div(
                [
                    html.Span(f"Rating: {company.get('rating_label') or 'Not assessed'}"),
                    html.Span(f"Market cap: {company.get('market_cap') or 'Not found'}"),
                    html.Span(f"Tech: {company.get('technical_asset_score') or 'n/a'}"),
                    html.Span(f"Commercial: {company.get('commercial_financial_score') or 'n/a'}"),
                    html.Span(f"Strategic: {company.get('strategic_supply_chain_score') or 'n/a'}"),
                ],
                className="comparison-card-metrics",
            ),
            html.Div(
                [
                    html.P("Positive drivers", className="comparison-card-kicker"),
                    html.P(str(company.get("positive_drivers") or "None"), title=str(company.get("positive_drivers") or "")),
                    html.P("Missing / negative evidence", className="comparison-card-kicker"),
                    html.P(str(company.get("negative_drivers") or company.get("missing_data_fields") or "None"), title=str(company.get("negative_drivers") or "")),
                ],
                className="comparison-card-notes",
            ),
        ],
        className="comparison-company-card",
    )


def _relative_score_table(comparison: dict[str, Any]) -> html.Div:
    companies = comparison.get("companies", [])
    if not companies:
        return html.Div("Click a company row to start a relative comparison.", className="empty-state")

    headers = [
        "Company",
        *[criterion.short_label for criterion in CRITERIA.values()],
        "Total / 25",
        "Rank",
    ]
    rows = []
    for company in companies:
        rows.append(
            html.Tr(
                [
                    html.Td(
                        [
                            html.Strong(company["company_name"]),
                            html.Span(f"LSE:{company['ticker']}"),
                        ],
                        className="relative-company-cell",
                    ),
                    *[
                        html.Td(
                            _score_bar(
                                company["criteria"][criterion_key]["score"],
                                source=company["criteria"][criterion_key]["source"],
                            ),
                            title="; ".join(company["criteria"][criterion_key].get("notes") or []),
                        )
                        for criterion_key in CRITERIA
                    ],
                    html.Td(f"{company['total_score']} / {company['max_score']}", className="relative-total-cell"),
                    html.Td(str(company.get("rank", "-")), className="relative-rank-cell"),
                ]
            )
        )
    return html.Div(
        html.Table(
            [
                html.Thead(html.Tr([html.Th(header) for header in headers])),
                html.Tbody(rows),
            ],
            className="relative-score-table",
        ),
        className="relative-score-table-wrap",
    )


def _comparison_candidates(
    payload: dict[str, dict[str, Any]],
    selection: list[str] | None,
    query: str | None,
) -> list[dict[str, Any]]:
    payload = _normalise_comparison_payload(payload)
    selected = set(_normalise_selection(selection))
    query_text = _safe_text(query).strip().lower()[:160]
    tokens = [token for token in query_text.split() if token][:8]
    candidates: list[dict[str, Any]] = []
    for ticker, record in payload.items():
        if ticker in selected:
            continue
        searchable = " ".join(
            _safe_text(record.get(field, ""))
            for field in (
                "ticker",
                "company_name",
                "exchange",
                "country",
                "commodity_tags",
                "supply_chain_role",
                "peer_group",
                "rating_label",
            )
        ).lower()
        if tokens and not all(token in searchable for token in tokens):
            continue
        candidates.append(record)
    candidates.sort(key=lambda item: _safe_float(item.get("composite_score")), reverse=True)
    return candidates[:8]


def _comparison_side_panel(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]],
    query: str | None,
) -> list[Any]:
    payload = _normalise_comparison_payload(payload)
    selection = [ticker for ticker in _normalise_selection(selection) if ticker in payload]
    selected_items = [
        payload[ticker]
        for ticker in selection
        if ticker in payload
    ]
    selected_list = [
        html.Div(
            [
                html.Div(
                    [
                        html.Strong(item.get("ticker") or ""),
                        html.Span(item.get("company_name") or item.get("ticker") or "Unknown company"),
                    ]
                ),
                html.Button(
                    "Remove",
                    id={"type": "compare-remove", "ticker": item.get("ticker") or ""},
                    n_clicks=0,
                    className="comparison-link-button",
                ),
            ],
            className="comparison-peer-row",
        )
        for item in selected_items
    ]

    if len(selection) >= MAX_COMPARISON_COMPANIES:
        candidates = [html.Div("Comparison group is full.", className="comparison-muted")]
    else:
        candidates = [
            html.Button(
                [
                    html.Strong(candidate.get("ticker") or ""),
                    html.Span(candidate.get("company_name") or candidate.get("ticker") or "Unknown company"),
                ],
                id={"type": "compare-add", "ticker": candidate.get("ticker") or ""},
                n_clicks=0,
                className="comparison-candidate-button",
                title=f"Add {candidate.get('company_name') or candidate.get('ticker') or 'company'} to comparison",
            )
            for candidate in _comparison_candidates(payload, selection, query)
            if candidate.get("ticker")
        ]
        if not candidates:
            candidates = [html.Div("No matching companies to add.", className="comparison-muted")]

    prompt = (
        "Add more companies to compare"
        if len(selection) < 2
        else f"{len(selection)} of {MAX_COMPARISON_COMPANIES} companies selected"
    )
    return [
        html.P(prompt, className="comparison-side-prompt"),
        html.Div(selected_list or [html.Div("No peers selected.", className="comparison-muted")], className="comparison-peer-list"),
        html.Div(candidates, className="comparison-candidate-list"),
    ]


def _comparison_footer() -> list[Any]:
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.Strong(criterion.label),
                        html.P(criterion.description),
                    ],
                    className="comparison-definition",
                )
                for criterion in CRITERIA.values()
            ],
            className="comparison-definitions",
        ),
        html.Div(
            [
                html.Strong("Scoring key"),
                *[
                    html.P(f"{item['score']} - {item['label']}: {item['description']}")
                    for item in SCORING_KEY
                ],
            ],
            className="comparison-scoring-key",
        ),
    ]


def _comparison_main_panel(selection: list[str], payload: dict[str, dict[str, Any]]) -> list[Any]:
    payload = _normalise_comparison_payload(payload)
    selection = [ticker for ticker in _normalise_selection(selection) if ticker in payload]
    comparison = build_relative_comparison(selection, payload)
    companies = comparison.get("companies", [])
    if not companies:
        return [html.Div("Click a company row to open a company card.", className="empty-state")]

    intro = (
        "Relative peer scorecard unlocks once at least two companies are selected."
        if len(companies) < 2
        else comparison.get("note")
    )
    return [
        html.Div([_company_card(company) for company in companies], className="comparison-card-grid"),
        html.P(intro, className="comparison-note"),
        _relative_score_table(comparison),
    ]


def _selected_overview_company(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for ticker in _normalise_selection(selection):
        if ticker in payload:
            return payload[ticker]
    return None


def _display_value(value: Any, default: str = "Not loaded") -> str:
    text = _safe_text(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return default
    return text


def _normalise_modal_tab(value: Any) -> str:
    return COMPARE_TAB if value == COMPARE_TAB else OVERVIEW_TAB


def _overview_kpi(label: str, value: Any, detail: str = "") -> html.Div:
    return html.Div(
        [
            html.Span(label),
            html.Strong(_display_value(value)),
            html.Small(detail) if detail else None,
        ],
        className="overview-kpi-card",
    )


def _split_detail_items(value: Any, limit: int = 6) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        raw_items = [f"{key}: {_safe_text(item)}" for key, item in value.items()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [_safe_text(item) for item in value]
    else:
        raw_items = re.split(r";|\n", _safe_text(value))
    items = [item.strip() for item in raw_items if item and item.strip()]
    return items[:limit]


def _overview_list(title: str, value: Any, *, empty: str = "None recorded") -> html.Div:
    items = _split_detail_items(value)
    return html.Div(
        [
            html.H4(title),
            html.Ul([html.Li(item, title=item) for item in items])
            if items
            else html.P(empty, className="comparison-muted"),
        ],
        className="overview-detail-card",
    )


def _normalise_url(url: Any) -> str:
    text = _safe_text(url).strip()
    if text.lower().startswith(("http://", "https://")):
        return text
    return ""


def _resource_links(company: dict[str, Any]) -> list[dict[str, str]]:
    ticker = normalize_lse_ticker(company.get("ticker"))
    yahoo_symbol = _display_value(company.get("yahoo_symbol") or yahoo_london_symbol(ticker), yahoo_london_symbol(ticker))
    lse_url = f"https://www.londonstockexchange.com/stock/{quote(ticker)}/"
    london_south_east_url = (
        _normalise_url(company.get("share_price_url"))
        or f"https://www.lse.co.uk/SharePrice.html?shareprice={quote(ticker)}"
    )
    links = [
        {"label": "London Stock Exchange", "href": lse_url},
        {"label": "London South East", "href": london_south_east_url},
        {"label": "Yahoo Finance", "href": f"https://finance.yahoo.com/quote/{quote(yahoo_symbol)}"},
    ]

    website = _normalise_url(company.get("company_website"))
    if website:
        links.append({"label": "Company Website", "href": website})

    website_urls = company.get("lse_website_urls") or []
    if isinstance(website_urls, str):
        website_urls = [website_urls]
    for index, url in enumerate(website_urls[:2], start=1):
        normalised = _normalise_url(url)
        if normalised:
            links.append({"label": f"LSE Detail {index}", "href": normalised})

    source_url = _normalise_url(company.get("source_url"))
    if source_url:
        links.append({"label": "Primary Source", "href": source_url})

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        href = link["href"]
        if href and href not in seen:
            seen.add(href)
            deduped.append(link)
    return deduped


def _resource_link_buttons(company: dict[str, Any]) -> html.Div:
    links = _resource_links(company)
    return html.Div(
        [
            html.H3("Resources"),
            html.Div(
                [
                    html.A(
                        link["label"],
                        href=link["href"],
                        target="_blank",
                        rel="noopener noreferrer",
                        className="overview-resource-link",
                    )
                    for link in links
                ],
                className="overview-resource-list",
            ),
        ],
        className="overview-resource-panel",
    )


def _number_from_display(value: Any) -> float | None:
    text = _safe_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _range_from_display(value: Any) -> tuple[float | None, float | None]:
    numbers = re.findall(r"-?\d+(?:\.\d+)?", _safe_text(value).replace(",", ""))
    if len(numbers) < 2:
        return None, None
    try:
        low = float(numbers[0])
        high = float(numbers[1])
    except ValueError:
        return None, None
    return low, high


def _apply_chart_layout(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=title,
        height=310,
        margin={"l": 42, "r": 18, "t": 52, "b": 42},
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#17211f"},
        xaxis={"gridcolor": "#eee7da", "zeroline": False},
        yaxis={"gridcolor": "#eee7da", "zeroline": False},
        showlegend=False,
    )
    return figure


def _share_chart_figure(company: dict[str, Any], chart_payload: dict[str, Any] | None = None) -> go.Figure:
    ticker = normalize_lse_ticker(company.get("ticker"))
    chart_payload = chart_payload if isinstance(chart_payload, dict) else {}
    points = chart_payload.get("points") or []
    if chart_payload.get("ticker") == ticker and points:
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=[point.get("date") for point in points],
                    y=[point.get("close") for point in points],
                    mode="lines",
                    line={"color": "#1b8a74", "width": 2.2},
                    hovertemplate="%{x}<br>%{y:g}<extra></extra>",
                )
            ]
        )
        return _apply_chart_layout(figure, "Yahoo 1Y Share Chart")

    low, high = _range_from_display(company.get("range_display"))
    last = _number_from_display(company.get("last_price_display"))
    if low is not None and high is not None and last is not None:
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=[low, high],
                    y=["52-week range", "52-week range"],
                    mode="lines",
                    line={"color": "#d3c9b9", "width": 9},
                    hoverinfo="skip",
                ),
                go.Scatter(
                    x=[last],
                    y=["52-week range"],
                    mode="markers+text",
                    marker={"color": "#1b8a74", "size": 13},
                    text=["Last"],
                    textposition="top center",
                    hovertemplate="Last price: %{x:g}<extra></extra>",
                ),
            ]
        )
        return _apply_chart_layout(figure, "Share Price Context")

    if last is not None:
        figure = go.Figure(
            data=[
                go.Bar(
                    x=["Last price"],
                    y=[last],
                    marker_color="#1b8a74",
                    hovertemplate="%{y:g}<extra></extra>",
                )
            ]
        )
        return _apply_chart_layout(figure, "Share Price Snapshot")

    figure = go.Figure()
    figure.add_annotation(
        text="Chart data not available",
        x=0.5,
        y=0.5,
        showarrow=False,
        xref="paper",
        yref="paper",
        font={"size": 14, "color": "#66706c"},
    )
    return _apply_chart_layout(figure, "Share Chart")


def _company_overview_main(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]],
    chart_payload: dict[str, Any] | None = None,
) -> list[Any]:
    company = _selected_overview_company(selection, payload)
    if not company:
        return [html.Div("Click a company row to open a company overview.", className="empty-state")]

    score = company.get("composite_score")
    header_meta = [
        _display_value(company.get("exchange"), "Exchange not loaded"),
        _display_value(company.get("peer_group"), "Peer group not classified"),
        _display_value(company.get("data_coverage_display"), "Coverage not assessed"),
    ]
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.P("Company Overview", className="section-kicker"),
                        html.H3(company.get("company_name") or company.get("ticker") or "Unknown company"),
                        html.P(" | ".join(header_meta), className="overview-company-meta"),
                    ],
                    className="overview-company-title",
                ),
                html.Div(
                    [
                        html.Span(f"LSE:{company.get('ticker')}", className="overview-pill"),
                        html.Span(_display_value(company.get("rating_label"), "Not assessed"), className="overview-pill"),
                        html.Span(f"Status: {_display_value(company.get('score_status'), 'Not loaded')}", className="overview-pill"),
                    ],
                    className="overview-status-pills",
                ),
            ],
            className="company-overview-hero",
        ),
        html.Div(
            [
                _overview_kpi("Composite Score", f"{score:.2f}" if isinstance(score, (int, float)) else score, "0-10 hybrid score"),
                _overview_kpi("Technical", company.get("technical_asset_score"), "asset quality"),
                _overview_kpi("Commercial", company.get("commercial_financial_score"), "financial route"),
                _overview_kpi("Strategic", company.get("strategic_supply_chain_score"), "supply-chain value"),
                _overview_kpi("Benchmark", company.get("benchmark_score"), "peer benchmark"),
                _overview_kpi("Confidence", company.get("scoring_confidence"), company.get("confidence_level") or "coverage signal"),
                _overview_kpi("Market Cap", company.get("market_cap_display"), "display source retained"),
                _overview_kpi("Last Price", company.get("last_price_display"), "latest cached/fallback"),
                _overview_kpi("Revenue Status", company.get("revenue_display"), "LFY or status"),
                _overview_kpi("Debt Metric", company.get("debt_metric_display"), "balance-sheet signal"),
                _overview_kpi("Shares", company.get("shares_display"), "shares outstanding"),
                _overview_kpi("Volume", company.get("volume_display"), "latest volume"),
                _overview_kpi("52W Range", company.get("range_display"), "low to high"),
            ],
            className="overview-kpi-grid",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.H3("Share Chart"),
                        dcc.Graph(
                            figure=_share_chart_figure(company, chart_payload),
                            config={"displayModeBar": False, "responsive": True},
                            className="overview-chart",
                        ),
                    ],
                    className="overview-chart-panel",
                ),
                html.Div(
                    [
                        _overview_list("Positive Drivers", company.get("positive_drivers") or company.get("drivers")),
                        _overview_list("Negative Drivers / Missing Data", company.get("negative_drivers") or company.get("missing_data_fields")),
                        _overview_list("Stage Gates", company.get("stage_gates")),
                        _overview_list("Data Notes", company.get("data_notes"), empty="No fallback notes recorded"),
                    ],
                    className="overview-detail-grid",
                ),
            ],
            className="company-overview-grid",
        ),
    ]


def _company_overview_side_panel(company: dict[str, Any] | None) -> list[Any]:
    if not company:
        return [html.Div("No company selected.", className="comparison-muted")]
    source_detail = _display_value(company.get("source"), "Source not loaded")
    return [
        _resource_link_buttons(company),
        html.Div(
            [
                html.H3("Source / Provenance"),
                html.P(source_detail, title=source_detail),
                html.P(f"Retrieved: {_display_value(company.get('retrieved_utc'), 'Not loaded')}"),
                html.P(f"Country: {_display_value(company.get('country'), 'Unknown')}"),
                html.P(f"Role: {_display_value(company.get('supply_chain_role'), 'Unclassified')}"),
                html.P(f"Commodity: {_display_value(company.get('commodity_tags'), 'Unclassified')}"),
            ],
            className="overview-source-card",
        ),
        html.Div(
            "Open the Compare To Others tab to add up to three more peers to the 1-5 relative scorecard.",
            className="comparison-muted",
        ),
    ]


def _count_chart(title: str, rows: list[dict[str, Any]], color: str = "#1b8a74") -> go.Figure:
    labels = [row["label"] for row in rows]
    values = [row["count"] for row in rows]
    figure = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker_color=color,
                hovertemplate="%{x}: %{y}<extra></extra>",
            )
        ]
    )
    figure.update_layout(
        title=title,
        margin={"l": 28, "r": 18, "t": 48, "b": 48},
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#17211f"},
        xaxis={"title": None},
        yaxis={"title": None, "tickformat": ",d", "gridcolor": "#e5e1d8"},
        showlegend=False,
    )
    return figure


def _donut_chart(title: str, rows: list[dict[str, Any]]) -> go.Figure:
    figure = go.Figure(
        data=[
            go.Pie(
                labels=[row["label"] for row in rows],
                values=[row["count"] for row in rows],
                hole=0.55,
                marker={"colors": ["#1b8a74", "#c48a24", "#356b8c", "#b34a3b", "#66706c"]},
                hovertemplate="%{label}: %{value}<extra></extra>",
            )
        ]
    )
    figure.update_layout(
        title=title,
        margin={"l": 18, "r": 18, "t": 48, "b": 18},
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#17211f"},
        showlegend=True,
        legend={"orientation": "h", "y": -0.08},
    )
    return figure


def _top_search_bar() -> html.Div:
    return html.Div(
        [
            html.Label("Company Search", htmlFor="universe-search-input", className="top-search-label"),
            dcc.Input(
                id="universe-search-input",
                type="search",
                debounce=0.35,
                maxLength=80,
                placeholder="Search company, ticker, exchange, commodity, country, role...",
                className="universe-search-input",
            ),
            html.Button(
                "Load financials",
                id="load-financials-button",
                n_clicks=0,
                className="compact-action-button",
            ),
            html.Div("Showing all companies", id="comparison-search-count", className="comparison-search-count"),
            dcc.Loading(
                html.Div(
                    f"Financial refresh loads up to {FINANCIAL_REFRESH_LIMIT} matching rows.",
                    id="financial-refresh-status",
                    className="financial-refresh-status",
                ),
                type="dot",
            ),
        ],
        className="top-search-bar",
    )


def _watchlist_tab(df: pd.DataFrame, error: str | None) -> html.Div:
    return html.Div(
        [
            html.Section(_metric_cards(df), className="metric-grid", id="watchlist-metrics"),
            html.Div(error, className="error-banner") if error else None,
            html.Section(
                [
                    _panel(
                        "Comparison Universe",
                        "LSE Industrial Metals Scoreboard",
                        scroll_table(
                            "stock-table",
                            TABLE_COLUMNS,
                            df.to_dict("records"),
                            max_height="72vh",
                            numeric_columns=COMPARISON_NUMERIC_COLUMNS,
                            wide_columns=COMPARISON_WIDE_COLUMNS,
                            sticky_columns_count=2,
                            row_id_field="Ticker",
                            row_id_type="comparison-row",
                        ),
                        "table-panel",
                    ),
                    html.Aside(
                        [
                            html.Div(
                                [
                                    html.P("Signal Stack", className="section-kicker"),
                                    html.H2("Top Candidates"),
                                ],
                                className="panel-heading",
                            ),
                            html.Div(_leaderboard(df), id="top-candidates-list"),
                            html.Div(
                                [
                                    html.Span("Tracking"),
                                    html.Strong("logs/dashboard.log"),
                                    html.Small("Runtime events and data-load warnings"),
                                ],
                                className="tracking-strip",
                            ),
                        ],
                        className="panel insight-panel",
                    ),
                ],
                className="content-grid",
            ),
        ],
        className="tab-body",
    )


def _projects_tab(projects: list[dict[str, Any]], catalysts: list[dict[str, Any]]) -> html.Div:
    project_rows = build_project_rows(projects)
    return html.Div(
        [
            html.Section(_discovery_metric_cards(projects, catalysts), className="metric-grid"),
            html.Section(
                [
                    _panel(
                        "Pipeline",
                        "Project Stage Mix",
                        dcc.Graph(
                            figure=_count_chart("Projects By Stage", count_by(projects, "stage"), "#1b8a74"),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                    _panel(
                        "Exposure",
                        "Commodity / REE Class",
                        dcc.Graph(
                            figure=_donut_chart("Exposure Split", count_by(projects, "ree_class")),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                ],
                className="chart-grid",
            ),
            _panel(
                "Discovery",
                "REE And Critical Minerals Project Pipeline",
                data_table(
                    "project-pipeline-table",
                    PROJECT_COLUMNS,
                    project_rows,
                    page_size=10,
                    wide_columns=["Project", "Commodity Focus", "Role", "Notes"],
                ),
                "table-panel full-width-panel",
            ),
        ],
        className="tab-body",
    )


def _supply_chain_tab(rankings: list[dict[str, Any]]) -> html.Div:
    rows = build_supply_chain_rows(rankings)
    return html.Div(
        [
            html.Section(
                [
                    _panel(
                        "Rankings",
                        "Supply Chain Segments",
                        dcc.Graph(
                            figure=_count_chart("Items By Segment", count_by(rankings, "segment"), "#356b8c"),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                    _panel(
                        "Coverage",
                        "Import / Tracking Status",
                        dcc.Graph(
                            figure=_donut_chart("Status Mix", count_by(rankings, "status")),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                ],
                className="chart-grid",
            ),
            _panel(
                "Supply Chain",
                "LREE, HREE, Processors And Magnet Makers",
                data_table(
                    "supply-chain-table",
                    SUPPLY_CHAIN_COLUMNS,
                    rows,
                    page_size=10,
                    wide_columns=["Entity", "Exposure", "Notes"],
                ),
                "table-panel full-width-panel",
            ),
        ],
        className="tab-body",
    )


def _catalysts_tab(catalysts: list[dict[str, Any]]) -> html.Div:
    rows = build_catalyst_rows(catalysts)
    return html.Div(
        [
            html.Section(
                [
                    _panel(
                        "Catalysts",
                        "Impact Mix",
                        dcc.Graph(
                            figure=_donut_chart("Catalysts By Impact", count_by(catalysts, "impact")),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                    _panel(
                        "Workflow",
                        "Catalysts By Category",
                        dcc.Graph(
                            figure=_count_chart("Catalysts By Category", count_by(catalysts, "category"), "#c48a24"),
                            config={"displayModeBar": False},
                            className="dashboard-graph",
                        ),
                        "chart-panel",
                    ),
                ],
                className="chart-grid",
            ),
            _panel(
                "Tracker",
                "Open Research And Market Catalysts",
                data_table(
                    "catalyst-table",
                    CATALYST_COLUMNS,
                    rows,
                    page_size=10,
                    wide_columns=["Catalyst", "Source", "Notes"],
                ),
                "table-panel full-width-panel",
            ),
        ],
        className="tab-body",
    )


def _dashboard_sections(df: pd.DataFrame, error: str | None) -> list:
    projects = load_project_pipeline()
    rankings = load_supply_chain_rankings()
    catalysts = load_catalysts()

    return [
        dcc.Tabs(
            id="dashboard-tabs",
            className="dashboard-tabs",
            parent_className="dashboard-tabs-wrap",
            children=[
                dcc.Tab(
                    label="LSE Watchlist",
                    value="watchlist",
                    className="dashboard-tab",
                    selected_className="dashboard-tab dashboard-tab-selected",
                    children=_watchlist_tab(df, error),
                ),
                dcc.Tab(
                    label="Project Pipeline",
                    value="projects",
                    className="dashboard-tab",
                    selected_className="dashboard-tab dashboard-tab-selected",
                    children=_projects_tab(projects, catalysts),
                ),
                dcc.Tab(
                    label="Supply Chain",
                    value="supply-chain",
                    className="dashboard-tab",
                    selected_className="dashboard-tab dashboard-tab-selected",
                    children=_supply_chain_tab(rankings),
                ),
                dcc.Tab(
                    label="Catalysts",
                    value="catalysts",
                    className="dashboard-tab",
                    selected_className="dashboard-tab dashboard-tab-selected",
                    children=_catalysts_tab(catalysts),
                ),
            ],
        )
    ]


def build_app_shell() -> html.Main:
    return html.Main(
        [
            dcc.Interval(id="load-trigger", interval=500, max_intervals=1, n_intervals=0),
            dcc.Store(id="ranked-records-store"),
            dcc.Store(id="filtered-records-store"),
            dcc.Store(id="comparison-payload-store"),
            dcc.Store(id="comparison-selection-store", data=[]),
            dcc.Store(id="comparison-chart-store", data={}),
            html.Section(
                [
                    html.Div(
                        [
                            html.P("Strategic Metals", className="eyebrow"),
                            html.H1("Portfolio Intelligence Dashboard"),
                            html.P(
                                "Searchable strategic-metals universe, lazy LSE fundamentals, supply-chain rankings and catalyst tracking.",
                                className="hero-copy",
                            ),
                        ],
                        className="hero-title",
                    ),
                    html.Div(
                        [html.Span("Ready", className="status-pill status-live")],
                        className="status-row",
                        id="status-row",
                    ),
                ],
                className="hero-band",
            ),
            _top_search_bar(),
            html.Div(
                html.Div("Loading watchlist data...", className="empty-state"),
                id="dashboard-content",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.P("Company Detail", className="section-kicker"),
                                            html.H2("Company Comparison"),
                                        ]
                                    ),
                                    html.Button("Close", id="compare-close-button", n_clicks=0, className="comparison-secondary-button"),
                                ],
                                className="comparison-modal-header",
                            ),
                            dcc.Tabs(
                                id="comparison-modal-tabs",
                                value=OVERVIEW_TAB,
                                className="comparison-detail-tabs",
                                parent_className="comparison-detail-tabs-wrap",
                                children=[
                                    dcc.Tab(
                                        label="Overview",
                                        value=OVERVIEW_TAB,
                                        className="comparison-detail-tab",
                                        selected_className="comparison-detail-tab comparison-detail-tab-selected",
                                    ),
                                    dcc.Tab(
                                        label="Compare To Others",
                                        value=COMPARE_TAB,
                                        className="comparison-detail-tab",
                                        selected_className="comparison-detail-tab comparison-detail-tab-selected",
                                    ),
                                ],
                            ),
                            html.Div(
                                [
                                    html.Div(id="comparison-main-panel", className="comparison-main-panel"),
                                    html.Aside(
                                        [
                                            html.Div(
                                                [
                                                    html.Label("Add Peer", htmlFor="compare-peer-search", className="top-search-label"),
                                                    dcc.Input(
                                                        id="compare-peer-search",
                                                        type="search",
                                                        debounce=0.35,
                                                        maxLength=80,
                                                        placeholder="Search ticker, company, commodity...",
                                                        className="universe-search-input",
                                                    ),
                                                    html.Button(
                                                        "Clear",
                                                        id="compare-clear-button",
                                                        n_clicks=0,
                                                        className="comparison-secondary-button",
                                                    ),
                                                ],
                                                id="comparison-side-tools",
                                                className="comparison-side-tools",
                                            ),
                                            html.Div(id="comparison-side-panel"),
                                        ],
                                        className="comparison-side-panel",
                                    ),
                                ],
                                className="comparison-modal-grid",
                            ),
                            html.Div(id="comparison-footer-panel", className="comparison-modal-footer"),
                        ],
                        className="comparison-modal-panel",
                    )
                ],
                id="relative-comparison-modal",
                className="comparison-modal comparison-modal-hidden",
            ),
        ],
        className="dashboard-shell",
    )


app = Dash(
    __name__,
    assets_folder=str(ASSET_DIR),
    title="Strategic Metals Dashboard",
    update_title=None,
    suppress_callback_exceptions=True,
)
app.layout = build_app_shell()
server = app.server


@app.callback(
    Output("status-row", "children"),
    Output("dashboard-content", "children"),
    Output("ranked-records-store", "data"),
    Output("comparison-payload-store", "data"),
    Input("load-trigger", "n_intervals"),
)
def render_dashboard(_n_intervals: int) -> tuple[list[html.Span], list, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    df, error, source, comparison_payload = load_dashboard_data()
    records = df.to_dict("records")
    return _status_children(error, source), _dashboard_sections(df, error), records, comparison_payload


@app.callback(
    Output("stock-table", "children"),
    Output("filtered-records-store", "data"),
    Output("watchlist-metrics", "children"),
    Output("top-candidates-list", "children"),
    Output("comparison-search-count", "children"),
    Input("ranked-records-store", "data"),
    Input("universe-search-input", "value"),
)
def update_ranked_view(
    records: list[dict[str, Any]] | None,
    query: str | None,
) -> tuple[list[Any], list[dict[str, Any]], list[html.Div], html.Div, str]:
    safe_records = [record for record in records or [] if isinstance(record, dict)]
    try:
        filtered_records = hydrate_dashboard_records_from_snapshot(_filter_comparison_records(safe_records, query))
        df = pd.DataFrame(filtered_records, columns=TABLE_COLUMNS)
        return (
            scroll_table_children(
                TABLE_COLUMNS,
                filtered_records,
                numeric_columns=COMPARISON_NUMERIC_COLUMNS,
                wide_columns=COMPARISON_WIDE_COLUMNS,
                sticky_columns_count=2,
                row_id_field="Ticker",
                row_id_type="comparison-row",
            ),
            filtered_records,
            _metric_cards(df),
            _leaderboard(df),
            _search_count_label(len(filtered_records), len(safe_records), query),
        )
    except Exception as exc:
        get_logger(__name__).exception("Ranked view update failed for query %r: %s", query, exc)
        empty_df = pd.DataFrame([], columns=TABLE_COLUMNS)
        return (
            scroll_table_children(
                TABLE_COLUMNS,
                [],
                numeric_columns=COMPARISON_NUMERIC_COLUMNS,
                wide_columns=COMPARISON_WIDE_COLUMNS,
                sticky_columns_count=2,
                row_id_field="Ticker",
                row_id_type="comparison-row",
            ),
            [],
            _metric_cards(empty_df),
            _leaderboard(empty_df),
            "Search temporarily unavailable. Clear the search and try again.",
        )


@app.callback(
    Output("ranked-records-store", "data", allow_duplicate=True),
    Output("comparison-payload-store", "data", allow_duplicate=True),
    Output("financial-refresh-status", "children"),
    Input("load-financials-button", "n_clicks"),
    State("ranked-records-store", "data"),
    State("filtered-records-store", "data"),
    prevent_initial_call=True,
)
def refresh_visible_financials(
    n_clicks: int,
    all_records: list[dict[str, Any]] | None,
    visible_records: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]] | Any, dict[str, dict[str, Any]] | Any, str]:
    if not n_clicks:
        return no_update, no_update, no_update

    all_records = [row for row in all_records or [] if isinstance(row, dict)]
    visible_records = [row for row in visible_records or all_records if isinstance(row, dict)]
    tickers = [normalize_lse_ticker(row.get("Ticker")) for row in visible_records]
    tickers = [ticker for ticker in dict.fromkeys(tickers) if ticker][:FINANCIAL_REFRESH_LIMIT]
    if not tickers:
        return no_update, no_update, "No matching companies to refresh."

    refreshed_rows: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for ticker in tickers:
        try:
            refreshed_rows[ticker] = build_dashboard_rows([load_detailed_stock(ticker, force_refresh=True)])[0]
        except Exception as exc:
            failures.append(ticker)
            get_logger(__name__).warning("Financial refresh failed for %s: %s", ticker, exc)

    if not refreshed_rows:
        return no_update, no_update, f"Could not refresh financials for {len(failures)} companies."

    next_records = [
        refreshed_rows.get(normalize_lse_ticker(row.get("Ticker")), row)
        for row in all_records
    ]
    next_records.sort(key=lambda row: _safe_float(row.get("Score")), reverse=True)
    next_records = hydrate_dashboard_records_from_snapshot(next_records)

    status = f"Loaded financials for {len(refreshed_rows)} companies"
    if failures:
        status += f"; {len(failures)} failed"
    if len(tickers) == FINANCIAL_REFRESH_LIMIT:
        status += f" (limit {FINANCIAL_REFRESH_LIMIT})"
    return next_records, _build_comparison_payload(next_records), status + "."


@app.callback(
    Output("comparison-selection-store", "data"),
    Output("comparison-modal-tabs", "value"),
    Input({"type": "comparison-row", "ticker": ALL}, "n_clicks"),
    Input({"type": "compare-add", "ticker": ALL}, "n_clicks"),
    Input({"type": "compare-remove", "ticker": ALL}, "n_clicks"),
    Input("compare-clear-button", "n_clicks"),
    Input("compare-close-button", "n_clicks"),
    State("comparison-selection-store", "data"),
    prevent_initial_call=True,
)
def update_comparison_selection(
    _row_clicks: list[int],
    _add_clicks: list[int],
    _remove_clicks: list[int],
    _clear_clicks: int,
    _close_clicks: int,
    selection: list[str] | None,
) -> tuple[list[str] | Any, str | Any]:
    trigger = ctx.triggered[0] if ctx.triggered else {}
    triggered = ctx.triggered_id
    trigger_value = trigger.get("value")
    prop_id = str(trigger.get("prop_id") or "")
    if not triggered and not prop_id:
        return no_update, no_update

    if isinstance(triggered, str) and triggered in {"compare-clear-button", "compare-close-button"} and trigger_value:
        get_logger(__name__).info("Comparison modal selection cleared via %s", triggered)
        return [], OVERVIEW_TAB

    action = None
    ticker = None
    if hasattr(triggered, "get"):
        action = triggered.get("type")
        ticker = triggered.get("ticker")
    elif prop_id and prop_id != ".":
        raw_id = prop_id.rsplit(".", 1)[0]
        try:
            parsed = json.loads(raw_id)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            action = parsed.get("type")
            ticker = parsed.get("ticker")

    if action and ticker:
        action_clicks = {
            "comparison-row": _row_clicks,
            "compare-add": _add_clicks,
            "compare-remove": _remove_clicks,
        }
        click_value = trigger_value if trigger_value is not None else action_clicks.get(action)
        if action in {"comparison-row", "compare-add", "compare-remove"} and not _trigger_has_click(click_value):
            get_logger(__name__).info(
                "Ignoring comparison trigger without click action=%s ticker=%s value=%r",
                action,
                ticker,
                click_value,
            )
            return no_update, no_update
        if action == "comparison-row":
            value = normalize_lse_ticker(ticker)
            get_logger(__name__).info("Comparison modal opened for %s on overview tab", value)
            return ([value] if value else []), OVERVIEW_TAB
        if action == "compare-add":
            next_selection = _add_comparison_ticker(selection, ticker)
            get_logger(__name__).info("Comparison peer added ticker=%s selection=%s", ticker, next_selection)
            return next_selection, COMPARE_TAB
        if action == "compare-remove":
            next_selection = _remove_comparison_ticker(selection, ticker)
            get_logger(__name__).info("Comparison peer removed ticker=%s selection=%s", ticker, next_selection)
            return next_selection, COMPARE_TAB if next_selection else OVERVIEW_TAB

    return no_update, no_update


@app.callback(
    Output("comparison-chart-store", "data"),
    Input("comparison-selection-store", "data"),
    State("comparison-payload-store", "data"),
    State("comparison-chart-store", "data"),
)
def load_comparison_chart(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]] | None,
    current_chart: dict[str, Any] | None = None,
) -> dict[str, Any] | Any:
    current_chart = current_chart if isinstance(current_chart, dict) else {}
    payload = _normalise_comparison_payload(payload)
    selection = [ticker for ticker in _normalise_selection(selection) if ticker in payload]
    if not selection:
        return {}

    ticker = selection[0]
    if current_chart.get("ticker") == ticker and current_chart.get("status") in {"loaded", "fallback", "unavailable"}:
        get_logger(__name__).info("Comparison chart reused ticker=%s status=%s", ticker, current_chart.get("status"))
        return current_chart

    try:
        chart = fetch_yahoo_price_history(ticker)
    except Exception as exc:
        get_logger(__name__).warning("Yahoo chart unavailable for %s: %s", ticker, exc)
        return {"ticker": ticker, "points": [], "status": "unavailable", "error": str(exc)[:180]}

    if not chart.get("points"):
        get_logger(__name__).info("Comparison chart fallback ticker=%s reason=no_points", ticker)
        return {"ticker": ticker, "points": [], "status": "fallback"}
    chart["ticker"] = ticker
    chart["status"] = "loaded"
    get_logger(__name__).info("Comparison chart loaded ticker=%s points=%s", ticker, len(chart.get("points") or []))
    return chart


@app.callback(
    Output("relative-comparison-modal", "className"),
    Output("comparison-main-panel", "children"),
    Output("comparison-footer-panel", "children"),
    Output("comparison-side-tools", "style"),
    Input("comparison-selection-store", "data"),
    Input("comparison-payload-store", "data"),
    Input("comparison-modal-tabs", "value"),
    Input("comparison-chart-store", "data"),
)
def render_relative_comparison_frame(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]] | None,
    active_tab: str | None = OVERVIEW_TAB,
    chart_payload: dict[str, Any] | None = None,
) -> tuple[str, list[Any], list[Any], dict[str, str]]:
    class_name, main_panel, _side_panel, footer_panel, side_tools_style = render_relative_comparison_modal(
        selection,
        payload,
        "",
        active_tab,
        chart_payload,
    )
    return class_name, main_panel, footer_panel, side_tools_style


@app.callback(
    Output("comparison-side-panel", "children"),
    Input("comparison-selection-store", "data"),
    Input("comparison-payload-store", "data"),
    Input("compare-peer-search", "value"),
    Input("comparison-modal-tabs", "value"),
)
def render_relative_comparison_side_panel(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]] | None,
    query: str | None,
    active_tab: str | None = OVERVIEW_TAB,
) -> list[Any]:
    payload = _normalise_comparison_payload(payload)
    selection = [ticker for ticker in _normalise_selection(selection) if ticker in payload]
    if not selection:
        return []

    active_tab = _normalise_modal_tab(active_tab)
    get_logger(__name__).info(
        "Comparison side panel render tab=%s selection=%s query_len=%s",
        active_tab,
        selection,
        len(_safe_text(query)),
    )
    try:
        if active_tab == COMPARE_TAB:
            return _comparison_side_panel(selection, payload, query)
        return _company_overview_side_panel(_selected_overview_company(selection, payload))
    except Exception as exc:
        get_logger(__name__).exception("Relative comparison side panel render failed: %s", exc)
        return [html.Div("Comparison controls are paused for this selection.", className="comparison-muted")]


def render_relative_comparison_modal(
    selection: list[str] | None,
    payload: dict[str, dict[str, Any]] | None,
    query: str | None,
    active_tab: str | None = OVERVIEW_TAB,
    chart_payload: dict[str, Any] | None = None,
) -> tuple[str, list[Any], list[Any], list[Any], dict[str, str]]:
    payload = _normalise_comparison_payload(payload)
    selection = [ticker for ticker in _normalise_selection(selection) if ticker in payload]
    if not selection:
        return "comparison-modal comparison-modal-hidden", [], [], [], {}

    active_tab = _normalise_modal_tab(active_tab)
    get_logger(__name__).info(
        "Comparison modal render tab=%s selection=%s payload=%s chart_status=%s",
        active_tab,
        selection,
        len(payload),
        chart_payload.get("status") if isinstance(chart_payload, dict) else "none",
    )
    try:
        if active_tab == COMPARE_TAB:
            main_panel = _comparison_main_panel(selection, payload)
            side_panel = _comparison_side_panel(selection, payload, query)
            footer_panel = _comparison_footer()
            side_tools_style = {}
        else:
            selected_company = _selected_overview_company(selection, payload)
            main_panel = _company_overview_main(selection, payload, chart_payload)
            side_panel = _company_overview_side_panel(selected_company)
            footer_panel = []
            side_tools_style = {"display": "none"}
    except Exception as exc:
        get_logger(__name__).exception("Relative comparison render failed: %s", exc)
        return (
            "comparison-modal",
            [
                html.Div(
                    "The comparison panel hit a recoverable display issue. Clear the selection and try again.",
                    className="empty-state",
                )
            ],
            [html.Div("Comparison controls are paused for this selection.", className="comparison-muted")],
            _comparison_footer() if active_tab == COMPARE_TAB else [],
            {} if active_tab == COMPARE_TAB else {"display": "none"},
        )

    return (
        "comparison-modal",
        main_panel,
        side_panel,
        footer_panel,
        side_tools_style,
    )


if __name__ == "__main__":
    app.run(debug=False, port=int(os.getenv("PORT", "8050")), use_reloader=False)
