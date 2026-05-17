import pandas as pd

from dashboard import dashboard as dashboard_module
from dashboard.dashboard import (
    COMPARE_TAB,
    OVERVIEW_TAB,
    _add_comparison_ticker,
    _build_comparison_payload,
    _company_overview_main,
    _company_overview_side_panel,
    _comparison_candidates,
    _comparison_side_panel,
    _filter_comparison_records,
    _leaderboard,
    _metric_cards,
    _normalise_selection,
    _remove_comparison_ticker,
    _resource_links,
    _share_chart_figure,
    _trigger_has_click,
    app,
    load_comparison_chart,
    render_relative_comparison_modal,
    update_ranked_view,
)
from dashboard import view_model
from dashboard.components import COLUMN_TOOLTIPS, _column_name, scroll_table, scroll_table_children
from dashboard.view_model import TABLE_COLUMNS, build_dashboard_rows, hydrate_dashboard_records_from_snapshot


def _find_component_by_id(component, component_id):
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            found = _find_component_by_id(child, component_id)
            if found is not None:
                return found
    elif children is not None and not isinstance(children, (str, int, float)):
        return _find_component_by_id(children, component_id)
    return None


def _callback_output_key(*contains: str) -> str:
    for key in app.callback_map:
        if all(part in key for part in contains):
            return key
    raise AssertionError(f"No Dash callback output contains: {contains}")


def test_build_dashboard_rows_uses_lse_fundamental_fields():
    rows = build_dashboard_rows(
        [
            {
                "ticker": "PRE",
                "name": "Pensana",
                "exchange": "LSE",
                "composite_score": 6.5,
                "fundamental": {
                    "fundamentals": {"score": 6.5, "drivers": ["LSE market cap available"]},
                    "metrics": {
                        "market_cap": 1_200_000,
                        "market": "MAINMARKET",
                        "segment": "SET3",
                        "issuer_name": "PENSANA PLC",
                        "last_price": 101.2,
                        "currency": "GBX",
                        "revenue_lfy": 5_000_000,
                        "long_term_debt_to_capital_pct": 8.5,
                        "net_debt_to_equity_pct": None,
                        "shares_outstanding_lfy": 339_248_000,
                        "volume": 16_062,
                        "fifty_two_week_low": 26.6,
                        "fifty_two_week_high": 184.5,
                        "source": "London Stock Exchange",
                        "data_coverage_ratio": 1.0,
                        "data_fallbacks": ["revenue_lfy from Yahoo Finance fallback"],
                        "retrieved": "2026-02-11T20:00:00+00:00",
                    },
                },
            }
        ]
    )

    assert rows[0]["Ticker"] == "PRE"
    assert rows[0]["Company"] == "PENSANA PLC"
    assert rows[0]["Exchange"] == "MAINMARKET"
    assert rows[0]["Segment"] == "SET3"
    assert rows[0]["Rating"] == "Strong watchlist"
    assert rows[0]["Market Cap"] == "1.2M"
    assert rows[0]["Last Price"] == "101.2 GBX"
    assert rows[0]["Revenue LFY"] == "5.0M"
    assert rows[0]["Debt Metric"] == "8.5% LT debt/cap"
    assert rows[0]["Shares Outstanding"] == "339.2M"
    assert rows[0]["Data Coverage"] == "100%"
    assert rows[0]["Data Notes"] == "revenue_lfy from Yahoo Finance fallback"
    assert "Sentiment" not in rows[0]


def test_filter_comparison_records_matches_company_ticker_and_commodity():
    records = [
        {
            "Ticker": "RBW",
            "Company": "Rainbow Rare Earths",
            "Exchange": "LSE",
            "Commodity": "rare earths, phosphogypsum",
            "Role": "Developer + processor",
            "Score Status": "metadata_only",
        },
        {
            "Ticker": "RIO",
            "Company": "Rio Tinto",
            "Exchange": "LSE",
            "Commodity": "industrial metals",
            "Role": "Producer",
            "Score Status": "metadata_only",
        },
    ]

    assert _filter_comparison_records(records, "rainbow")[0]["Ticker"] == "RBW"
    assert _filter_comparison_records(records, "rio")[0]["Ticker"] == "RIO"
    assert _filter_comparison_records(records, "rare processor")[0]["Ticker"] == "RBW"


