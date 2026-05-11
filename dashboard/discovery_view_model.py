from __future__ import annotations

from typing import Any

PROJECT_COLUMNS = [
    "Ticker",
    "Company",
    "Exchange",
    "Project",
    "Commodity Focus",
    "REE Class",
    "Role",
    "Country",
    "Stage",
    "Drill Results",
    "Historic Mine",
    "Source Confidence",
    "Priority",
    "Notes",
]

SUPPLY_CHAIN_COLUMNS = [
    "Segment",
    "Entity",
    "Role",
    "Ranking",
    "Jurisdiction",
    "Exposure",
    "Source",
    "Status",
    "Notes",
]

CATALYST_COLUMNS = [
    "Ticker",
    "Company",
    "Catalyst",
    "Category",
    "Timing",
    "Status",
    "Impact",
    "Source",
    "Owner",
    "Notes",
]


def build_project_rows(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Ticker": item.get("ticker", ""),
            "Company": item.get("company", ""),
            "Exchange": item.get("exchange", ""),
            "Project": item.get("project", ""),
            "Commodity Focus": item.get("commodity_focus", ""),
            "REE Class": item.get("ree_class", ""),
            "Role": item.get("supply_chain_role", ""),
            "Country": item.get("country", ""),
            "Stage": item.get("stage", ""),
            "Drill Results": item.get("drill_results_status", ""),
            "Historic Mine": item.get("historic_mine_flag", ""),
            "Source Confidence": item.get("source_confidence", ""),
            "Priority": item.get("priority", ""),
            "Notes": item.get("notes", ""),
        }
        for item in projects
    ]


def build_supply_chain_rows(rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Segment": item.get("segment", ""),
            "Entity": item.get("entity", ""),
            "Role": item.get("role", ""),
            "Ranking": item.get("ranking", ""),
            "Jurisdiction": item.get("jurisdiction", ""),
            "Exposure": item.get("exposure", ""),
            "Source": item.get("source", ""),
            "Status": item.get("status", ""),
            "Notes": item.get("notes", ""),
        }
        for item in rankings
    ]


def build_catalyst_rows(catalysts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Ticker": item.get("ticker", ""),
            "Company": item.get("company", ""),
            "Catalyst": item.get("catalyst", ""),
            "Category": item.get("category", ""),
            "Timing": item.get("timing", ""),
            "Status": item.get("status", ""),
            "Impact": item.get("impact", ""),
            "Source": item.get("source", ""),
            "Owner": item.get("owner", ""),
            "Notes": item.get("notes", ""),
        }
        for item in catalysts
    ]
