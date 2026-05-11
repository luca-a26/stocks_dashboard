from dashboard.discovery_view_model import build_catalyst_rows, build_project_rows
from data.discovery import count_by, load_catalysts, load_project_pipeline


def test_project_pipeline_loads_reex_ready_fields():
    projects = load_project_pipeline()
    rows = build_project_rows(projects)

    assert rows
    assert {"Ticker", "REE Class", "Drill Results", "Historic Mine", "Source Confidence"} <= set(rows[0])


def test_catalysts_include_reex_import_workflow():
    rows = build_catalyst_rows(load_catalysts())

    assert any(row["Ticker"] == "REEx" and row["Status"] == "Pending" for row in rows)


def test_count_by_groups_pipeline_fields():
    grouped = count_by(
        [
            {"stage": "Exploration"},
            {"stage": "Exploration"},
            {"stage": "Development"},
        ],
        "stage",
    )

    assert {"label": "Exploration", "count": 2} in grouped
    assert {"label": "Development", "count": 1} in grouped