def test_filter_comparison_records_ignores_malformed_rows_and_long_queries():
    records = [
        {"Ticker": "PRE", "Company": "Pensana", "Commodity": ["rare earths", "NdPr"]},
        "bad row",
        None,
    ]

    filtered = _filter_comparison_records(records, "rare " * 100)

    assert filtered == [{"Ticker": "PRE", "Company": "Pensana", "Commodity": ["rare earths", "NdPr"]}]


def test_search_inputs_are_throttled_to_reduce_callback_churn():
    shell = dashboard_module.build_app_shell()
    top_search = _find_component_by_id(shell, "universe-search-input")
    peer_search = _find_component_by_id(shell, "compare-peer-search")

    assert top_search is not None
    assert peer_search is not None
    assert top_search.debounce == 0.35
    assert top_search.maxLength == 80
    assert peer_search.debounce == 0.35
    assert peer_search.maxLength == 80


def test_metric_cards_and_leaderboard_handle_non_numeric_scores():
    df = pd.DataFrame(
        [
            {"Ticker": "BAD", "Company": "Bad Score Plc", "Score": "not loaded"},
            {"Ticker": "PRE", "Company": "Pensana", "Score": 7.2},
        ]
    )

    cards = _metric_cards(df)
    leaderboard = _leaderboard(df)

    assert "Average Score" in str(cards)
    assert "Pensana" in str(leaderboard)


def test_update_ranked_view_handles_bad_score_rows_without_crashing():
    children, filtered, metrics, leaderboard, label = update_ranked_view(
        [{"Ticker": "BAD", "Company": "Bad Score Plc", "Score": "not loaded"}],
        "bad",
    )

    assert children
    assert filtered[0]["Ticker"] == "BAD"
    assert metrics
    assert leaderboard
    assert label == "Showing 1 of 1 companies"


def test_update_ranked_view_returns_safe_state_on_transform_error(monkeypatch):
    monkeypatch.setattr(
        dashboard_module,
        "hydrate_dashboard_records_from_snapshot",
        lambda _records: (_ for _ in ()).throw(RuntimeError("transform failed")),
    )

    children, filtered, metrics, leaderboard, label = dashboard_module.update_ranked_view(
        [{"Ticker": "PRE", "Company": "Pensana", "Score": 7.2}],
        "pre",
    )

    assert children
    assert filtered == []
    assert metrics
    assert leaderboard
    assert "temporarily unavailable" in label


def test_table_columns_keep_company_sticky_and_move_commodity_later():
    assert TABLE_COLUMNS[:2] == ["Company", "Ticker"]
    assert TABLE_COLUMNS.index("Commodity") == TABLE_COLUMNS.index("Stage Gates") - 1


def test_key_table_terms_have_header_tooltips():
    for column in ("Debt Metric", "Tech Score", "Commercial Score", "Strategic Score", "Benchmark Score", "Segment"):
        assert column in COLUMN_TOOLTIPS
        assert len(COLUMN_TOOLTIPS[column]) > 30
        assert _column_name(column).endswith("(?)")


def test_scroll_table_uses_plain_html_table_for_scoreboard():
    table = scroll_table(
        "stock-table",
        ["Company", "Ticker", "Market Cap"],
        [{"Company": "A", "Ticker": "AAA", "Market Cap": "1.0M"}],
        numeric_columns=["Market Cap"],
        sticky_columns_count=2,
    )
    children = scroll_table_children(
        ["Company", "Ticker", "Market Cap"],
        [{"Company": "A", "Ticker": "AAA", "Market Cap": "1.0M"}],
        numeric_columns=["Market Cap"],
        sticky_columns_count=2,
    )

    assert table.id == "stock-table"
    assert table.className == "scroll-table-shell"
    assert table.children[0].className == "scoreboard-table"
    colgroup = children[0].children[0]
    header_row = children[0].children[1].children
    body_row = children[0].children[2].children[0]
    assert "scoreboard-col-sticky-1" in colgroup.children[0].className
    assert "scoreboard-col-numeric" in colgroup.children[2].className
    assert "scoreboard-cell-sticky-1" in header_row.children[0].className
    assert "scoreboard-cell-numeric" in header_row.children[2].className
    assert body_row.children[0].children.className == "scoreboard-cell-content"
    assert body_row.children[0].children.title == "A"


