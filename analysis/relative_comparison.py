from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data.market_snapshot import normalize_lse_ticker
from data.utils import CONFIG_DIR, get_logger

MAX_COMPARISON_COMPANIES = 4
DEFAULT_OVERRIDE_PATH = CONFIG_DIR / "relative_score_overrides.csv"


@dataclass(frozen=True)
class RelativeCriterion:
    key: str
    label: str
    short_label: str
    description: str


CRITERIA: dict[str, RelativeCriterion] = {
    "grade_deposit_quality": RelativeCriterion(
        key="grade_deposit_quality",
        label="Minerals, grade & deposit quality",
        short_label="Grade & deposit",
        description=(
            "Relative read-through from technical asset score, resource/deposit "
            "benchmark evidence, grade, scale, confidence, accessibility, and processing complexity."
        ),
    ),
    "commodity_price_outlook": RelativeCriterion(
        key="commodity_price_outlook",
        label="Commodity price outlook",
        short_label="Price outlook",
        description=(
            "Relative commodity setup using explicit overrides where available. "
            "Defaults to neutral when no price-outlook evidence has been supplied."
        ),
    ),
    "jurisdiction_political_stability": RelativeCriterion(
        key="jurisdiction_political_stability",
        label="Jurisdiction & political stability",
        short_label="Jurisdiction",
        description=(
            "Relative jurisdiction quality, permitting credibility, rule of law, "
            "infrastructure alignment, and sovereign-risk signal."
        ),
    ),
    "dilution_warrant_overhang": RelativeCriterion(
        key="dilution_warrant_overhang",
        label="Dilution & warrant overhang",
        short_label="Dilution risk",
        description=(
            "Inverse dilution-risk score: higher means lower expected dilution risk, "
            "better cash runway, or stronger funding validation."
        ),
    ),
    "application_strategic_relevance": RelativeCriterion(
        key="application_strategic_relevance",
        label="Application & strategic relevance",
        short_label="Application",
        description=(
            "Relative strategic relevance from downstream depth, magnet-critical exposure, "
            "ex-China supply-chain value, and application tags."
        ),
    ),
}

SCORING_KEY = [
    {
        "score": 5,
        "label": "Best in class",
        "description": "Best relative peer in this selected group on the criterion.",
    },
    {
        "score": 4,
        "label": "Strong",
        "description": "Above-average relative peer evidence.",
    },
    {
        "score": 3,
        "label": "Average",
        "description": "Mid-pack or neutral where evidence is not yet available.",
    },
    {
        "score": 2,
        "label": "Below average",
        "description": "Weaker relative evidence or meaningful uncertainty.",
    },
    {
        "score": 1,
        "label": "Weak",
        "description": "Weakest relative peer evidence or highest unresolved risk.",
    },
]


