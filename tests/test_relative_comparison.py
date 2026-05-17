from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from analysis.relative_comparison import (
    CRITERIA,
    MAX_COMPARISON_COMPANIES,
    build_relative_comparison,
    load_relative_score_overrides,
)


def _payload() -> dict[str, dict]:
    return {
        "LOW": {
            "ticker": "LOW",
            "company_name": "Low Grade Plc",
            "Tech Score": 2,
            "Commercial Score": 2,
            "Strategic Score": 3,
            "Score": 4,
        },
        "MID": {
            "ticker": "MID",
            "company_name": "Mid Grade Plc",
            "Tech Score": 5,
            "Commercial Score": 5,
            "Strategic Score": 5,
            "Score": 5,
        },
        "HIGH": {
            "ticker": "HIGH",
            "company_name": "High Grade Plc",
            "Tech Score": 8,
            "Commercial Score": 8,
            "Strategic Score": 8,
            "Score": 8,
        },
    }


def test_relative_scores_scale_one_to_five_across_peer_group():
    comparison = build_relative_comparison(["LOW", "MID", "HIGH"], _payload(), overrides={})
    by_ticker = {company["ticker"]: company for company in comparison["companies"]}

    assert by_ticker["LOW"]["criteria"]["grade_deposit_quality"]["score"] == 1
    assert by_ticker["MID"]["criteria"]["grade_deposit_quality"]["score"] == 3
    assert by_ticker["HIGH"]["criteria"]["grade_deposit_quality"]["score"] == 5


def test_relative_totals_are_equal_weighted_out_of_25():
    overrides = {
        ("LOW", criterion): {"score": 4, "source": "test", "notes": "fixed"}
        for criterion in CRITERIA
    }

    comparison = build_relative_comparison(["LOW"], _payload(), overrides=overrides)
    company = comparison["companies"][0]

    assert company["total_score"] == 20
    assert company["max_score"] == 25


def test_dilution_score_is_inverse_higher_means_lower_risk():
    comparison = build_relative_comparison(["LOW", "HIGH"], _payload(), overrides={})
    by_ticker = {company["ticker"]: company for company in comparison["companies"]}

    assert by_ticker["HIGH"]["criteria"]["dilution_warrant_overhang"]["score"] == 5
    assert by_ticker["LOW"]["criteria"]["dilution_warrant_overhang"]["score"] == 1


def test_missing_commodity_outlook_uses_neutral_three_with_note():
    comparison = build_relative_comparison(["LOW", "HIGH"], _payload(), overrides={})
    low = next(company for company in comparison["companies"] if company["ticker"] == "LOW")
    criterion = low["criteria"]["commodity_price_outlook"]

    assert criterion["score"] == 3
    assert criterion["source"] == "neutral"
    assert "neutral 3/5" in criterion["notes"][0]


def test_overrides_replace_automatic_criterion_scores():
    overrides = {
        ("LOW", "grade_deposit_quality"): {
            "score": 5,
            "source": "analyst note",
            "notes": "manual peer adjustment",
        }
    }

    comparison = build_relative_comparison(["LOW", "HIGH"], _payload(), overrides=overrides)
    low = next(company for company in comparison["companies"] if company["ticker"] == "LOW")

    assert low["criteria"]["grade_deposit_quality"]["score"] == 5
    assert low["criteria"]["grade_deposit_quality"]["source"] == "override"


def test_comparison_group_is_limited_to_four_companies():
    payload = {f"T{i}": {"ticker": f"T{i}", "company_name": f"Company {i}", "Score": i} for i in range(6)}

    comparison = build_relative_comparison(list(payload), payload, overrides={})

    assert len(comparison["companies"]) == MAX_COMPARISON_COMPANIES


def test_relative_comparison_does_not_mutate_hybrid_payload():
    payload = _payload()
    original = deepcopy(payload)

    build_relative_comparison(["LOW", "MID", "HIGH"], payload, overrides={})

    assert payload == original


def test_override_loader_accepts_valid_rows():
    path = Path("storage/cache/test_relative_score_overrides.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            "ticker,criterion,score,as_of_date,source,notes\n"
            "low,Grade & deposit,4,2026-05-16,manual,reviewed\n",
            encoding="utf-8",
        )

        overrides = load_relative_score_overrides(path)
    finally:
        path.unlink(missing_ok=True)

    assert overrides[("LOW", "grade_deposit_quality")]["score"] == 4
    assert overrides[("LOW", "grade_deposit_quality")]["source"] == "manual"