def test_scroll_table_can_render_clickable_comparison_rows():
    children = scroll_table_children(
        ["Company", "Ticker", "Market Cap"],
        [{"Company": "A", "Ticker": "AAA", "Market Cap": "1.0M"}],
        row_id_field="Ticker",
        row_id_type="comparison-row",
    )

    body_row = children[0].children[2].children[0]
    company_cell = body_row.children[0].children
    company_button = company_cell.children[0]

    assert "scoreboard-row-clickable" in body_row.className
    assert company_button.id == {"type": "comparison-row", "ticker": "AAA"}
    assert company_button.n_clicks == 0
    assert company_button.children == "More"
    assert company_button.title == "Open company overview for A"
    assert "scoreboard-compare-button" in company_button.className


def test_comparison_payload_normalises_tickers_and_keeps_hybrid_scores():
    payload = _build_comparison_payload(
        [
            {
                "Ticker": "BHP.L",
                "Company": "BHP Group",
                "Score": 7.1,
                "Tech Score": 8.2,
                "Commercial Score": 6.4,
                "Strategic Score": 7.0,
                "Market Cap": "200.0B",
                "Positive Drivers": "Strong resource",
            }
        ]
    )

    assert "BHP" in payload
    assert payload["BHP"]["composite_score"] == 7.1
    assert payload["BHP"]["technical_asset_score"] == 8.2
    assert payload["BHP"]["market_cap_display"] == "200.0B"


def test_company_overview_payload_renders_kpis_and_resource_links():
    payload = _build_comparison_payload(
        [
            {
                "Ticker": "PRE",
                "Company": "Pensana",
                "Score": 7.8,
                "Tech Score": 8.0,
                "Commercial Score": 6.0,
                "Strategic Score": 7.0,
                "Benchmark Score": 6.5,
                "Confidence": 4.7,
                "Confidence Level": "Medium",
                "Market Cap": "352.1M",
                "Last Price": "103.8 GBX",
                "Revenue LFY": "Pre-revenue confirmed",
                "Debt Metric": "0.0% LT debt/cap",
                "Shares Outstanding": "339.2M",
                "Volume": "1.2M",
                "52W Range": "33 - 184.5",
                "Rating": "High-quality / advanced",
                "Data Coverage": "100%",
                "Data Notes": "Market snapshot used",
            }
        ]
    )

    main = _company_overview_main(["PRE"], payload, {"ticker": "PRE", "points": []})
    side = _company_overview_side_panel(payload["PRE"])
    links = _resource_links(payload["PRE"])

    assert "Company Overview" in str(main)
    assert "352.1M" in str(main)
    assert "Share Chart" in str(main)
    assert "Resources" in str(side)
    assert any(link["label"] == "Yahoo Finance" for link in links)


def test_company_overview_chart_uses_yahoo_points_when_available():
    figure = _share_chart_figure(
        {"ticker": "PRE", "last_price_display": "103.8 GBX", "range_display": "33 - 184.5"},
        {
            "ticker": "PRE",
            "points": [
                {"date": "2026-01-01", "close": 100.0},
                {"date": "2026-01-02", "close": 104.0},
            ],
        },
    )

    assert figure.data
    assert list(figure.data[0].y) == [100.0, 104.0]
    assert figure.layout.title.text == "Yahoo 1Y Share Chart"


def test_company_overview_chart_falls_back_without_yahoo_points():
    figure = _share_chart_figure(
        {"ticker": "PRE", "last_price_display": "103.8 GBX", "range_display": "33 - 184.5"},
        {"ticker": "PRE", "points": []},
    )

    assert len(figure.data) == 2
    assert figure.layout.title.text == "Share Price Context"


def test_comparison_selection_helpers_add_remove_and_cap_at_four():
    selection = []
    for ticker in ("A", "B", "C", "D", "E"):
        selection = _add_comparison_ticker(selection, ticker)

    assert selection == ["A", "B", "C", "D"]
    assert _add_comparison_ticker(selection, "B") == selection
    assert _remove_comparison_ticker(selection, "C") == ["A", "B", "D"]


