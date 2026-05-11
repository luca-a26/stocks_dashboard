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
            for nested_key in ("technical", "asset", "project", "commercial", "strategic"):
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
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
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


def _component(score: float, reasons: list[str] | None = None, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "score": clamp_score(score),
        "reason_codes": reasons or [],
        "missing_data_fields": missing or [],
    }


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
    groups = {
        "technical_asset": technical,
        "commercial_financial": commercial,
        "strategic_supply_chain": strategic,
    }
    reasons, missing = _collect_component_metadata(groups)
    raw_composite = _weighted_score(
        {
            "technical_asset_score": technical["score"],
            "commercial_financial_score": commercial["score"],
            "strategic_supply_chain_score": strategic["score"],
        },
        SCORING_CONFIG.hybrid_weights,
    )
    gated_score, stage_gates = _stage_gates(raw_composite, metadata, metrics)
    if stage_gates:
        reasons.extend(gate["reason"] for gate in stage_gates)
    status = _derive_status(metadata, metrics, missing, score_status)
    confidence = _data_quality_score(metadata, metrics, missing, status)
    unique_reasons = sorted(dict.fromkeys(reasons))

    return {
        "composite_score": gated_score,
        "raw_composite_score": raw_composite,
        "technical_asset_score": technical["score"],
        "commercial_financial_score": commercial["score"],
        "strategic_supply_chain_score": strategic["score"],
        "scoring_confidence": confidence,
        "data_quality_score": confidence,
        "score_status": status,
        "rating_label": rating_label(gated_score),
        "score_breakdown": {
            "technical_asset": technical,
            "commercial_financial": commercial,
            "strategic_supply_chain": strategic,
        },
        "missing_data_fields": missing,
        "applied_stage_gates": stage_gates,
        "reason_codes": unique_reasons,
        "explanation_bullets": unique_reasons,
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
        "scoring_confidence": 3.0 if not verified_technical else 4.5,
        "data_quality_score": 3.0 if not verified_technical else 4.5,
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
    }
