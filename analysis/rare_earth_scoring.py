from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from typing import Any


@dataclass(frozen=True)
class HybridScoringConfig:
    """Weights for the rare-earth hybrid score.

    Scores are always kept on a 0-10 scale. The composite gives the highest
    influence to technical asset evidence, then commercial/financial resilience,
    then strategic supply-chain relevance.
    """

    hybrid_weights: dict[str, float]
    technical_weights: dict[str, float]
    commercial_weights: dict[str, float]
    strategic_weights: dict[str, float]
    benchmark_weights: dict[str, float]


SCORING_CONFIG = HybridScoringConfig(
    hybrid_weights={
        "technical_asset_score": 0.55,
        "commercial_financial_score": 0.25,
        "strategic_supply_chain_score": 0.20,
    },
    technical_weights={
        "resource_scale_grade": 0.18,
        "magnet_basket_quality": 0.18,
        "mineralogy_quality": 0.18,
        "metallurgy_derisking": 0.23,
        "resource_confidence": 0.13,
        "impurity_penalty_profile": 0.10,
    },
    commercial_weights={
        "revenue_quality": 0.20,
        "debt_balance_sheet": 0.20,
        "cash_runway_or_funding_risk": 0.20,
        "study_economics": 0.20,
        "offtake_funding_validation": 0.20,
    },
    strategic_weights={
        "jurisdiction_quality": 0.25,
        "processing_depth": 0.35,
        "ex_china_supply_chain_value": 0.25,
        "esg_permitting_social_licence": 0.15,
    },
    benchmark_weights={
        "resource_deposit_quality": 0.25,
        "economics_valuation": 0.25,
        "revenue_downstream_integration": 0.20,
        "production_development": 0.15,
        "strategic_criticality": 0.15,
    },
)


CORE_TECHNICAL_FIELDS = {
    "treo_grade_pct",
    "resource_tonnage_mt",
    "contained_treo_tonnes",
    "contained_ndpr_tonnes",
    "ndpr_pct_of_treo",
    "mineralogy",
    "metallurgical_testwork",
    "recovery_pct",
    "concentrate_grade_pct",
    "resource_category",
    "study_stage",
}

ALIGNED_JURISDICTION_TERMS = {
    "australia",
    "botswana",
    "canada",
    "european union",
    "finland",
    "france",
    "germany",
    "namibia",
    "norway",
    "south africa",
    "sweden",
    "united kingdom",
    "united states",
}


def clamp_score(value: float) -> float:
    return round(min(max(float(value), 0.0), 10.0), 2)


def rating_label(score: float) -> str:
    if score >= 7.5:
        return "High-quality / advanced"
    if score >= 6.0:
        return "Strong watchlist"
    if score >= 4.5:
        return "Developing opportunity"
    if score >= 3.0:
        return "Early / speculative"
    return "Low confidence / insufficient evidence"


