from __future__ import annotations

from typing import Any

from dash import html
from dash import dash_table

COLUMN_TOOLTIPS = {
    "Score": "Final 0-10 composite score used for ranking after stage gates.",
    "Score Status": "full means detailed market, financial, and technical fields are available; partial means some key fields are missing; metadata_only means only lightweight universe metadata is loaded; stale means cached detail is expired after a failed refresh.",
    "Full Score": "Detailed score calculated after on-demand market/fundamental data is loaded.",
    "Prelim Score": "Lightweight metadata-only score used before expensive financial data is fetched.",
    "Tech Score": "Technical asset score covering resource scale, grade, magnet basket quality, mineralogy, metallurgy, confidence, and impurity risk.",
    "Commercial Score": "Commercial and financial score covering revenue quality, debt, cash runway, study economics, and funding/offtake validation.",
    "Strategic Score": "Strategic supply-chain score covering jurisdiction, processing depth, ex-China relevance, ESG, permitting, and downstream role.",
    "Benchmark Score": "Workbook-style benchmark score for deposit value, NPV, downstream revenue, production visibility, and strategic criticality where data exists.",
    "Confidence": "0-10 data quality score based on field coverage, freshness, and core scoring evidence.",
    "Confidence Level": "High, Medium, or Low label derived from benchmark data completeness.",
    "Data Coverage": "Share of key financial fields currently populated: market cap, price, volume, 52-week range, revenue, debt metric, and shares.",
    "Rating": "Analytical label derived from the final score. It is not a buy/sell/hold recommendation.",
    "Peer Group": "Suggested comparison group derived from sector coverage or supply-chain role.",
    "Segment": "LSE trading segment code, such as SETS/SETSqx/AIM segment identifiers. Useful for liquidity and listing context.",
    "Market Cap": "Market capitalisation from LSE first, then fallback sources or calculated price x shares when available.",
    "Last Price": "Latest available quoted price from LSE or fallback market data.",
    "Revenue LFY": "Last fiscal-year revenue when available. Fallback providers may supply trailing revenue estimates, noted in Data Notes.",
    "Debt Metric": "Debt basis shown per row: LT debt/capital from LSE tearsheet first, otherwise net debt/equity from fallback analytics.",
    "Shares Outstanding": "Shares outstanding from LSE tearsheet first, otherwise fallback market data when available.",
    "52W Range": "52-week low and high from LSE instrument data or tearsheet fallback.",
    "Mineralogy": "RNS-derived mineral host evidence such as monazite, bastnaesite, xenotime, ionic clay, phosphogypsum, or complex hosts.",
    "Recovery": "Metallurgical recovery percentage extracted from RNS text where available; otherwise flags whether testwork was found without a numeric recovery.",
    "Study Stage": "RNS-derived technical stage such as scoping, PEA, PFS, DFS, FEED, pilot, construction, or operation.",
    "Resource Confidence": "Highest RNS-derived reserve/resource confidence signal, e.g. reserve, measured, indicated, inferred, or exploration target.",
    "Impurity Profile": "RNS-derived impurity or radioactivity evidence, including thorium, uranium, radionuclide, or clean/low-impurity indications.",
    "Technical Status": "Whether RNS/documentation was found and whether structured technical fields were extracted or still need analyst review.",
    "Technical Source": "Most recent technical RNS title or evidence source feeding the asset-quality score.",
    "Stage Gates": "Caps applied to prevent weakly evidenced early projects from scoring as advanced assets.",
    "Missing Data": "Fields needed by the methodology that are unavailable for this company.",
    "Drivers": "Short explanation bullets from financial and rare-earth scoring.",
    "Positive Drivers": "Highest-signal positive benchmark or scoring reasons.",
    "Negative Drivers": "Highest-signal negative or missing-data reasons.",
    "Data Notes": "Fallback fields used to improve coverage, such as Yahoo Finance or London South East sector cache fills.",
    "Source": "Primary and fallback source names for the displayed row.",
}


def _column_name(column: str) -> str:
    return f"{column} (?)" if column in COLUMN_TOOLTIPS else column