def test_comparison_selection_helper_treats_string_as_single_ticker():
    assert _normalise_selection("PRE") == ["PRE"]
    assert _normalise_selection({"not": "a list"}) == []


def test_comparison_trigger_guard_ignores_rendered_zero_clicks():
    assert _trigger_has_click(0) is False
    assert _trigger_has_click([0, None]) is False
    assert _trigger_has_click([]) is False
    assert _trigger_has_click(1) is True
    assert _trigger_has_click([0, 1]) is True


def test_comparison_candidates_skip_bad_payload_records_and_scores():
    payload = {
        "PRE": {
            "ticker": "PRE",
            "company_name": "Pensana",
            "commodity_tags": ["rare earths", "NdPr"],
            "composite_score": "not loaded",
        },
        "BAD": "not a record",
        "RIO": {
            "Ticker": "RIO.L",
            "Company": "Rio Tinto",
            "Commodity": "industrial metals",
            "Score": 7,
        },
    }

    candidates = _comparison_candidates(payload, [], "rare ndpr")

    assert [candidate["ticker"] for candidate in candidates] == ["PRE"]


def test_comparison_side_panel_survives_malformed_payload():
    side_panel = _comparison_side_panel(
        ["PRE", "BAD"],
        {
            "PRE": {"Ticker": "PRE.L", "Company": "Pensana", "composite_score": "not loaded"},
            "BAD": None,
        },
        "",
    )

    assert "PRE" in str(side_panel)
    assert "Pensana" in str(side_panel)


def test_relative_comparison_modal_opens_with_overview_first():
    payload = _build_comparison_payload(
        [
            {
                "Ticker": "PRE",
                "Company": "Pensana",
                "Score": 7.8,
                "Tech Score": 8.0,
                "Commercial Score": 6.0,
                "Strategic Score": 7.0,
                "Market Cap": "352.1M",
                "Rating": "High-quality / advanced",
            }
        ]
    )

    class_name, main, side, footer, side_tools_style = render_relative_comparison_modal(
        ["PRE"],
        payload,
        "",
        OVERVIEW_TAB,
        {"ticker": "PRE", "points": []},
    )

    assert class_name == "comparison-modal"
    assert "Company Overview" in str(main)
    assert "Pensana" in str(main)
    assert "Resources" in str(side)
    assert footer == []
    assert side_tools_style == {"display": "none"}


def test_relative_comparison_modal_compare_tab_keeps_scorecard():
    payload = _build_comparison_payload(
        [
            {"Ticker": "PRE", "Company": "Pensana", "Score": 7.8, "Tech Score": 8.0, "Commercial Score": 6.0, "Strategic Score": 7.0},
            {"Ticker": "RBW", "Company": "Rainbow Rare Earths", "Score": 6.8, "Tech Score": 6.0, "Commercial Score": 5.0, "Strategic Score": 8.0},
        ]
    )

    class_name, main, side, footer, side_tools_style = render_relative_comparison_modal(
        ["PRE", "RBW"],
        payload,
        "",
        COMPARE_TAB,
        {},
    )

    assert class_name == "comparison-modal"
    assert "Total / 25" in str(main)
    assert "Rainbow Rare Earths" in str(main)
    assert "Add more companies" in str(side) or "companies selected" in str(side)
    assert footer
    assert side_tools_style == {}


def test_relative_comparison_modal_unknown_tab_falls_back_to_overview():
    payload = _build_comparison_payload(
        [{"Ticker": "PRE", "Company": "Pensana", "Score": 7.8, "Market Cap": "352.1M"}]
    )

    class_name, main, side, footer, side_tools_style = render_relative_comparison_modal(
        ["PRE"],
        payload,
        "",
        "bad-tab-value",
        {"ticker": "PRE", "points": []},
    )

    assert class_name == "comparison-modal"
    assert "Company Overview" in str(main)
    assert "Resources" in str(side)
    assert footer == []
    assert side_tools_style == {"display": "none"}


