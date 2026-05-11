from __future__ import annotations

from collections import Counter
from typing import Any

from data.utils import CONFIG_DIR, load_yaml

PIPELINE_PATH = CONFIG_DIR / "ree_pipeline.yaml"


def load_discovery_config() -> dict[str, Any]:
    return load_yaml(PIPELINE_PATH)


def load_project_pipeline() -> list[dict[str, Any]]:
    return load_discovery_config().get("project_pipeline", [])


def load_supply_chain_rankings() -> list[dict[str, Any]]:
    return load_discovery_config().get("supply_chain_rankings", [])


def load_catalysts() -> list[dict[str, Any]]:
    return load_discovery_config().get("catalysts", [])


def count_by(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts = Counter(str(item.get(field) or "Unknown") for item in items)
    return [{"label": label, "count": count} for label, count in sorted(counts.items())]


def priority_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("priority") or item.get("impact") or "Unknown") for item in items)
    return dict(counts)