def _cell_classes(
    column: str,
    index: int,
    *,
    numeric_columns: set[str],
    wide_columns: set[str],
    sticky_columns_count: int,
    value: Any = None,
) -> str:
    classes = ["scoreboard-cell"]
    if column in numeric_columns:
        classes.append("scoreboard-cell-numeric")
    if column in wide_columns:
        classes.append("scoreboard-cell-wide")
    if index < sticky_columns_count:
        classes.append("scoreboard-cell-sticky")
        classes.append(f"scoreboard-cell-sticky-{index + 1}")
    if column == "Score":
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = None
        if score is not None and score >= 7:
            classes.append("scoreboard-score-high")
        elif score is not None and score >= 5:
            classes.append("scoreboard-score-mid")
        elif score is not None and score < 3:
            classes.append("scoreboard-score-low")
    if column == "Score Status":
        status = str(value or "").lower()
        if status in {"full", "partial", "stale", "metadata_only"}:
            classes.append(f"scoreboard-status-{status.replace('_', '-')}")
    return " ".join(classes)


def _col_classes(
    column: str,
    index: int,
    *,
    numeric_columns: set[str],
    wide_columns: set[str],
    sticky_columns_count: int,
) -> str:
    classes = ["scoreboard-col"]
    if column in numeric_columns:
        classes.append("scoreboard-col-numeric")
    if column in wide_columns:
        classes.append("scoreboard-col-wide")
    if index < sticky_columns_count:
        classes.append(f"scoreboard-col-sticky-{index + 1}")
    return " ".join(classes)


def _cell_content(value: Any, click_id: dict[str, str] | None = None) -> html.Div:
    text = str(value if value is not None else "")
    if click_id:
        return html.Div(
            [
                html.Button(
                    "More",
                    id=click_id,
                    n_clicks=0,
                    className="scoreboard-compare-button",
                    title=f"Open company overview for {text}",
                ),
                html.Span(text, className="scoreboard-company-name"),
            ],
            className="scoreboard-cell-content scoreboard-company-action-cell",
            title=text,
        )
    return html.Div(text, className="scoreboard-cell-content", title=text)


def scroll_table_children(
    columns: list[str],
    records: list[dict[str, Any]],
    *,
    numeric_columns: list[str] | None = None,
    wide_columns: list[str] | None = None,
    sticky_columns_count: int = 0,
    row_id_field: str | None = None,
    row_id_type: str | None = None,
) -> list[Any]:
    numeric_column_set = set(numeric_columns or [])
    wide_column_set = set(wide_columns or [])
    colgroup = html.Colgroup(
        [
            html.Col(
                className=_col_classes(
                    column,
                    index,
                    numeric_columns=numeric_column_set,
                    wide_columns=wide_column_set,
                    sticky_columns_count=sticky_columns_count,
                )
            )
            for index, column in enumerate(columns)
        ]
    )
    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    html.Div(_column_name(column), className="scoreboard-header-content"),
                    title=COLUMN_TOOLTIPS.get(column),
                    className=_cell_classes(
                        column,
                        index,
                        numeric_columns=numeric_column_set,
                        wide_columns=wide_column_set,
                        sticky_columns_count=sticky_columns_count,
                    ),
                )
                for index, column in enumerate(columns)
            ]
        )
    )
    body_rows = []
    for record in records:
        row_kwargs: dict[str, Any] = {"className": "scoreboard-row"}
        row_click_id: dict[str, str] | None = None
        if row_id_field and row_id_type and record.get(row_id_field):
            row_click_id = {"type": row_id_type, "ticker": str(record.get(row_id_field))}
            row_kwargs.update(
                {
                    "className": "scoreboard-row scoreboard-row-clickable",
                    "title": "Open relative comparison card",
                }
            )
        body_rows.append(
            html.Tr(
                [
                    html.Td(
                        _cell_content(
                            record.get(column, ""),
                            click_id=row_click_id if index == 0 else None,
                        ),
                        className=_cell_classes(
                            column,
                            index,
                            numeric_columns=numeric_column_set,
                            wide_columns=wide_column_set,
                            sticky_columns_count=sticky_columns_count,
                            value=record.get(column),
                        ),
                    )
                    for index, column in enumerate(columns)
                ],
                **row_kwargs,
            )
        )
    body = html.Tbody(body_rows)
    return [
        html.Table(
            [colgroup, header, body],
            className="scoreboard-table",
        )
    ]