def test_relative_comparison_modal_handles_malformed_payload_without_crashing():
    class_name, main, side, footer, side_tools_style = render_relative_comparison_modal(
        ["PRE", "BAD"],
        {
            "PRE": {"Ticker": "PRE.L", "Company": "Pensana", "Score": "not loaded"},
            "BAD": "not a record",
        },
        "rare " * 50,
        OVERVIEW_TAB,
        {},
    )

    assert class_name == "comparison-modal"
    assert "Pensana" in str(main)
    assert "Resources" in str(side)
    assert footer == []
    assert side_tools_style == {"display": "none"}


def test_chart_loader_reuses_existing_chart_when_switching_tabs(monkeypatch):
    payload = _build_comparison_payload([{"Ticker": "PRE", "Company": "Pensana"}])
    existing = {"ticker": "PRE", "points": [{"date": "2026-01-01", "close": 100}], "status": "loaded"}

    def fail_fetch(_ticker):
        raise AssertionError("chart should not be refetched")

    monkeypatch.setattr(dashboard_module, "fetch_yahoo_price_history", fail_fetch)

    assert load_comparison_chart(["PRE"], payload, existing) == existing
    assert load_comparison_chart(["PRE"], payload, existing) == existing


def test_chart_loader_returns_safe_unavailable_payload(monkeypatch):
    payload = _build_comparison_payload([{"Ticker": "PRE", "Company": "Pensana"}])

    def fail_fetch(_ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(dashboard_module, "fetch_yahoo_price_history", fail_fetch)

    chart = load_comparison_chart(["PRE"], payload, {})

    assert chart["ticker"] == "PRE"
    assert chart["points"] == []
    assert chart["status"] == "unavailable"


def test_relative_comparison_modal_hides_when_selection_cleared():
    class_name, main, side, footer, side_tools_style = render_relative_comparison_modal([], {}, "")

    assert class_name == "comparison-modal comparison-modal-hidden"
    assert main == []
    assert side == []
    assert footer == []
    assert side_tools_style == {}


def test_dash_pattern_click_callback_selects_ticker():
    client = app.server.test_client()
    output = _callback_output_key("comparison-selection-store.data", "comparison-modal-tabs.value")
    payload = {
        "output": output,
        "outputs": [
            {"id": "comparison-selection-store", "property": "data"},
            {"id": "comparison-modal-tabs", "property": "value"},
        ],
        "inputs": [
            {"id": '{"ticker":["ALL"],"type":"comparison-row"}', "property": "n_clicks", "value": [1]},
            {"id": '{"ticker":["ALL"],"type":"compare-add"}', "property": "n_clicks", "value": []},
            {"id": '{"ticker":["ALL"],"type":"compare-remove"}', "property": "n_clicks", "value": []},
            {"id": "compare-clear-button", "property": "n_clicks", "value": 0},
            {"id": "compare-close-button", "property": "n_clicks", "value": 0},
        ],
        "state": [{"id": "comparison-selection-store", "property": "data", "value": []}],
        "changedPropIds": ['{"ticker":"PRE","type":"comparison-row"}.n_clicks'],
    }

    response = client.post("/_dash-update-component", json=payload)

    assert response.status_code == 200
    assert response.json["response"]["comparison-selection-store"]["data"] == ["PRE"]
    assert response.json["response"]["comparison-modal-tabs"]["value"] == OVERVIEW_TAB


def test_dash_pattern_add_callback_selects_ticker():
    client = app.server.test_client()
    output = _callback_output_key("comparison-selection-store.data", "comparison-modal-tabs.value")
    payload = {
        "output": output,
        "outputs": [
            {"id": "comparison-selection-store", "property": "data"},
            {"id": "comparison-modal-tabs", "property": "value"},
        ],
        "inputs": [
            {"id": '{"ticker":["ALL"],"type":"comparison-row"}', "property": "n_clicks", "value": []},
            {"id": '{"ticker":["ALL"],"type":"compare-add"}', "property": "n_clicks", "value": [1]},
            {"id": '{"ticker":["ALL"],"type":"compare-remove"}', "property": "n_clicks", "value": []},
            {"id": "compare-clear-button", "property": "n_clicks", "value": 0},
            {"id": "compare-close-button", "property": "n_clicks", "value": 0},
        ],
        "state": [{"id": "comparison-selection-store", "property": "data", "value": []}],
        "changedPropIds": ['{"ticker":"PRE","type":"compare-add"}.n_clicks'],
    }

    response = client.post("/_dash-update-component", json=payload)

    assert response.status_code == 200
    assert response.json["response"]["comparison-selection-store"]["data"] == ["PRE"]
    assert response.json["response"]["comparison-modal-tabs"]["value"] == COMPARE_TAB


def test_dash_pattern_zero_click_does_not_select_ticker():
    client = app.server.test_client()
    output = _callback_output_key("comparison-selection-store.data", "comparison-modal-tabs.value")
    payload = {
        "output": output,
        "outputs": [
            {"id": "comparison-selection-store", "property": "data"},
            {"id": "comparison-modal-tabs", "property": "value"},
        ],
        "inputs": [
            {"id": '{"ticker":["ALL"],"type":"comparison-row"}', "property": "n_clicks", "value": []},
            {"id": '{"ticker":["ALL"],"type":"compare-add"}', "property": "n_clicks", "value": [0]},
            {"id": '{"ticker":["ALL"],"type":"compare-remove"}', "property": "n_clicks", "value": []},
            {"id": "compare-clear-button", "property": "n_clicks", "value": 0},
            {"id": "compare-close-button", "property": "n_clicks", "value": 0},
        ],
        "state": [{"id": "comparison-selection-store", "property": "data", "value": ["PRE"]}],
        "changedPropIds": ['{"ticker":"RBW","type":"compare-add"}.n_clicks'],
    }

    response = client.post("/_dash-update-component", json=payload)

    assert response.status_code == 200
    assert response.json["response"] == {}


def test_modal_frame_callback_survives_repeated_tab_switching():
    client = app.server.test_client()
    output = _callback_output_key(
        "relative-comparison-modal.className",
        "comparison-main-panel.children",
        "comparison-footer-panel.children",
        "comparison-side-tools.style",
    )
    comparison_payload = _build_comparison_payload(
        [
            {"Ticker": "PRE", "Company": "Pensana", "Score": 7.8, "Tech Score": 8, "Commercial Score": 6, "Strategic Score": 7},
            {"Ticker": "RBW", "Company": "Rainbow Rare Earths", "Score": 6.8, "Tech Score": 6, "Commercial Score": 5, "Strategic Score": 8},
        ]
    )

    for active_tab in (OVERVIEW_TAB, COMPARE_TAB, OVERVIEW_TAB, COMPARE_TAB, "bad-tab-value"):
        response = client.post(
            "/_dash-update-component",
            json={
                "output": output,
                "outputs": [
                    {"id": "relative-comparison-modal", "property": "className"},
                    {"id": "comparison-main-panel", "property": "children"},
                    {"id": "comparison-footer-panel", "property": "children"},
                    {"id": "comparison-side-tools", "property": "style"},
                ],
                "inputs": [
                    {"id": "comparison-selection-store", "property": "data", "value": ["PRE", "RBW"]},
                    {"id": "comparison-payload-store", "property": "data", "value": comparison_payload},
                    {"id": "comparison-modal-tabs", "property": "value", "value": active_tab},
                    {"id": "comparison-chart-store", "property": "data", "value": {"ticker": "PRE", "points": [], "status": "fallback"}},
                ],
                "state": [],
                "changedPropIds": ["comparison-modal-tabs.value"],
            },
        )
        assert response.status_code == 200
        assert response.json["response"]["relative-comparison-modal"]["className"] == "comparison-modal"


def test_modal_side_panel_callback_survives_noisy_peer_search():
    client = app.server.test_client()
    comparison_payload = _build_comparison_payload(
        [
            {"Ticker": "PRE", "Company": "Pensana", "Commodity": "rare earths NdPr", "Score": 7.8},
            {"Ticker": "RBW", "Company": "Rainbow Rare Earths", "Commodity": "rare earths", "Score": 6.8},
            {"Ticker": "RIO", "Company": "Rio Tinto", "Commodity": "industrial metals", "Score": 5.8},
        ]
    )

    for query in ("r", "rare", "rare ndpr", "rare " * 80):
        response = client.post(
            "/_dash-update-component",
            json={
                "output": "comparison-side-panel.children",
                "outputs": {"id": "comparison-side-panel", "property": "children"},
                "inputs": [
                    {"id": "comparison-selection-store", "property": "data", "value": ["PRE"]},
                    {"id": "comparison-payload-store", "property": "data", "value": comparison_payload},
                    {"id": "compare-peer-search", "property": "value", "value": query},
                    {"id": "comparison-modal-tabs", "property": "value", "value": COMPARE_TAB},
                ],
                "state": [],
                "changedPropIds": ["compare-peer-search.value"],
            },
        )
        assert response.status_code == 200
        assert "comparison-side-panel" in response.json["response"]


def test_dashboard_rows_use_explicit_missing_labels_instead_of_blank_cells():
    rows = build_dashboard_rows(
        [
            {
                "ticker": "MISS",
                "name": "Anglo Asian Mining Plc",
                "exchange": "LSE",
                "commodity_tags": [],
                "score_status": "metadata_only",
                "composite_score": 4.2,
                "fundamental": {"fundamentals": {"drivers": []}, "metrics": {}},
            }
        ]
    )

    row = rows[0]
    assert all(value != "" for value in row.values())
    assert row["Market Cap"] == "Not found"
    assert row["Debt Metric"] == "Not found after fallback"
    assert row["Alias"] == "None"
    assert row["Commodity"] == "Unclassified"


def test_dashboard_rows_render_explicit_market_snapshot_edge_statuses():
    rows = build_dashboard_rows(
        [
            {
                "ticker": "70GD",
                "name": "Antofagasta Plc 5% Cum Prf #1",
                "exchange": "LSE",
                "commodity_tags": ["industrial metals"],
                "score_status": "metadata_only",
                "composite_score": 4.0,
                "fundamental": {
                    "fundamentals": {"drivers": []},
                    "metrics": {
                        "market_cap": None,
                        "shares_outstanding_lfy": None,
                        "field_provenance": {
                            "market_cap": {"status": "not_applicable_preference_share_no_market_cap"},
                            "shares_outstanding": {"status": "not_applicable_preference_share_no_market_cap"},
                        },
                    },
                },
            }
        ]
    )

    assert rows[0]["Market Cap"] == "Not applicable - preference share"
    assert rows[0]["Shares Outstanding"] == "Not applicable - preference share"


def test_dashboard_rows_fill_market_cap_directly_from_snapshot_csv(monkeypatch):
    view_model._market_snapshot_rows.cache_clear()
    monkeypatch.setattr(
        view_model,
        "load_market_snapshot",
        lambda: {
            "AAZ": {
                "ticker": "AAZ",
                "market_cap": 337_310_000,
                "shares_outstanding": 114_340_000,
                "snapshot_status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
                "source_url": "https://example.test/aaz",
                "notes": "csv row",
            }
        },
    )

    rows = build_dashboard_rows(
        [
            {
                "ticker": "AAZ",
                "name": "Anglo Asian Mining Plc",
                "exchange": "LSE",
                "commodity_tags": ["industrial metals"],
                "score_status": "metadata_only",
                "composite_score": 4.2,
                "fundamental": {"fundamentals": {"drivers": []}, "metrics": {}},
            }
        ]
    )

    assert rows[0]["Market Cap"] == "337.3M"
    assert rows[0]["Shares Outstanding"] == "114.3M"
    assert "company_market_snapshot.csv" in rows[0]["Data Notes"]
    view_model._market_snapshot_rows.cache_clear()


def test_dashboard_rows_replace_literal_na_market_cap_from_snapshot_csv(monkeypatch):
    view_model._market_snapshot_rows.cache_clear()


def test_dashboard_rows_fill_price_from_snapshot_when_present(monkeypatch):
    view_model._market_snapshot_rows.cache_clear()
    monkeypatch.setattr(
        view_model,
        "load_market_snapshot",
        lambda: {
            "PX": {
                "ticker": "PX",
                "market_cap": 10_000_000,
                "last_price": 12.5,
                "price_currency": "GBX",
                "shares_outstanding": 80_000_000,
                "snapshot_status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
                "source_url": "https://example.test/px",
                "notes": "csv row",
            }
        },
    )

    rows = build_dashboard_rows(
        [
            {
                "ticker": "PX",
                "name": "Price Test",
                "exchange": "LSE",
                "score_status": "metadata_only",
                "composite_score": 4.0,
                "fundamental": {
                    "fundamentals": {"drivers": []},
                    "metrics": {"last_price": "n/a", "currency": "n/a"},
                },
            }
        ]
    )

    assert rows[0]["Last Price"] == "12.5 GBX"
    view_model._market_snapshot_rows.cache_clear()
    monkeypatch.setattr(
        view_model,
        "load_market_snapshot",
        lambda: {
            "PRE": {
                "ticker": "PRE",
                "market_cap": 358_460_000,
                "shares_outstanding": 353_510_000,
                "snapshot_status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
                "source_url": "https://example.test/pre",
                "notes": "csv row",
            }
        },
    )

    rows = build_dashboard_rows(
        [
            {
                "ticker": "PRE",
                "name": "Pensana",
                "exchange": "LSE",
                "commodity_tags": ["rare earths"],
                "score_status": "metadata_only",
                "composite_score": 4.8,
                "fundamental": {
                    "fundamentals": {"drivers": []},
                    "metrics": {
                        "market_cap": "n/a",
                        "shares_outstanding_lfy": "n/a",
                    },
                },
            }
        ]
    )

    assert rows[0]["Market Cap"] == "358.5M"
    assert rows[0]["Shares Outstanding"] == "353.5M"
    view_model._market_snapshot_rows.cache_clear()


def test_dashboard_rows_match_snapshot_with_london_suffix(monkeypatch):
    view_model._market_snapshot_rows.cache_clear()
    monkeypatch.setattr(
        view_model,
        "load_market_snapshot",
        lambda: {
            "BHP": {
                "ticker": "BHP",
                "market_cap": 200_000_000_000,
                "shares_outstanding": 5_000_000_000,
                "snapshot_status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
                "source_url": "https://example.test/bhp",
                "notes": "csv row",
            }
        },
    )

    rows = build_dashboard_rows(
        [
            {
                "ticker": "BHP.L",
                "name": "BHP Group",
                "exchange": "LSE",
                "commodity_tags": ["industrial metals"],
                "score_status": "metadata_only",
                "composite_score": 4.2,
                "fundamental": {"fundamentals": {"drivers": []}, "metrics": {}},
            }
        ]
    )

    assert rows[0]["Market Cap"] == "200.0B"
    assert rows[0]["Shares Outstanding"] == "5.0B"
    view_model._market_snapshot_rows.cache_clear()


def test_paginated_display_records_are_rehydrated_from_snapshot(monkeypatch):
    view_model._market_snapshot_rows.cache_clear()
    monkeypatch.setattr(
        view_model,
        "load_market_snapshot",
        lambda: {
            "PAGE2": {
                "ticker": "PAGE2",
                "market_cap": 42_500_000,
                "shares_outstanding": 850_000_000,
                "snapshot_status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
                "source_url": "https://example.test/page2",
                "notes": "csv row",
            }
        },
    )
    records = [
        {
            "Ticker": f"P{i}",
            "Company": f"Page Test {i}",
            "Market Cap": "10.0M",
            "Shares Outstanding": "100.0M",
            "Data Notes": "existing",
            "Source": "cache",
        }
        for i in range(25)
    ]
    records.append(
        {
            "Ticker": "PAGE2.L",
            "Company": "Page 2 Company",
            "Market Cap": "n/a",
            "Shares Outstanding": "Not found",
            "Data Notes": "existing",
            "Source": "cache",
        }
    )

    hydrated = hydrate_dashboard_records_from_snapshot(records)

    assert hydrated[0]["Market Cap"] == "10.0M"
    assert hydrated[25]["Market Cap"] == "42.5M"
    assert hydrated[25]["Shares Outstanding"] == "850.0M"
    assert "company_market_snapshot.csv" in hydrated[25]["Data Notes"]
    view_model._market_snapshot_rows.cache_clear()
