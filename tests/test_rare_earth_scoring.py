from analysis.rare_earth_scoring import score_company, score_metadata_only


def _strong_technical_metadata():
    return {
        "ticker": "DEV",
        "company_name": "Developer Plc",
        "country": "Australia",
        "commodity_tags": ["rare earths", "NdPr", "HREE"],
        "supply_chain_role": "Mine developer",
        "stage": "Development",
        "technical": {
            "defined_resource": True,
            "resource_category": "Indicated",
            "treo_grade_pct": 4.2,
            "resource_tonnage_mt": 80,
            "contained_treo_tonnes": 600_000,
            "contained_ndpr_tonnes": 90_000,
            "mine_life_years": 18,
            "ndpr_pct_of_treo": 24,
            "mineralogy": "monazite and bastnaesite",
            "metallurgical_testwork": True,
            "recovery_pct": 78,
            "concentrate_grade_pct": 35,
            "flowsheet_validated": True,
            "variability_testing": True,
            "impurity_profile": "low thorium and low uranium",
            "study_stage": "PFS",
            "offtake_agreement": True,
            "development_route": True,
        },
    }


def test_producer_with_strong_revenue_and_low_debt_scores_well():
    metadata = _strong_technical_metadata() | {
        "supply_chain_role": "Producer / developer",
        "stage": "Operations",
    }
    metrics = {
        "market_cap": 500_000_000,
        "last_price": 120,
        "revenue_lfy": 55_000_000,
        "long_term_debt_to_capital_pct": 5,
    }

    scored = score_company(metadata, metrics)

    assert scored["commercial_financial_score"] >= 6.5
    assert scored["composite_score"] >= 6.5
    assert scored["score_status"] == "full"
    assert scored["composite_score"] <= 10


def test_pre_revenue_developer_can_rank_on_strong_technical_asset():
    metadata = _strong_technical_metadata()
    metrics = {"market_cap": 150_000_000, "last_price": 42, "revenue_lfy": 0, "net_debt_to_equity_pct": 0}

    scored = score_company(metadata, metrics)

    assert scored["technical_asset_score"] >= 7
    assert scored["composite_score"] >= 6
    assert "Pre-revenue developer not penalised heavily" in scored["reason_codes"]


def test_early_explorer_without_resource_is_capped():
    metadata = {
        "ticker": "EXP",
        "company_name": "Explorer Plc",
        "country": "Australia",
        "commodity_tags": ["rare earths"],
        "supply_chain_role": "Explorer",
        "stage": "Exploration",
    }

    scored = score_company(metadata, {"market_cap": 25_000_000, "last_price": 3})

    assert scored["composite_score"] <= 5.5
    assert any(gate["reason"] == "No defined resource" for gate in scored["applied_stage_gates"])
    assert "defined_resource" in scored["missing_data_fields"]


def test_processor_recycler_can_score_through_downstream_role_without_mine():
    metadata = {
        "ticker": "REC",
        "company_name": "Recycler Plc",
        "country": "United Kingdom",
        "commodity_tags": ["rare earths", "recycling"],
        "supply_chain_role": "Recycler + magnet metals processor",
        "stage": "Operations",
        "processing_depth": "metals/alloys/magnets/recycling",
        "government_grant": True,
        "development_route": True,
    }
    metrics = {"market_cap": 80_000_000, "last_price": 12, "revenue_lfy": 2_000_000, "long_term_debt_to_capital_pct": 0}

    scored = score_company(metadata, metrics)

    assert scored["strategic_supply_chain_score"] >= 7.5
    assert scored["composite_score"] >= 5
    assert not any(gate["reason"] == "No defined resource" for gate in scored["applied_stage_gates"])


def test_metadata_only_company_is_capped_and_low_confidence():
    scored = score_metadata_only(
        {
            "ticker": "META",
            "company_name": "Metadata Plc",
            "priority": "High",
            "commodity_tags": ["HREE", "NdPr"],
            "supply_chain_role": "Developer",
        }
    )

    assert scored["composite_score"] <= 5.5
    assert scored["score_status"] == "metadata_only"
    assert scored["scoring_confidence"] <= 4


def test_missing_debt_and_revenue_are_neutral_but_reported():
    metadata = _strong_technical_metadata()
    metrics = {"market_cap": 200_000_000, "last_price": 25}

    scored = score_company(metadata, metrics)

    assert scored["score_status"] == "partial"
    assert "revenue_lfy" in scored["missing_data_fields"]
    assert "debt_metric" in scored["missing_data_fields"]
    assert scored["commercial_financial_score"] >= 4


def test_stage_gate_cap_enforcement_limits_high_raw_scores():
    metadata = {
        "ticker": "CAP",
        "company_name": "Capped Plc",
        "country": "Australia",
        "commodity_tags": ["rare earths", "NdPr", "HREE"],
        "supply_chain_role": "Explorer",
        "stage": "Exploration",
        "ndpr_pct_of_treo": 30,
        "government_grant": True,
        "offtake_agreement": True,
    }
    metrics = {"market_cap": 300_000_000, "last_price": 50, "revenue_lfy": 30_000_000, "long_term_debt_to_capital_pct": 0}

    scored = score_company(metadata, metrics)

    assert scored["raw_composite_score"] > scored["composite_score"]
    assert scored["composite_score"] == 5.5


def test_final_scores_are_capped_between_zero_and_ten():
    metadata = _strong_technical_metadata()
    metadata["technical"]["treo_grade_pct"] = 99
    metadata["technical"]["recovery_pct"] = 99
    metrics = {"market_cap": 10_000_000_000, "last_price": 1000, "revenue_lfy": 9_000_000_000, "long_term_debt_to_capital_pct": 0}

    scored = score_company(metadata, metrics)

    assert 0 <= scored["composite_score"] <= 10
    assert 0 <= scored["technical_asset_score"] <= 10
    assert 0 <= scored["commercial_financial_score"] <= 10
    assert 0 <= scored["strategic_supply_chain_score"] <= 10


def test_reason_codes_and_missing_data_are_dashboard_friendly():
    metadata = _strong_technical_metadata()
    metrics = {"market_cap": 100_000_000, "last_price": 20, "revenue_lfy": None}

    scored = score_company(metadata, metrics)

    assert "Strong NdPr exposure" in scored["reason_codes"] or "NdPr-rich basket" in scored["reason_codes"]
    assert "revenue_lfy" in scored["missing_data_fields"]
    assert isinstance(scored["score_breakdown"], dict)