def scroll_table(
    table_id: str,
    columns: list[str],
    records: list[dict[str, Any]],
    *,
    max_height: str = "72vh",
    numeric_columns: list[str] | None = None,
    wide_columns: list[str] | None = None,
    sticky_columns_count: int = 0,
    row_id_field: str | None = None,
    row_id_type: str | None = None,
) -> html.Div:
    return html.Div(
        scroll_table_children(
            columns,
            records,
            numeric_columns=numeric_columns,
            wide_columns=wide_columns,
            sticky_columns_count=sticky_columns_count,
            row_id_field=row_id_field,
            row_id_type=row_id_type,
        ),
        id=table_id,
        className="scroll-table-shell",
        style={"maxHeight": max_height},
    )


def data_table(
    table_id: str,
    columns: list[str],
    records: list[dict[str, Any]],
    page_size: int = 12,
    page_action: str = "native",
    max_height: str | None = None,
    numeric_columns: list[str] | None = None,
    wide_columns: list[str] | None = None,
    row_selectable: str | bool | None = None,
    fixed_columns_count: int = 0,
) -> dash_table.DataTable:
    numeric_columns = numeric_columns or []
    wide_columns = wide_columns or []

    style_cell_conditional = [
        {"if": {"column_id": column}, "textAlign": "right", "width": "112px"}
        for column in numeric_columns
    ]
    style_cell_conditional.extend(
        {"if": {"column_id": column}, "minWidth": "240px"}
        for column in wide_columns
    )

    style_data_conditional = []
    if "Score" in columns:
        style_data_conditional = [
            {
                "if": {"filter_query": "{Score} >= 7", "column_id": "Score"},
                "backgroundColor": "#dff3ea",
                "color": "#0f5132",
                "fontWeight": "700",
            },
            {
                "if": {"filter_query": "{Score} >= 5 && {Score} < 7", "column_id": "Score"},
                "backgroundColor": "#fff1cf",
                "color": "#73510b",
                "fontWeight": "700",
            },
            {
                "if": {"filter_query": "{Score} < 3", "column_id": "Score"},
                "backgroundColor": "#fbe3df",
                "color": "#8a1f11",
                "fontWeight": "700",
            },
        ]
    if "Score Status" in columns:
        style_data_conditional.extend(
            [
                {
                    "if": {"filter_query": '{Score Status} = "full"', "column_id": "Score Status"},
                    "backgroundColor": "#dff3ea",
                    "color": "#0f5132",
                    "fontWeight": "700",
                },
                {
                    "if": {"filter_query": '{Score Status} = "partial"', "column_id": "Score Status"},
                    "backgroundColor": "#fff1cf",
                    "color": "#73510b",
                    "fontWeight": "700",
                },
                {
                    "if": {"filter_query": '{Score Status} = "stale"', "column_id": "Score Status"},
                    "backgroundColor": "#fbe3df",
                    "color": "#8a1f11",
                    "fontWeight": "700",
                },
                {
                    "if": {"filter_query": '{Score Status} = "metadata_only"', "column_id": "Score Status"},
                    "backgroundColor": "#e8edf1",
                    "color": "#334155",
                    "fontWeight": "700",
                },
            ]
        )

    options: dict[str, Any] = {}
    if row_selectable:
        options["row_selectable"] = row_selectable
        options["selected_rows"] = []
    if fixed_columns_count:
        options["fixed_columns"] = {"headers": True, "data": fixed_columns_count}

    style_table = {"overflowX": "auto", "minWidth": "100%", "maxWidth": "100%"}
    if max_height:
        style_table["maxHeight"] = max_height
        style_table["overflowY"] = "auto"

    return dash_table.DataTable(
        id=table_id,
        columns=[{"name": _column_name(column), "id": column} for column in columns],
        data=records,
        tooltip_header={column: COLUMN_TOOLTIPS[column] for column in columns if column in COLUMN_TOOLTIPS},
        tooltip_delay=350,
        tooltip_duration=None,
        sort_action="native",
        filter_action="native",
        page_action=page_action,
        page_size=page_size,
        fixed_rows={"headers": True},
        style_as_list_view=True,
        style_table=style_table,
        style_header={
            "backgroundColor": "#17211f",
            "color": "#f6f2e8",
            "fontWeight": "700",
            "border": "0",
            "padding": "12px",
        },
        style_cell={
            "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
            "fontSize": "13px",
            "padding": "12px",
            "border": "0",
            "borderBottom": "1px solid #e5e1d8",
            "backgroundColor": "#fffdf8",
            "color": "#1d2725",
            "textAlign": "left",
            "whiteSpace": "normal",
            "height": "auto",
            "minWidth": "104px",
        },
        style_cell_conditional=style_cell_conditional,
        style_data_conditional=style_data_conditional,
        **options,
    )
