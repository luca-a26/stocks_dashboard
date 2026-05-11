from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html, no_update

from analysis.composite import load_default_ranked_stocks, load_detailed_stock
from dashboard.components import data_table
from dashboard.discovery_view_model import (
    CATALYST_COLUMNS,
    PROJECT_COLUMNS,
    SUPPLY_CHAIN_COLUMNS,
    build_catalyst_rows,
    build_project_rows,
    build_supply_chain_rows,
)
from dashboard.view_model import SEARCH_COLUMNS, TABLE_COLUMNS, build_dashboard_rows, build_universe_search_rows
from data.discovery import (
    count_by,
    load_catalysts,
    load_project_pipeline,
    load_supply_chain_rankings,
)
from data.universe import load_ticker_universe, preliminary_score, search_ticker_universe
from data.utils import get_logger

ASSET_DIR = Path(__file__).resolve().parent / "assets"


def load_dashboard_frame() -> tuple[pd.DataFrame, str | None, str]:
    try:
        stocks, source = load_default_ranked_stocks(limit=100)
        rows = build_dashboard_rows(stocks)
        return pd.DataFrame(rows, columns=TABLE_COLUMNS), None, source
    except Exception as exc:
        get_logger(__name__).exception("Dashboard data load failed")
        return pd.DataFrame(columns=TABLE_COLUMNS), str(exc), "load failed"


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

    avg_score = df["Score"].mean()
    leader = df.sort_values("Score", ascending=False).iloc[0]
    review_count = int((df["Score"] < 3).sum())

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
    for _, row in df.sort_values("Score", ascending=False).head(5).iterrows():
        items.append(
            html.Div(
                [
                    html.Div([html.Strong(row["Ticker"]), html.Span(row["Company"])]),
                    html.Div(f"{row['Score']:.1f}", className="score-pill"),
                ],
                className="ranked-item",
            )
        )
    return html.Div(items, className="ranked-list")


def _status_children(error: str | None = None, source: str | None = None) -> list[html.Span]:
    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "Data warning" if error else "Live fundamentals"
    class_name = "status-pill" if error else "status-pill status-live"
    return [
        html.Span(status, className=class_name),
        html.Span(f"Top 100: {source or 'metadata'}", className="status-pill"),
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


def _search_panel() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    dcc.Input(
                        id="universe-search-input",
                        type="search",
                        debounce=True,
                        placeholder="Search ticker, company, exchange, commodity, country, or supply-chain role",
                        className="universe-search-input",
                    ),
                    html.Button("Load Details", id="load-selected-button", n_clicks=0, className="action-button"),
                    html.Button("Add To Ranked", id="add-selected-button", n_clicks=0, className="action-button secondary"),
                ],
                className="search-controls",
            ),
            dcc.Loading(
                data_table(
                    "universe-results-table",
                    SEARCH_COLUMNS,
                    [],
                    page_size=6,
                    numeric_columns=["Prelim Score"],
                    wide_columns=["Company", "Commodity", "Role"],
                    row_selectable="single",
                ),
                type="dot",
            ),
            dcc.Loading(html.Div("Search the metadata universe, then load one company on demand.", id="detail-status", className="detail-status"), type="dot"),
            html.Div("", id="add-status", className="detail-status"),
        ],
        className="search-panel",
    )