def _normalise_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def _sources(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for source in (metrics or {}, metadata or {}):
        if isinstance(source, dict):
            sources.append(source)
            for nested_key in (
                "technical",
                "asset",
                "project",
                "commercial",
                "strategic",
                "resource",
                "valuation",
                "production",
                "benchmarks",
                "benchmark",
                "sector_benchmarks",
            ):
                nested = source.get(nested_key)
                if isinstance(nested, dict):
                    sources.append(nested)
    return sources


def _get(sources: list[dict[str, Any]], *keys: str) -> Any:
    key_options = {key for key in keys}
    key_options.update(_normalise_key(key) for key in keys)
    for source in sources:
        lowered = {_normalise_key(str(key)): value for key, value in source.items()}
        for key in key_options:
            if key in source and _present(source[key]):
                return source[key]
            normalised = _normalise_key(key)
            if normalised in lowered and _present(lowered[normalised]):
                return lowered[normalised]
    return None


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "n/a", "na", "none", "unknown", "-"}
    if isinstance(value, float):
        return not isnan(value)
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _as_float(value: Any) -> float | None:
    if not _present(value):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if isnan(number) else number
    text = str(value).replace(",", "").replace("%", "").strip().lower()
    text = text.replace("£", "").replace("$", "").replace("€", "").replace("gbp", "").replace("usd", "").replace("eur", "")
    multipliers = (
        ("billion", 1_000_000_000.0),
        ("bn", 1_000_000_000.0),
        (" b", 1_000_000_000.0),
        ("million", 1_000_000.0),
        (" m", 1_000_000.0),
        ("m", 1_000_000.0),
        ("k", 1_000.0),
    )
    multiplier = 1.0
    for suffix, factor in multipliers:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _as_bool(value: Any) -> bool | None:
    if not _present(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1", "available", "complete", "completed", "published"}:
        return True
    if text in {"no", "n", "false", "0", "unavailable", "not available", "none"}:
        return False
    return None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _haystack(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> str:
    parts: list[str] = []
    for source in _sources(metadata, metrics):
        for value in source.values():
            if isinstance(value, (str, int, float, list, tuple)):
                parts.append(_text(value))
    return " ".join(parts).lower()


def _weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    return clamp_score(sum(clamp_score(scores[key]) * weights[key] for key in weights))


def _component(score: float, reasons: list[str] | None = None, missing: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    component = {
        "score": clamp_score(score),
        "reason_codes": reasons or [],
        "missing_data_fields": missing or [],
    }
    component.update(extra)
    return component


def _first_float(sources: list[dict[str, Any]], *keys: str) -> float | None:
    return _as_float(_get(sources, *keys))


def _benchmark_keys(prefix: str, field: str) -> tuple[str, ...]:
    return (
        f"{prefix}_{field}",
        f"sector_{prefix}_{field}",
        f"benchmark_{prefix}_{field}",
        f"{field}_{prefix}",
        f"sector_{field}_{prefix}",
    )


def _benchmark_relative_component(
    sources: list[dict[str, Any]],
    value_keys: tuple[str, ...],
    median_field: str,
    label: str,
    missing_field: str,
) -> dict[str, Any]:
    """Score one workbook-style numeric factor against sector benchmarks.

    The workbook model uses median-relative scoring to avoid letting a single
    mining outlier dominate. This keeps the same idea on the dashboard's 0-10
    scale and treats populated-but-unbenchmarked values as modest evidence.
    """
    value = _first_float(sources, *value_keys)
    if value is None:
        return _component(5.0, [], [missing_field], has_evidence=False)

    median = _first_float(sources, *_benchmark_keys("median", median_field))
    average = _first_float(sources, *_benchmark_keys("average", median_field), *_benchmark_keys("avg", median_field))
    benchmark = median if median not in (None, 0) else average
    if benchmark not in (None, 0):
        score_100 = 50 + 50 * ((value - benchmark) / abs(benchmark))
        score = clamp_score(max(0.0, min(100.0, score_100)) / 10.0)
        if value >= benchmark * 1.15:
            reason = f"Above-median {label}"
        elif value <= benchmark * 0.85:
            reason = f"Below-median {label}"
        else:
            reason = f"Near-median {label}"
        return _component(score, [reason], [], has_evidence=True)

    return _component(6.0, [f"{label} populated; benchmark unavailable"], [], has_evidence=True)


def _weighted_available_score(components: dict[str, dict[str, Any]], weights: dict[str, float], default: float = 5.0) -> float:
    available = {key: value for key, value in components.items() if value.get("has_evidence")}
    if not available:
        return clamp_score(default)
    total_weight = sum(weights.get(key, 0.0) for key in available)
    if total_weight <= 0:
        return clamp_score(default)
    return clamp_score(sum(value["score"] * weights[key] for key, value in available.items()) / total_weight)


def _category_result(
    components: dict[str, dict[str, Any]],
    weights: dict[str, float],
    *,
    default: float = 5.0,
) -> dict[str, Any]:
    score = _weighted_available_score(components, weights, default=default)
    reasons: list[str] = []
    missing: list[str] = []
    evidence = 0
    for component in components.values():
        reasons.extend(component.get("reason_codes", []))
        missing.extend(component.get("missing_data_fields", []))
        evidence += 1 if component.get("has_evidence") else 0
    return {
        "score": score,
        "components": components,
        "reason_codes": sorted(dict.fromkeys(reasons)),
        "missing_data_fields": sorted(dict.fromkeys(missing)),
        "has_evidence": evidence > 0,
        "evidence_count": evidence,
        "factor_count": len(components),
    }


def _blend_when_evidenced(base: float, benchmark_category: dict[str, Any], weight: float) -> float:
    if not benchmark_category.get("has_evidence"):
        return clamp_score(base)
    return clamp_score((base * (1 - weight)) + (benchmark_category["score"] * weight))


def _confidence_level(score: float) -> str:
    if score >= 7.5:
        return "High"
    if score >= 4.5:
        return "Medium"
    return "Low"


def _defined_resource(sources: list[dict[str, Any]]) -> bool:
    explicit = _as_bool(_get(sources, "defined_resource", "mineral_resource_defined"))
    if explicit is not None:
        return explicit
    category = str(_get(sources, "resource_category", "resource_confidence") or "").lower()
    if any(term in category for term in ("reserve", "measured", "indicated", "inferred")):
        return True
    return any(
        _as_float(_get(sources, field)) is not None
        for field in ("resource_tonnage_mt", "contained_treo_tonnes", "contained_ndpr_tonnes")
    )


def _has_study(sources: list[dict[str, Any]]) -> bool:
    stage = str(_get(sources, "study_stage", "study_level") or "").lower()
    return any(term in stage for term in ("scoping", "pea", "pfs", "dfs", "bfs", "feasibility"))


def _has_development_route(sources: list[dict[str, Any]], text: str) -> bool:
    bool_fields = (
        "offtake_agreement",
        "strategic_investor",
        "government_grant",
        "funding_package",
        "development_route",
        "permitted",
    )
    return any(_as_bool(_get(sources, field)) is True for field in bool_fields) or any(
        term in text for term in ("offtake", "grant", "strategic investor", "funded", "permitted", "producer")
    )


def _is_downstream_or_processor(text: str) -> bool:
    return any(
        term in text
        for term in (
            "processor",
            "processing",
            "separation",
            "separated oxide",
            "metal",
            "alloy",
            "magnet",
            "recycler",
            "recycling",
        )
    )


def _is_producer_or_advanced(text: str) -> bool:
    return any(term in text for term in ("producer", "production", "operations", "operating", "permitted"))


def _resource_scale_grade(sources: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    missing: list[str] = []
    score = 5.0

    if _defined_resource(sources):
        score += 0.8
        reasons.append("Defined JORC/NI 43-101 resource")
    else:
        missing.append("defined_resource")

    treo = _as_float(_get(sources, "treo_grade_pct", "treo_grade"))
    if treo is None:
        missing.append("treo_grade_pct")
    elif treo >= 5:
        score += 1.8
        reasons.append("High TREO grade")
    elif treo >= 2:
        score += 1.2
        reasons.append("Solid TREO grade")
    elif treo > 0:
        score += 0.5
        reasons.append("TREO grade available")

    tonnage = _as_float(_get(sources, "resource_tonnage_mt", "resource_tonnes_mt"))
    if tonnage is None:
        missing.append("resource_tonnage_mt")
    elif tonnage >= 100:
        score += 1.0
        reasons.append("Large resource tonnage")
    elif tonnage >= 10:
        score += 0.5
        reasons.append("Resource tonnage available")

    contained_treo = _as_float(_get(sources, "contained_treo_tonnes"))
    if contained_treo is None:
        missing.append("contained_treo_tonnes")
    elif contained_treo >= 250_000:
        score += 1.0
        reasons.append("Meaningful contained TREO")
    elif contained_treo > 0:
        score += 0.4

    contained_ndpr = _as_float(_get(sources, "contained_ndpr_tonnes"))
    if contained_ndpr is None:
        missing.append("contained_ndpr_tonnes")
    elif contained_ndpr >= 30_000:
        score += 1.0
        reasons.append("Meaningful contained NdPr")
    elif contained_ndpr > 0:
        score += 0.4

    mine_life = _as_float(_get(sources, "mine_life_years"))
    if mine_life is None:
        missing.append("mine_life_years")
    elif mine_life >= 15:
        score += 0.5
        reasons.append("Long mine-life potential")

    return _component(score, reasons, missing)


def _magnet_basket_quality(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    reasons: list[str] = []
    missing: list[str] = []
    score = 5.0

    ndpr_pct = _as_float(_get(sources, "ndpr_pct_of_treo", "ndpr_pct", "magnet_ree_pct"))
    if ndpr_pct is None:
        missing.append("ndpr_pct_of_treo")
        if "ndpr" in text:
            score += 0.8
            reasons.append("NdPr exposure present")
    elif ndpr_pct >= 25:
        score += 2.0
        reasons.append("Strong NdPr exposure")
    elif ndpr_pct >= 15:
        score += 1.2
        reasons.append("NdPr-rich basket")
    elif ndpr_pct > 0:
        score += 0.5
        reasons.append("NdPr exposure quantified")

    hree_terms = ("hree", "heavy rare earth", "dysprosium", "terbium", " dy", " tb")
    if any(term in text for term in hree_terms) or _as_bool(_get(sources, "hree_exposure")) is True:
        score += 1.5
        reasons.append("HREE exposure present")
    else:
        missing.append("hree_dy_tb_exposure")

    return _component(score, reasons, missing)


def _mineralogy_quality(sources: list[dict[str, Any]]) -> dict[str, Any]:
    mineralogy = str(_get(sources, "mineralogy", "host_minerals") or "").lower()
    if not mineralogy:
        return _component(5.0, [], ["mineralogy"])

    score = 5.0
    reasons: list[str] = []
    if any(term in mineralogy for term in ("monazite", "bastnaesite", "xenotime", "ionic clay")):
        score += 1.5
        reasons.append("Commercially understood mineralogy")
    if any(term in mineralogy for term in ("eudialyte", "steenstrupine", "complex", "refractory")):
        score -= 1.5
        reasons.append("Complex mineralogy flagged")
    return _component(score, reasons, [])


def _metallurgy_derisking(sources: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    missing: list[str] = []
    score = 5.0

    testwork = _as_bool(_get(sources, "metallurgical_testwork", "met_testwork"))
    recovery = _as_float(_get(sources, "recovery_pct", "metallurgical_recovery_pct"))
    concentrate_grade = _as_float(_get(sources, "concentrate_grade_pct"))
    flowsheet = _as_bool(_get(sources, "flowsheet_validated"))
    pilot = _as_bool(_get(sources, "pilot_work", "pilot_plant"))
    variability = _as_bool(_get(sources, "variability_testing"))

    if testwork is True:
        score += 1.0
        reasons.append("Metallurgical testwork published")
    elif testwork is False:
        score -= 1.0
        reasons.append("Metallurgical recovery data unavailable")
    else:
        missing.append("metallurgical_testwork")

    if recovery is None:
        missing.append("recovery_pct")
    elif recovery >= 80:
        score += 1.8
        reasons.append("Strong recovery data")
    elif recovery >= 60:
        score += 1.0
        reasons.append("Recovery data available")
    elif recovery > 0:
        score += 0.2
        reasons.append("Low recovery data")

    if concentrate_grade is None:
        missing.append("concentrate_grade_pct")
    elif concentrate_grade >= 40:
        score += 1.0
        reasons.append("High concentrate grade")
    elif concentrate_grade >= 20:
        score += 0.6
        reasons.append("Concentrate grade available")

    if flowsheet is True:
        score += 0.8
        reasons.append("Flowsheet validation present")
    else:
        missing.append("flowsheet_validated")
    if pilot is True:
        score += 0.8
        reasons.append("Pilot work completed")
    if variability is True:
        score += 0.4
        reasons.append("Variability testing present")

    return _component(score, reasons, missing)


def _resource_confidence(sources: list[dict[str, Any]]) -> dict[str, Any]:
    category = str(_get(sources, "resource_category", "resource_confidence") or "").lower()
    if not category:
        return _component(3.5, ["No defined resource"], ["resource_category"])
    if "reserve" in category:
        return _component(9.0, ["Reserve-level confidence"], [])
    if "measured" in category:
        return _component(8.0, ["Measured resource confidence"], [])
    if "indicated" in category:
        return _component(7.0, ["Indicated resource confidence"], [])
    if "inferred" in category:
        return _component(5.5, ["Inferred resource confidence"], [])
    if "exploration target" in category:
        return _component(4.5, ["Exploration target only"], [])
    return _component(4.0, ["Resource confidence unclear"], ["resource_category"])


def _impurity_penalty_profile(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    impurity_profile = str(_get(sources, "impurity_profile", "impurities") or "").lower()
    thorium = _as_float(_get(sources, "thorium_ppm"))
    uranium = _as_float(_get(sources, "uranium_ppm"))
    acid_gangue = _as_bool(_get(sources, "acid_consuming_gangue"))

    if not impurity_profile and thorium is None and uranium is None and acid_gangue is None:
        return _component(5.0, ["Impurity data unclear"], ["impurity_profile"])

    score = 7.0
    reasons: list[str] = []
    if any(term in impurity_profile or term in text for term in ("low thorium", "low uranium", "clean impurity")):
        score += 1.0
        reasons.append("Clean impurity profile indicated")
    if any(term in impurity_profile or term in text for term in ("high thorium", "high uranium", "radionuclide", "radioactivity")):
        score -= 2.0
        reasons.append("Radioactive impurity handling risk")
    if thorium is not None and thorium > 1000:
        score -= 1.2
        reasons.append("High thorium flagged")
    if uranium is not None and uranium > 200:
        score -= 1.0
        reasons.append("High uranium flagged")
    if acid_gangue is True:
        score -= 1.0
        reasons.append("Acid-consuming gangue flagged")

    return _component(score, reasons, [])


def technical_asset_score(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> dict[str, Any]:
    sources = _sources(metadata, metrics)
    text = _haystack(metadata, metrics)
    components = {
        "resource_scale_grade": _resource_scale_grade(sources),
        "magnet_basket_quality": _magnet_basket_quality(sources, text),
        "mineralogy_quality": _mineralogy_quality(sources),
        "metallurgy_derisking": _metallurgy_derisking(sources),
        "resource_confidence": _resource_confidence(sources),
        "impurity_penalty_profile": _impurity_penalty_profile(sources, text),
    }
    return {
        "score": _weighted_score({key: value["score"] for key, value in components.items()}, SCORING_CONFIG.technical_weights),
        "components": components,
    }


def _revenue_quality(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    revenue = _as_float(_get(sources, "revenue_lfy", "revenue"))
    if revenue is None:
        return _component(5.0, ["Revenue data unavailable"], ["revenue_lfy"])

    is_ree_relevant = any(term in text for term in ("rare earth", "ndpr", "hree", "processor", "recycling", "magnet"))
    score = 5.0
    if revenue > 20_000_000:
        score = 8.0 if is_ree_relevant else 7.0
        reasons = ["REE-relevant revenue available" if is_ree_relevant else "Revenue-generating (>20M LFY)"]
    elif revenue > 0:
        score = 6.5 if is_ree_relevant else 6.0
        reasons = ["Revenue-generating"]
    else:
        score = 5.0
        reasons = ["Pre-revenue developer not penalised heavily"]
    return _component(score, reasons, [])


def _debt_balance_sheet(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    debt = _as_float(_get(sources, "long_term_debt_to_capital_pct", "net_debt_to_equity_pct"))
    if debt is None:
        return _component(5.0, ["Debt data unavailable"], ["debt_metric"])
    if debt == 0:
        return _component(8.0, ["No LSE-reported debt burden"], [])
    if debt <= 25:
        return _component(7.0, ["Moderate LSE-reported debt burden"], [])
    if debt >= 50:
        stage_penalty = 0.5 if "exploration" in text or "development" in text else 0.0
        return _component(3.5 - stage_penalty, ["High LSE-reported debt burden"], [])
    return _component(5.5, ["Debt burden in watch range"], [])


def _cash_runway_or_funding_risk(sources: list[dict[str, Any]]) -> dict[str, Any]:
    runway = _as_float(_get(sources, "cash_runway_months"))
    funding_risk = str(_get(sources, "funding_risk") or "").lower()
    if runway is None and not funding_risk:
        return _component(5.0, ["Cash runway data unavailable"], ["cash_runway_months"])
    if runway is not None:
        if runway >= 24:
            return _component(8.0, ["Strong cash runway"], [])
        if runway >= 12:
            return _component(7.0, ["Adequate cash runway"], [])
        if runway >= 6:
            return _component(5.5, ["Short but usable cash runway"], [])
        return _component(3.0, ["Funding runway risk"], [])
    if "low" in funding_risk:
        return _component(7.0, ["Low funding risk indicated"], [])
    if "high" in funding_risk:
        return _component(3.0, ["Funding risk flagged"], [])
    return _component(5.0, ["Funding risk unclear"], ["cash_runway_months"])


def _study_economics(sources: list[dict[str, Any]]) -> dict[str, Any]:
    study = str(_get(sources, "study_stage", "study_level") or "").lower()
    if not study:
        return _component(5.0, ["No published study economics"], ["study_stage"])
    if any(term in study for term in ("dfs", "bfs", "definitive", "bankable")):
        return _component(8.5, ["DFS/BFS economics published"], [])
    if "pfs" in study or "pre-feasibility" in study:
        return _component(7.5, ["PFS economics published"], [])
    if "pea" in study or "scoping" in study:
        return _component(6.5, ["Scoping/PEA economics published"], [])
    return _component(5.0, ["Study economics unclear"], ["study_stage"])


def _offtake_funding_validation(sources: list[dict[str, Any]]) -> dict[str, Any]:
    score = 5.0
    reasons: list[str] = []
    missing: list[str] = []
    signals = {
        "offtake_agreement": "Offtake agreement present",
        "strategic_investor": "Strategic investor present",
        "government_grant": "Government grant/support present",
        "funding_package": "Funding package present",
        "development_route": "Development route identified",
    }
    for field, reason in signals.items():
        value = _as_bool(_get(sources, field))
        if value is True:
            score += 0.9
            reasons.append(reason)
        elif value is None:
            missing.append(field)
    if not reasons:
        reasons.append("No funding/offtake validation found")
    return _component(score, reasons, missing)


def commercial_financial_score(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> dict[str, Any]:
    sources = _sources(metadata, metrics)
    text = _haystack(metadata, metrics)
    components = {
        "revenue_quality": _revenue_quality(sources, text),
        "debt_balance_sheet": _debt_balance_sheet(sources, text),
        "cash_runway_or_funding_risk": _cash_runway_or_funding_risk(sources),
        "study_economics": _study_economics(sources),
        "offtake_funding_validation": _offtake_funding_validation(sources),
    }
    return {
        "score": _weighted_score({key: value["score"] for key, value in components.items()}, SCORING_CONFIG.commercial_weights),
        "components": components,
    }


def _jurisdiction_quality(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    explicit = _as_float(_get(sources, "jurisdiction_score"))
    if explicit is not None:
        return _component(explicit, ["Jurisdiction score supplied"], [])
    country = str(_get(sources, "country", "jurisdiction") or "").lower()
    if not country:
        return _component(5.0, ["Jurisdiction data unavailable"], ["country"])
    if any(term in country or term in text for term in ALIGNED_JURISDICTION_TERMS):
        return _component(7.0, ["Aligned mining jurisdiction"], [])
    if "multi-jurisdiction" in country:
        return _component(5.5, ["Multi-jurisdiction exposure"], [])
    return _component(5.0, ["Jurisdiction requires review"], [])


def _processing_depth(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    depth = str(_get(sources, "processing_depth") or "").lower()
    combined = f"{depth} {text}"
    if any(term in combined for term in ("magnet", "metal", "alloy", "recycling", "recycler")):
        return _component(9.0, ["Advanced downstream processing capability"], [])
    if "separated oxide" in combined or "separation" in combined:
        return _component(8.5, ["Separated oxide capability"], [])
    if "carbonate" in combined or "hydroxide" in combined:
        return _component(7.0, ["Mixed rare earth carbonate/hydroxide route"], [])
    if "processor" in combined or "processing" in combined:
        return _component(6.5, ["Processing route present"], [])
    if "concentrate" in combined:
        return _component(5.5, ["Concentrate-only processing route"], [])
    if "explorer" in combined or "exploration" in combined:
        return _component(3.5, ["Exploration asset only"], [])
    return _component(5.0, ["Processing depth unavailable"], ["processing_depth"])


def _ex_china_supply_chain_value(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    explicit = _as_float(_get(sources, "ex_china_supply_chain_score"))
    if explicit is not None:
        return _component(explicit, ["Ex-China score supplied"], [])
    country = str(_get(sources, "country", "jurisdiction") or "").lower()
    is_ree = any(term in text for term in ("rare earth", "ndpr", "hree", "dysprosium", "terbium"))
    is_downstream = _is_downstream_or_processor(text)
    if "china" in country:
        return _component(3.5, ["China-linked supply-chain exposure"], [])
    if is_ree and is_downstream:
        return _component(8.5, ["High ex-China supply-chain value"], [])
    if is_ree:
        return _component(7.0, ["Ex-China rare-earth supply relevance"], [])
    if "critical minerals" in text or "battery" in text:
        return _component(6.0, ["Critical-minerals supply relevance"], [])
    return _component(5.0, ["Ex-China supply-chain value unclear"], ["ex_china_supply_chain_value"])


def _esg_permitting_social_licence(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    permitted = _as_bool(_get(sources, "permitted", "environmental_approval"))
    community_risk = str(_get(sources, "community_risk") or "").lower()
    radioactivity = str(_get(sources, "radioactivity_risk") or "").lower()
    if permitted is None and not community_risk and not radioactivity:
        return _component(5.0, ["ESG/permitting data unavailable"], ["esg_permitting"])
    score = 5.0
    reasons: list[str] = []
    if permitted is True:
        score += 2.0
        reasons.append("Permitting/environmental approval present")
    if "low" in community_risk:
        score += 1.0
        reasons.append("Low community risk indicated")
    if "high" in community_risk:
        score -= 1.5
        reasons.append("Community risk flagged")
    if "high" in radioactivity or "radioactivity" in text or "radionuclide" in text:
        score -= 1.0
        reasons.append("Radioactivity/permitting complexity flagged")
    return _component(score, reasons, [])


def strategic_supply_chain_score(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> dict[str, Any]:
    sources = _sources(metadata, metrics)
    text = _haystack(metadata, metrics)
    components = {
        "jurisdiction_quality": _jurisdiction_quality(sources, text),
        "processing_depth": _processing_depth(sources, text),
        "ex_china_supply_chain_value": _ex_china_supply_chain_value(sources, text),
        "esg_permitting_social_licence": _esg_permitting_social_licence(sources, text),
    }
    return {
        "score": _weighted_score({key: value["score"] for key, value in components.items()}, SCORING_CONFIG.strategic_weights),
        "components": components,
    }


def _resource_confidence_weighted(sources: list[dict[str, Any]]) -> dict[str, Any]:
    weighted_inputs = {
        "proven": (
            1.00,
            ("proven_resource_value", "proven_reserve_value", "proven_ore_reserve_value", "proven_tonnes"),
        ),
        "probable": (
            0.85,
            ("probable_resource_value", "probable_reserve_value", "probable_ore_reserve_value", "probable_tonnes"),
        ),
        "measured": (0.75, ("measured_resource_value", "measured_resource_tonnes", "measured_tonnes")),
        "indicated": (0.55, ("indicated_resource_value", "indicated_resource_tonnes", "indicated_tonnes")),
        "inferred": (0.25, ("inferred_resource_value", "inferred_resource_tonnes", "inferred_tonnes")),
    }
    total = 0.0
    weighted_total = 0.0
    populated: list[str] = []
    for label, (weight, keys) in weighted_inputs.items():
        value = _first_float(sources, *keys)
        if value is None or value <= 0:
            continue
        total += value
        weighted_total += value * weight
        populated.append(label)

    if total > 0:
        score = clamp_score(10 * (weighted_total / total))
        if any(label in populated for label in ("proven", "probable")):
            reason = "Reserve-weighted resource confidence"
        elif "measured" in populated or "indicated" in populated:
            reason = "Measured/indicated resource confidence"
        else:
            reason = "Inferred-resource reliance"
        return _component(score, [reason], [], has_evidence=True)

    fallback = _resource_confidence(sources)
    return _component(
        fallback["score"],
        fallback["reason_codes"],
        fallback["missing_data_fields"],
        has_evidence=not fallback.get("missing_data_fields"),
    )


def _sector_coverage(sources: list[dict[str, Any]], text: str) -> tuple[int, list[str]]:
    explicit = _first_float(sources, "sector_count", "covered_sector_count", "number_of_covered_sectors")
    sectors: list[str] = []
    checks = {
        "Mining": ("mining", "mine", "ore production"),
        "Processing": ("processing", "processor", "concentrate"),
        "Separation": ("separation", "separated oxide", "oxide"),
        "Magnets": ("magnet", "alloy", "metal"),
        "Recycling": ("recycling", "recycler"),
        "Other downstream": ("downstream", "other revenue"),
    }
    for label, terms in checks.items():
        bool_value = _as_bool(_get(sources, f"{_normalise_key(label)}_coverage", f"covers_{_normalise_key(label)}"))
        if bool_value is True or any(term in text for term in terms):
            sectors.append(label)

    if explicit is not None:
        return max(int(explicit), len(sectors)), sectors
    return len(sectors), sectors


def _peer_group(sources: list[dict[str, Any]], text: str) -> str:
    explicit = str(_get(sources, "peer_group", "comparison_group") or "").strip()
    if explicit:
        return explicit
    _, sectors = _sector_coverage(sources, text)
    if sectors:
        return " + ".join(sectors[:3]) + ("+" if len(sectors) > 3 else "")
    role = str(_get(sources, "supply_chain_role", "role") or "").strip()
    if role:
        return role
    stage = str(_get(sources, "stage") or "").strip()
    return stage or "Unclassified"


def _downstream_depth_component(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    magnet_revenue = _first_float(sources, "magnet_revenue", "annual_magnet_revenue", "current_magnet_revenue")
    separation_revenue = _first_float(sources, "separation_revenue", "annual_separation_revenue", "current_separation_revenue")
    processing_revenue = _first_float(sources, "processing_revenue", "annual_processing_revenue", "current_processing_revenue")
    count, sectors = _sector_coverage(sources, text)
    if magnet_revenue and magnet_revenue > 0:
        return _component(9.0, ["Strong magnet revenue exposure"], [], has_evidence=True)
    if separation_revenue and separation_revenue > 0:
        return _component(8.0, ["Separation revenue exposure"], [], has_evidence=True)
    if processing_revenue and processing_revenue > 0:
        return _component(6.5, ["Processing revenue exposure"], [], has_evidence=True)
    if any(sector in sectors for sector in ("Magnets", "Recycling")):
        return _component(8.0, ["Magnet supply-chain exposure"], [], has_evidence=True)
    if count > 0:
        return _component(min(8.0, 4.0 + count), [f"{count} sector coverage areas"], [], has_evidence=True)
    return _component(5.0, [], ["sector_coverage"], has_evidence=False)


def _workbook_resource_deposit_quality(sources: list[dict[str, Any]]) -> dict[str, Any]:
    components = {
        "total_mineral_deposit_value": _benchmark_relative_component(
            sources,
            ("total_mineral_deposit_value", "total_deposit_value", "mineral_deposit_value_total"),
            "total_mineral_deposit_value",
            "total mineral deposit value",
            "total_mineral_deposit_value",
        ),
        "ore_reserve_value": _benchmark_relative_component(
            sources,
            ("ore_reserve_value", "reserve_value", "ore_reserves_value"),
            "ore_reserve_value",
            "ore reserve value",
            "ore_reserve_value",
        ),
        "mineral_resource_value": _benchmark_relative_component(
            sources,
            ("mineral_resource_value", "resource_value", "mineral_resources_value"),
            "mineral_resource_value",
            "mineral resource value",
            "mineral_resource_value",
        ),
        "treo_grade": _benchmark_relative_component(
            sources,
            ("treo_grade_pct", "treo_grade", "treo_content_pct"),
            "treo_grade_pct",
            "TREO grade",
            "treo_grade_pct",
        ),
        "ndpr_content": _benchmark_relative_component(
            sources,
            ("ndpr_content", "contained_ndpr_tonnes", "ndpr_pct_of_treo", "ndpr_pct"),
            "ndpr_content",
            "NdPr content",
            "ndpr_content",
        ),
        "dytb_content": _benchmark_relative_component(
            sources,
            ("dytb_content", "dy_tb_content", "contained_dytb_tonnes", "dytb_pct_of_treo"),
            "dytb_content",
            "DyTb content",
            "dytb_content",
        ),
        "resource_confidence": _resource_confidence_weighted(sources),
    }
    weights = {
        "total_mineral_deposit_value": 0.17,
        "ore_reserve_value": 0.15,
        "mineral_resource_value": 0.15,
        "treo_grade": 0.16,
        "ndpr_content": 0.16,
        "dytb_content": 0.11,
        "resource_confidence": 0.10,
    }
    return _category_result(components, weights)


def _workbook_economics_valuation(sources: list[dict[str, Any]]) -> dict[str, Any]:
    deposit_value = _first_float(sources, "deposit_value", "total_mineral_deposit_value", "project_value")
    contained_treo = _first_float(sources, "contained_treo_tonnes", "contained_reo_tonnes", "treo_tonnes")
    implied_component: dict[str, Any]
    if deposit_value is not None and contained_treo and contained_treo > 0:
        implied_value = deposit_value / contained_treo
        median = _first_float(sources, *_benchmark_keys("median", "value_per_tonne_treo"))
        if median not in (None, 0):
            score = clamp_score(max(0.0, min(100.0, 50 + 50 * ((implied_value - median) / abs(median)))) / 10.0)
            implied_component = _component(score, ["Implied value per tonne TREO benchmarked"], [], has_evidence=True)
        else:
            implied_component = _component(6.0, ["Implied value per tonne TREO calculable"], [], has_evidence=True)
    else:
        implied_component = _component(5.0, [], ["implied_value_per_tonne_treo"], has_evidence=False)

    components = {
        "npv_5": _benchmark_relative_component(sources, ("npv_5", "npv5", "npv_5_pct"), "npv_5", "NPV 5", "npv_5"),
        "npv_8": _benchmark_relative_component(sources, ("npv_8", "npv8", "npv_8_pct"), "npv_8", "NPV 8", "npv_8"),
        "npv_10": _benchmark_relative_component(sources, ("npv_10", "npv10", "npv_10_pct"), "npv_10", "NPV 10", "npv_10"),
        "deposit_value": _benchmark_relative_component(
            sources,
            ("deposit_value", "project_deposit_value", "total_mineral_deposit_value"),
            "deposit_value",
            "deposit value",
            "deposit_value",
        ),
        "annual_mining_output_value": _benchmark_relative_component(
            sources,
            ("annual_mining_output_value", "mining_revenue", "annual_mining_revenue"),
            "annual_mining_output_value",
            "annual mining output value",
            "annual_mining_output_value",
        ),
        "valuation_vs_sector_average": _benchmark_relative_component(
            sources,
            ("total_mineral_deposit_value", "deposit_value", "project_value"),
            "sector_valuation",
            "valuation versus sector",
            "sector_valuation",
        ),
        "implied_value_per_tonne_treo": implied_component,
    }
    weights = {
        "npv_5": 0.15,
        "npv_8": 0.17,
        "npv_10": 0.13,
        "deposit_value": 0.17,
        "annual_mining_output_value": 0.13,
        "valuation_vs_sector_average": 0.13,
        "implied_value_per_tonne_treo": 0.12,
    }
    return _category_result(components, weights)


def _workbook_revenue_downstream_integration(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    count, _ = _sector_coverage(sources, text)
    sector_count = _component(
        min(10.0, 3.5 + count * 1.2) if count else 5.0,
        [f"{count} sector coverage areas"] if count else [],
        [] if count else ["sector_coverage"],
        has_evidence=count > 0,
    )
    components = {
        "mining_revenue": _benchmark_relative_component(
            sources,
            ("mining_revenue", "annual_mining_revenue", "current_mining_revenue"),
            "annual_mining_revenue",
            "mining revenue",
            "mining_revenue",
        ),
        "processing_revenue": _benchmark_relative_component(
            sources,
            ("processing_revenue", "annual_processing_revenue", "current_processing_revenue"),
            "annual_processing_revenue",
            "processing revenue",
            "processing_revenue",
        ),
        "separation_revenue": _benchmark_relative_component(
            sources,
            ("separation_revenue", "annual_separation_revenue", "current_separation_revenue"),
            "annual_separation_revenue",
            "separation revenue",
            "separation_revenue",
        ),
        "magnet_revenue": _benchmark_relative_component(
            sources,
            ("magnet_revenue", "annual_magnet_revenue", "current_magnet_revenue"),
            "annual_magnet_revenue",
            "magnet revenue",
            "magnet_revenue",
        ),
        "other_downstream_revenue": _benchmark_relative_component(
            sources,
            ("other_downstream_revenue", "other_revenue", "downstream_revenue"),
            "other_downstream_revenue",
            "other downstream revenue",
            "other_downstream_revenue",
        ),
        "sector_count": sector_count,
        "downstream_depth": _downstream_depth_component(sources, text),
    }
    weights = {
        "mining_revenue": 0.12,
        "processing_revenue": 0.15,
        "separation_revenue": 0.18,
        "magnet_revenue": 0.20,
        "other_downstream_revenue": 0.10,
        "sector_count": 0.10,
        "downstream_depth": 0.15,
    }
    return _category_result(components, weights)


def _workbook_production_development(sources: list[dict[str, Any]]) -> dict[str, Any]:
    current = _first_float(sources, "current_ore_production", "current_ore_production_2026", "planned_ore_production_2026", "ore_production_2026")
    planned_2027 = _first_float(sources, "planned_ore_production_2027", "ore_production_2027")
    planned_2028 = _first_float(sources, "planned_ore_production_2028", "ore_production_2028")
    if current and current > 0 and planned_2028 is not None:
        growth = (planned_2028 - current) / current
        growth_component = _component(
            clamp_score(5.0 + min(4.0, max(-3.0, growth * 2.0))),
            ["Planned production growth visible"] if growth > 0 else ["Production growth limited"],
            [],
            has_evidence=True,
        )
    else:
        growth_component = _component(5.0, [], ["planned_vs_current_production_growth"], has_evidence=False)

    components = {
        "current_or_2026_ore_production": _benchmark_relative_component(
            sources,
            ("current_ore_production", "current_ore_production_2026", "planned_ore_production_2026", "ore_production_2026"),
            "ore_production_2026",
            "2026 ore production",
            "ore_production_2026",
        ),
        "planned_2027_ore_production": _benchmark_relative_component(
            sources,
            ("planned_ore_production_2027", "ore_production_2027"),
            "ore_production_2027",
            "2027 ore production",
            "ore_production_2027",
        ),
        "planned_2028_ore_production": _benchmark_relative_component(
            sources,
            ("planned_ore_production_2028", "ore_production_2028"),
            "ore_production_2028",
            "2028 ore production",
            "ore_production_2028",
        ),
        "life_of_mine": _benchmark_relative_component(
            sources,
            ("life_of_mine", "life_of_mine_years", "mine_life_years"),
            "life_of_mine",
            "life of mine",
            "life_of_mine",
        ),
        "production_growth": growth_component,
    }
    weights = {
        "current_or_2026_ore_production": 0.25,
        "planned_2027_ore_production": 0.20,
        "planned_2028_ore_production": 0.20,
        "life_of_mine": 0.20,
        "production_growth": 0.15,
    }
    return _category_result(components, weights, default=4.0)


def _workbook_strategic_criticality(sources: list[dict[str, Any]], text: str) -> dict[str, Any]:
    hree_value = _first_float(sources, "hree_content", "heavy_ree_content", "heavy_rare_earth_content")
    hree_component = _component(
        7.5,
        ["Heavy rare earth exposure present"],
        [],
        has_evidence=True,
    ) if hree_value and hree_value > 0 else _component(
        7.0,
        ["HREE exposure present"],
        [],
        has_evidence=True,
    ) if any(term in text for term in ("hree", "heavy rare earth", "dysprosium", "terbium")) else _component(
        5.0,
        [],
        ["hree_content"],
        has_evidence=False,
    )
    magnet_exposure = _downstream_depth_component(sources, text)
    components = {
        "ndpr_exposure": _benchmark_relative_component(
            sources,
            ("ndpr_content", "contained_ndpr_tonnes", "ndpr_pct_of_treo", "ndpr_pct"),
            "ndpr_content",
            "NdPr exposure",
            "ndpr_content",
        ),
        "dytb_exposure": _benchmark_relative_component(
            sources,
            ("dytb_content", "dy_tb_content", "contained_dytb_tonnes", "dytb_pct_of_treo"),
            "dytb_content",
            "DyTb exposure",
            "dytb_content",
        ),
        "heavy_ree_exposure": hree_component,
        "magnet_critical_content": _benchmark_relative_component(
            sources,
            ("magnet_critical_ree_content", "magnet_ree_pct", "ndpr_pct_of_treo"),
            "magnet_critical_ree_content",
            "magnet-critical REE content",
            "magnet_critical_ree_content",
        ),
        "magnet_supply_chain_exposure": magnet_exposure,
    }
    weights = {
        "ndpr_exposure": 0.25,
        "dytb_exposure": 0.20,
        "heavy_ree_exposure": 0.18,
        "magnet_critical_content": 0.17,
        "magnet_supply_chain_exposure": 0.20,
    }
    return _category_result(components, weights)


def workbook_benchmark_score(metadata: dict[str, Any] | None, metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Return the spreadsheet-derived benchmark layer on a 0-10 scale.

    This mirrors the analyst workbook categories while remaining lazy and
    deterministic: if a metric is missing, it is flagged and excluded from the
    weighted category rather than silently scored as zero.
    """
    sources = _sources(metadata, metrics)
    text = _haystack(metadata, metrics)
    categories = {
        "resource_deposit_quality": _workbook_resource_deposit_quality(sources),
        "economics_valuation": _workbook_economics_valuation(sources),
        "revenue_downstream_integration": _workbook_revenue_downstream_integration(sources, text),
        "production_development": _workbook_production_development(sources),
        "strategic_criticality": _workbook_strategic_criticality(sources, text),
    }
    score = _weighted_available_score(categories, SCORING_CONFIG.benchmark_weights, default=5.0)
    factor_count = sum(category["factor_count"] for category in categories.values())
    evidence_count = sum(category["evidence_count"] for category in categories.values())
    completeness = clamp_score((evidence_count / factor_count) * 10 if factor_count else 0)
    reasons: list[str] = []
    missing: list[str] = []
    positive: list[str] = []
    negative: list[str] = []
    for category in categories.values():
        reasons.extend(category["reason_codes"])
        missing.extend(category["missing_data_fields"])
        for component in category["components"].values():
            component_reasons = component.get("reason_codes", [])
            if component.get("score", 5) >= 6:
                positive.extend(component_reasons)
            elif component.get("score", 5) <= 4.5:
                negative.extend(component_reasons)
    if completeness < 4.5:
        negative.append("Low data completeness")
    if missing:
        negative.append("Missing benchmark inputs")

    return {
        "score": score,
        "components": categories,
        "data_completeness_score": completeness,
        "confidence_level": _confidence_level(completeness),
        "suggested_peer_group": _peer_group(sources, text),
        "reason_codes": sorted(dict.fromkeys(reasons)),
        "missing_data_fields": sorted(dict.fromkeys(missing)),
        "top_positive_drivers": list(dict.fromkeys(positive))[:3],
        "top_negative_drivers": list(dict.fromkeys(negative))[:3],
        "has_evidence": evidence_count > 0,
    }


def _collect_component_metadata(groups: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    missing: list[str] = []
    for group in groups.values():
        for component in group.get("components", {}).values():
            reasons.extend(component.get("reason_codes", []))
            missing.extend(component.get("missing_data_fields", []))
    return sorted(dict.fromkeys(reasons)), sorted(dict.fromkeys(missing))


def _stage_gates(
    composite: float,
    metadata: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
) -> tuple[float, list[dict[str, Any]]]:
    sources = _sources(metadata, metrics)
    text = _haystack(metadata, metrics)
    is_downstream = _is_downstream_or_processor(text)
    is_advanced = _is_producer_or_advanced(text)
    gates: list[dict[str, Any]] = []

    def apply(condition: bool, cap: float, reason: str) -> None:
        nonlocal composite
        if not condition:
            return
        gates.append({"cap": cap, "reason": reason})
        if composite > cap:
            composite = min(composite, cap)

    mine_asset_gates_apply = not is_downstream and not is_advanced
    apply(mine_asset_gates_apply and not _defined_resource(sources), 5.5, "No defined resource")
    apply(
        mine_asset_gates_apply and _as_bool(_get(sources, "metallurgical_testwork", "met_testwork")) is not True,
        6.0,
        "No metallurgical testwork",
    )
    apply(mine_asset_gates_apply and _as_float(_get(sources, "recovery_pct", "metallurgical_recovery_pct")) is None, 6.5, "No recovery data")
    apply(mine_asset_gates_apply and not _has_study(sources), 7.0, "No scoping study / PEA / PFS / DFS")
    apply(not is_advanced and not _has_development_route(sources, text), 8.0, "No funding/offtake/development route")
    return clamp_score(composite), gates


def _data_quality_score(
    metadata: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    missing_fields: list[str],
    status: str,
) -> float:
    sources = _sources(metadata, metrics)
    evidence_fields = [
        "market_cap",
        "last_price",
        "fifty_two_week_low",
        "fifty_two_week_high",
        "revenue_lfy",
        "long_term_debt_to_capital_pct",
        "net_debt_to_equity_pct",
        "resource_category",
        "treo_grade_pct",
        "resource_tonnage_mt",
        "metallurgical_testwork",
        "recovery_pct",
        "study_stage",
        "processing_depth",
        "country",
    ]
    present = sum(1 for field in evidence_fields if _present(_get(sources, field)))
    score = 2.0 + (present / len(evidence_fields)) * 8.0
    if status == "metadata_only":
        score = min(score, 4.0)
    if status == "stale":
        score -= 2.0
    if len(missing_fields) > 8:
        score -= 1.0
    return clamp_score(score)


def _derive_status(
    metadata: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    missing_fields: list[str],
    requested_status: str | None,
) -> str:
    if requested_status in {"metadata_only", "stale"}:
        return requested_status
    if not metrics:
        return "metadata_only"
    sources = _sources(metadata, metrics)
    has_market = _present(_get(sources, "market_cap")) or _present(_get(sources, "last_price"))
    has_financial = _present(_get(sources, "revenue_lfy")) or _present(_get(sources, "long_term_debt_to_capital_pct", "net_debt_to_equity_pct"))
    has_technical = any(_present(_get(sources, field)) for field in CORE_TECHNICAL_FIELDS)
    return "full" if has_market and has_financial and has_technical else "partial"


def score_company(
    metadata: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    *,
    score_status: str | None = None,
) -> dict[str, Any]:
    """Return the full rare-earth hybrid score output for one company.

    Missing values are scored neutrally in sub-components, recorded in
    `missing_data_fields`, and reflected in `scoring_confidence`. Stage gates
    cap weakly evidenced mining projects so early names cannot rank as advanced
    projects without resource, metallurgy, study, and development-route evidence.
    """
    metadata = metadata or {}
    metrics = metrics or {}
    technical = technical_asset_score(metadata, metrics)
    commercial = commercial_financial_score(metadata, metrics)
    strategic = strategic_supply_chain_score(metadata, metrics)
    benchmark = workbook_benchmark_score(metadata, metrics)

    benchmark_components = benchmark["components"]
    enhanced_technical = _blend_when_evidenced(technical["score"], benchmark_components["resource_deposit_quality"], 0.30)
    enhanced_technical = _blend_when_evidenced(enhanced_technical, benchmark_components["production_development"], 0.15)
    enhanced_commercial = _blend_when_evidenced(commercial["score"], benchmark_components["economics_valuation"], 0.30)
    enhanced_commercial = _blend_when_evidenced(enhanced_commercial, benchmark_components["revenue_downstream_integration"], 0.25)
    enhanced_strategic = _blend_when_evidenced(strategic["score"], benchmark_components["strategic_criticality"], 0.35)

    groups = {
        "technical_asset": technical,
        "commercial_financial": commercial,
        "strategic_supply_chain": strategic,
    }
    reasons, missing = _collect_component_metadata(groups)
    reasons.extend(benchmark["reason_codes"])
    missing.extend(benchmark["missing_data_fields"])
    if benchmark["has_evidence"]:
        reasons.append("Workbook benchmark scoring layer applied")
    raw_composite = _weighted_score(
        {
            "technical_asset_score": enhanced_technical,
            "commercial_financial_score": enhanced_commercial,
            "strategic_supply_chain_score": enhanced_strategic,
        },
        SCORING_CONFIG.hybrid_weights,
    )
    gated_score, stage_gates = _stage_gates(raw_composite, metadata, metrics)
    if stage_gates:
        reasons.extend(gate["reason"] for gate in stage_gates)
    status = _derive_status(metadata, metrics, missing, score_status)
    confidence = max(_data_quality_score(metadata, metrics, missing, status), benchmark["data_completeness_score"])
    unique_reasons = sorted(dict.fromkeys(reasons))
    unique_missing = sorted(dict.fromkeys(missing))
    top_positive = benchmark["top_positive_drivers"] or [reason for reason in unique_reasons if "unavailable" not in reason.lower()][:3]
    top_negative = benchmark["top_negative_drivers"] or [f"Missing {field}" for field in unique_missing[:3]]

    return {
        "composite_score": gated_score,
        "raw_composite_score": raw_composite,
        "technical_asset_score": enhanced_technical,
        "commercial_financial_score": enhanced_commercial,
        "strategic_supply_chain_score": enhanced_strategic,
        "base_technical_asset_score": technical["score"],
        "base_commercial_financial_score": commercial["score"],
        "base_strategic_supply_chain_score": strategic["score"],
        "benchmark_score": benchmark["score"],
        "benchmark_breakdown": benchmark,
        "scoring_confidence": confidence,
        "data_quality_score": confidence,
        "data_completeness_score": benchmark["data_completeness_score"],
        "confidence_level": benchmark["confidence_level"],
        "suggested_peer_group": benchmark["suggested_peer_group"],
        "score_status": status,
        "rating_label": rating_label(gated_score),
        "score_breakdown": {
            "technical_asset": technical,
            "commercial_financial": commercial,
            "strategic_supply_chain": strategic,
            "workbook_benchmark": benchmark,
        },
        "missing_data_fields": unique_missing,
        "applied_stage_gates": stage_gates,
        "reason_codes": unique_reasons,
        "explanation_bullets": unique_reasons,
        "top_positive_drivers": top_positive[:3],
        "top_negative_drivers": top_negative[:3],
    }


def score_metadata_only(record: dict[str, Any]) -> dict[str, Any]:
    """Lightweight metadata triage aligned to the hybrid framework.

    This deliberately caps metadata-only names at 5.5 unless verified technical
    fields are present, and marks confidence as low.
    """
    score = 4.0
    text = _haystack(record, {})
    priority = str(record.get("priority", "")).lower()
    if priority == "high":
        score += 0.7
    elif priority == "medium":
        score += 0.35
    if any(term in text for term in ("producer", "production", "operations", "developer", "development")):
        score += 0.45
    if _is_downstream_or_processor(text):
        score += 0.55
    if any(term in text for term in ("hree", "heavy rare earth", "dysprosium", "terbium")):
        score += 0.55
    elif any(term in text for term in ("ndpr", "rare earth", "lree")):
        score += 0.35
    if str(record.get("market_cap_tier", "")).lower() in {"large", "mega"}:
        score += 0.25

    verified_technical = any(_present(record.get(field)) for field in CORE_TECHNICAL_FIELDS)
    score = min(score, 5.5 if not verified_technical else 6.5)
    score = clamp_score(score)
    return {
        "composite_score": score,
        "technical_asset_score": min(score, 5.5),
        "commercial_financial_score": 4.0,
        "strategic_supply_chain_score": clamp_score(score + (0.8 if _is_downstream_or_processor(text) else 0.0)),
        "benchmark_score": score,
        "benchmark_breakdown": {},
        "scoring_confidence": 3.0 if not verified_technical else 4.5,
        "data_quality_score": 3.0 if not verified_technical else 4.5,
        "data_completeness_score": 1.5 if not verified_technical else 3.0,
        "confidence_level": "Low",
        "suggested_peer_group": str(record.get("supply_chain_role") or record.get("stage") or "Metadata-only"),
        "score_status": "metadata_only",
        "rating_label": rating_label(score),
        "score_breakdown": {},
        "missing_data_fields": [
            "full_market_data",
            "financial_metrics",
            "technical_asset_fields",
        ],
        "applied_stage_gates": [] if verified_technical else [{"cap": 5.5, "reason": "Metadata-only score cap"}],
        "reason_codes": ["Metadata-only preliminary score", "Load details for full hybrid score"],
        "explanation_bullets": ["Metadata-only preliminary score", "Load details for full hybrid score"],
        "top_positive_drivers": ["Metadata-only preliminary score"],
        "top_negative_drivers": ["Load details for full hybrid score"],
    }
