from __future__ import annotations

from typing import Any

from dash import dash_table


def data_table(
    table_id: str,
    columns: list[str],
    records: list[dict[str, Any]],
    page_size: int = 12,
    numeric_columns: list[str] | None = None,
    wide_columns: list[str] | None = None,
    row_selectable: str | bool | None = None,
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

    return dash_table.DataTable(
        id=table_id,
        columns=[{"name": column, "id": column} for column in columns],
        data=records,
        sort_action="native",
        filter_action="native",
        page_size=page_size,
        fixed_rows={"headers": True},
        style_as_list_view=True,
        style_table={"overflowX": "auto", "minWidth": "100%"},
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