def _watchlist_tab(df: pd.DataFrame, error: str | None) -> html.Div:
    return html.Div(
        [
            html.Section(_metric_cards(df), className="metric-grid", id="watchlist-metrics"),
            html.Div(error, className="error-banner") if error else None,
            _panel(
                "Universe Search",
                "Find And Add Companies",
                _search_panel(),
                "table-panel full-width-panel",
            ),
            html.Section(
                [
                    _panel(
                        "Watchlist",
                        "LSE Fundamental Scoreboard",
                        data_table(
                            "stock-table",
                            TABLE_COLUMNS,
                            df.to_dict("records"),
                            page_size=12,
                            numeric_columns=[
                                "Score",
                                "Full Score",
                                "Prelim Score",
                                "Tech Score",
                                "Commercial Score",
                                "Strategic Score",
                                "Confidence",
                                "Market Cap",
                                "Last Price",
                                "Revenue LFY",
                                "Debt Metric",
                                "Shares Outstanding",
                                "Volume",
                            ],
                            wide_columns=[
                                "Company",
                                "Alias",
                                "Commodity",
                                "Role",
                                "Stage Gates",
                                "Missing Data",
                                "Drivers",
                                "Source",
                            ],
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
            dcc.Store(id="selected-detail-store"),
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
            html.Div(
                html.Div("Loading watchlist data...", className="empty-state"),
                id="dashboard-content",
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
    Input("load-trigger", "n_intervals"),
)
def render_dashboard(_n_intervals: int) -> tuple[list[html.Span], list, list[dict[str, Any]]]:
    df, error, source = load_dashboard_frame()
    records = df.to_dict("records")
    return _status_children(error, source), _dashboard_sections(df, error), records


@app.callback(
    Output("stock-table", "data"),
    Output("watchlist-metrics", "children"),
    Output("top-candidates-list", "children"),
    Input("ranked-records-store", "data"),
)
def update_ranked_view(records: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[html.Div], html.Div]:
    records = records or []
    df = pd.DataFrame(records, columns=TABLE_COLUMNS)
    return records, _metric_cards(df), _leaderboard(df)


@app.callback(
    Output("universe-results-table", "data"),
    Input("universe-search-input", "value"),
)
def search_universe(query: str | None) -> list[dict[str, Any]]:
    if not query:
        return []
    records = []
    for record in search_ticker_universe(query, load_ticker_universe(), limit=25):
        record = dict(record)
        record["preliminary_score"] = preliminary_score(record)
        records.append(record)
    return build_universe_search_rows(records)


@app.callback(
    Output("selected-detail-store", "data"),
    Output("detail-status", "children"),
    Input("load-selected-button", "n_clicks"),
    State("universe-results-table", "selected_rows"),
    State("universe-results-table", "data"),
    prevent_initial_call=True,
)
def load_selected_detail(
    n_clicks: int,
    selected_rows: list[int] | None,
    rows: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | Any, html.Div | str]:
    if not n_clicks:
        return no_update, no_update
    if not selected_rows or not rows:
        return no_update, "Select a company from the search results first."

    selected = rows[selected_rows[0]]
    ticker = selected.get("Ticker")
    if not ticker:
        return no_update, "Selected row has no ticker."

    try:
        detail = build_dashboard_rows([load_detailed_stock(ticker)])[0]
    except Exception as exc:
        get_logger(__name__).exception("Search detail load failed for %s", ticker)
        return no_update, f"Could not load {ticker}: {exc}"

    return detail, html.Div(
        [
            html.Strong(f"{detail['Ticker']} loaded"),
            html.Span(f"{detail['Company']} | score {detail['Score']} | {detail['Score Status']}"),
        ],
        className="detail-loaded",
    )


@app.callback(
    Output("ranked-records-store", "data", allow_duplicate=True),
    Output("add-status", "children"),
    Input("add-selected-button", "n_clicks"),
    State("selected-detail-store", "data"),
    State("ranked-records-store", "data"),
    prevent_initial_call=True,
)
def add_selected_to_ranked(
    n_clicks: int,
    detail: dict[str, Any] | None,
    records: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]] | Any, str]:
    if not n_clicks:
        return no_update, ""
    if not detail:
        return no_update, "Load company details before adding it to ranked candidates."

    records = records or []
    ticker = detail.get("Ticker")
    next_records = [row for row in records if row.get("Ticker") != ticker]
    next_records.append(detail)
    next_records.sort(key=lambda row: float(row.get("Score") or 0), reverse=True)
    return next_records, f"{ticker} added to ranked candidates."


if __name__ == "__main__":
    app.run(debug=False, port=int(os.getenv("PORT", "8050")), use_reloader=False)