def _normalise_criterion(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", "and")
    for char in (" ", "-", "/", ",", "(", ")"):
        text = text.replace(char, "_")
    text = "_".join(part for part in text.split("_") if part)
    aliases = {key: key for key in CRITERIA}
    for key, criterion in CRITERIA.items():
        aliases[_normalise_criterion_label(criterion.label)] = key
        aliases[_normalise_criterion_label(criterion.short_label)] = key
    return aliases.get(text, text)


def _normalise_criterion_label(value: str) -> str:
    text = value.strip().lower().replace("&", "and")
    for char in (" ", "-", "/", ",", "(", ")"):
        text = text.replace(char, "_")
    return "_".join(part for part in text.split("_") if part)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in {"", "-", "n/a", "na", "none", "not loaded", "not found"}:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _clamp_score(value: float) -> int:
    return max(1, min(5, int(round(value))))


def load_relative_score_overrides(path: Path | str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """Load optional criterion-level relative score overrides.

    Overrides are intentionally narrow: each row affects one ticker and one
    criterion. Invalid rows are skipped and logged so a bad manual row cannot
    break the dashboard.
    """
    resolved = Path(path) if path is not None else DEFAULT_OVERRIDE_PATH
    if not resolved.is_absolute():
        resolved = CONFIG_DIR.parent / resolved
    if not resolved.exists():
        return {}

    overrides: dict[tuple[str, str], dict[str, Any]] = {}
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = normalize_lse_ticker(row.get("ticker"))
            criterion = _normalise_criterion(row.get("criterion"))
            score = _as_float(row.get("score"))
            if not ticker or criterion not in CRITERIA or score is None or not 1 <= score <= 5:
                get_logger(__name__).warning("Skipping invalid relative score override row: %s", row)
                continue
            overrides[(ticker, criterion)] = {
                "ticker": ticker,
                "criterion": criterion,
                "score": _clamp_score(score),
                "as_of_date": row.get("as_of_date", ""),
                "source": row.get("source", ""),
                "notes": row.get("notes", ""),
            }
    return overrides


def _record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return None


def _score_value(record: dict[str, Any], *keys: str) -> float | None:
    return _as_float(_record_value(record, *keys))


def _component_score(record: dict[str, Any], group: str, component: str) -> float | None:
    breakdown = record.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return None
    group_data = breakdown.get(group)
    if not isinstance(group_data, dict):
        return None
    components = group_data.get("components")
    if not isinstance(components, dict):
        return None
    component_data = components.get(component)
    if isinstance(component_data, dict):
        return _as_float(component_data.get("score"))
    return _as_float(component_data)


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _proxy_value(record: dict[str, Any], criterion: str) -> tuple[float | None, list[str]]:
    if criterion == "grade_deposit_quality":
        value = _average(
            [
                _component_score(record, "workbook_benchmark", "resource_deposit_quality"),
                _score_value(record, "technical_asset_score", "Tech Score"),
                _score_value(record, "benchmark_score", "Benchmark Score"),
            ]
        )
        return value, [] if value is not None else ["No grade/deposit proxy available; neutral score used."]

    if criterion == "commodity_price_outlook":
        value = _score_value(record, "commodity_price_outlook_score", "Commodity Price Outlook Score")
        if value is None:
            return None, ["Commodity outlook not supplied; neutral 3/5 used."]
        return value, []

    if criterion == "jurisdiction_political_stability":
        value = _average(
            [
                _component_score(record, "strategic_supply_chain", "jurisdiction_quality"),
                _score_value(record, "strategic_supply_chain_score", "Strategic Score"),
            ]
        )
        return value, [] if value is not None else ["No jurisdiction proxy available; neutral score used."]

    if criterion == "dilution_warrant_overhang":
        value = _average(
            [
                _component_score(record, "commercial_financial", "cash_runway_or_funding_risk"),
                _component_score(record, "commercial_financial", "offtake_funding_validation"),
                _score_value(record, "commercial_financial_score", "Commercial Score"),
            ]
        )
        return value, [] if value is not None else ["Dilution evidence unavailable; neutral 3/5 used."]

    if criterion == "application_strategic_relevance":
        value = _average(
            [
                _component_score(record, "strategic_supply_chain", "processing_depth"),
                _component_score(record, "strategic_supply_chain", "ex_china_supply_chain_value"),
                _component_score(record, "workbook_benchmark", "strategic_criticality"),
                _score_value(record, "strategic_supply_chain_score", "Strategic Score"),
            ]
        )
        return value, [] if value is not None else ["No application proxy available; neutral score used."]

    return None, ["Criterion proxy unavailable; neutral score used."]


def _relative_scores(values: dict[str, float | None]) -> dict[str, int]:
    present = {ticker: value for ticker, value in values.items() if value is not None}
    if len(present) < 2:
        return {ticker: 3 for ticker in values}
    minimum = min(present.values())
    maximum = max(present.values())
    if minimum == maximum:
        return {ticker: 3 for ticker in values}

    scaled: dict[str, int] = {}
    for ticker, value in values.items():
        if value is None:
            scaled[ticker] = 3
        else:
            scaled[ticker] = _clamp_score(1 + 4 * ((value - minimum) / (maximum - minimum)))
    return scaled


def _company_name(record: dict[str, Any], ticker: str) -> str:
    return str(_record_value(record, "company_name", "Company", "name") or ticker)


def build_relative_comparison(
    selected_tickers: list[str],
    company_payload: dict[str, dict[str, Any]],
    *,
    overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a 1-5 relative scorecard for up to four selected companies.

    The function reads from existing dashboard/hybrid scoring outputs and does
    not mutate the input payload. Scores are relative to the selected peer set,
    not absolute investment-quality ratings.
    """
    overrides = load_relative_score_overrides() if overrides is None else overrides
    normalised_payload = {
        normalised: record
        for key, record in company_payload.items()
        if (normalised := normalize_lse_ticker(key))
    }
    selected: list[str] = []
    for ticker in selected_tickers:
        normalised = normalize_lse_ticker(ticker)
        if normalised and normalised in normalised_payload and normalised not in selected:
            selected.append(normalised)
        if len(selected) == MAX_COMPARISON_COMPANIES:
            break

    records = {ticker: dict(normalised_payload[ticker]) for ticker in selected}
    proxy_values = {
        criterion: {ticker: _proxy_value(record, criterion)[0] for ticker, record in records.items()}
        for criterion in CRITERIA
    }
    scaled_scores = {criterion: _relative_scores(values) for criterion, values in proxy_values.items()}

    companies: list[dict[str, Any]] = []
    for ticker, record in records.items():
        criterion_scores: dict[str, dict[str, Any]] = {}
        for criterion, definition in CRITERIA.items():
            override = overrides.get((ticker, criterion))
            _proxy, proxy_notes = _proxy_value(record, criterion)
            if override:
                score = int(override["score"])
                source = "override"
                notes = [note for note in [override.get("notes"), override.get("source")] if note]
            else:
                score = scaled_scores[criterion][ticker]
                source = "automatic"
                notes = proxy_notes
                if criterion == "commodity_price_outlook" and proxy_values[criterion][ticker] is None:
                    score = 3
                    source = "neutral"
            criterion_scores[criterion] = {
                "score": score,
                "label": definition.label,
                "short_label": definition.short_label,
                "source": source,
                "notes": notes,
            }

        total = sum(item["score"] for item in criterion_scores.values())
        companies.append(
            {
                "ticker": ticker,
                "company_name": _company_name(record, ticker),
                "total_score": total,
                "max_score": len(CRITERIA) * 5,
                "criteria": criterion_scores,
                "composite_score": _score_value(record, "composite_score", "Score"),
                "technical_asset_score": _score_value(record, "technical_asset_score", "Tech Score"),
                "commercial_financial_score": _score_value(record, "commercial_financial_score", "Commercial Score"),
                "strategic_supply_chain_score": _score_value(record, "strategic_supply_chain_score", "Strategic Score"),
                "rating_label": _record_value(record, "rating_label", "Rating") or "Not assessed",
                "market_cap": _record_value(record, "market_cap_display", "Market Cap") or "Not found",
                "data_notes": _record_value(record, "data_notes", "Data Notes") or "None",
                "missing_data_fields": _record_value(record, "missing_data_fields", "Missing Data") or "None",
                "positive_drivers": _record_value(record, "positive_drivers", "Positive Drivers") or "None",
                "negative_drivers": _record_value(record, "negative_drivers", "Negative Drivers") or "None",
            }
        )

    companies.sort(
        key=lambda company: (
            -int(company["total_score"]),
            -float(company["composite_score"] or 0),
            str(company["ticker"]),
        )
    )
    for rank, company in enumerate(companies, start=1):
        company["rank"] = rank

    return {
        "criteria": [criterion.__dict__ for criterion in CRITERIA.values()],
        "companies": companies,
        "scoring_key": SCORING_KEY,
        "max_companies": MAX_COMPARISON_COMPANIES,
        "note": "Scores are relative to the selected peer group and do not replace the dashboard hybrid score.",
    }
