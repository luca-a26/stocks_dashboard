import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.financial_pipeline import (
    build_company_identity,
    compute_market_cap,
    coverage_audit,
    financial_cache_state,
    normalise_company_financials,
)
from data.market_snapshot import (
    load_market_snapshot,
    normalise_market_snapshot_row,
    normalize_lse_ticker,
    snapshot_is_stale,
)


def test_lse_ticker_normalization_matches_suffixes_and_prefixes():
    assert normalize_lse_ticker("BHP") == "BHP"
    assert normalize_lse_ticker("BHP.L") == "BHP"
    assert normalize_lse_ticker("bhp") == "BHP"
    assert normalize_lse_ticker("LON:BHP") == "BHP"
    assert normalize_lse_ticker("XLON:RIO") == "RIO"


def test_gbpence_price_is_normalized_for_market_cap():
    market_cap, meta = compute_market_cap(247.5, 114_340_000, "GBX")

    assert market_cap == 282_991_500
    assert meta["normalized_price"] == 2.475
    assert meta["normalized_price_currency"] == "GBP"
    assert meta["price_unit"] == "GBp"

    market_cap_from_gbp_unit, meta_from_unit = compute_market_cap(247.5, 114_340_000, "GBP", "GBp")
    assert market_cap_from_gbp_unit == 282_991_500
    assert meta_from_unit["price_unit"] == "GBp"


def test_market_cap_computation_flags_vendor_conflict():
    identity = build_company_identity({"ticker": "AAZ", "exchange": "LSE"})
    metrics = normalise_company_financials(
        identity,
        {
            "lse": {"last_price": 247.5, "currency": "GBX"},
            "yahoo": {"shares_outstanding_lfy": 114_340_000, "market_cap": 10_000_000},
        },
        overrides=[],
    )

    assert metrics["market_cap"] == 282_991_500
    assert "market_cap_computed" in metrics["data_quality_flags"]
    assert "market_cap_vendor_conflict" in metrics["data_quality_flags"]


def test_market_snapshot_loader_normalizes_supplied_schema():
    path = Path("storage/cache/test_market_snapshot_loader.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "Ticker,Company,Market Cap,Market Cap Currency,Market Cap Numeric,Magnitude,Shares in Issue,Status,Primary Source,Snapshot Date,Notes",
                "AAZ,Anglo Asian Mining PLC,£337.31m,GBP,337310000,m,114.34m,found_lse_share_page,https://example.test/aaz,2026-05-12,verified",
            ]
        ),
        encoding="utf-8",
    )

    try:
        rows = load_market_snapshot(path)
    finally:
        path.unlink(missing_ok=True)

    assert rows["AAZ"]["company_id"] == "LSE:AAZ"
    assert rows["AAZ"]["market_cap_native"] == 337_310_000
    assert rows["AAZ"]["market_cap_currency"] == "GBP"
    assert rows["AAZ"]["shares_outstanding"] == 114_340_000
    assert rows["AAZ"]["source_url"] == "https://example.test/aaz"


def test_market_snapshot_numeric_values_parse_common_market_cap_formats():
    cases = [
        ("123456789", 123_456_789),
        ("123,456,789", 123_456_789),
        ("£123.4m", 123_400_000),
        ("£1.23B", 1_230_000_000),
        ("1.23bn", 1_230_000_000),
        ("123.4m", 123_400_000),
    ]

    for raw, expected in cases:
        row = normalise_market_snapshot_row(
            {
                "Ticker": "FMT",
                "Company": "Format Test",
                "Market Cap": raw,
                "Shares in Issue": "1",
                "Status": "found_lse_share_page",
                "Snapshot Date": "2026-05-12",
            }
        )
        assert row["market_cap"] == expected

    for raw in ("N/A", "Not found", "", "-"):
        row = normalise_market_snapshot_row(
            {
                "Ticker": "MISS",
                "Company": "Missing Test",
                "Market Cap": raw,
                "Shares in Issue": "1",
                "Status": "not_found",
                "Snapshot Date": "2026-05-12",
            }
        )
        assert row["market_cap"] is None


def test_market_snapshot_source_priority_beats_lse_vendor_market_cap():
    identity = build_company_identity({"ticker": "SNAP", "exchange": "LSE"})
    metrics = normalise_company_financials(
        identity,
        {
            "market_snapshot": {
                "ticker": "SNAP",
                "market_cap": 120_000_000,
                "shares_outstanding": 12_000_000,
                "status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
            },
            "lse": {"market_cap": 10_000_000},
        },
        overrides=[],
    )

    assert metrics["market_cap"] == 120_000_000
    assert metrics["field_provenance"]["market_cap"]["source"] == "company market snapshot"
    assert "market_cap_snapshot_used" in metrics["data_quality_flags"]


def test_valid_snapshot_value_is_not_overwritten_by_missing_or_not_found_fallbacks():
    identity = build_company_identity({"ticker": "KEEP", "exchange": "LSE"})
    metrics = normalise_company_financials(
        identity,
        {
            "market_snapshot": {
                "ticker": "KEEP",
                "market_cap": 99_000_000,
                "shares_outstanding": 9_900_000,
                "status": "found_lse_share_page",
                "snapshot_date": "2026-05-12",
            },
            "lse": {"market_cap": None},
            "yahoo": {"market_cap": "Not found"},
            "london_south_east_share": {"market_cap": "-"},
        },
        overrides=[],
    )

    assert metrics["market_cap"] == 99_000_000
    assert metrics["field_provenance"]["market_cap"]["source"] == "company market snapshot"


def test_stale_market_snapshot_detection_sets_flag():
    row = normalise_market_snapshot_row(
        {
            "Ticker": "OLD",
            "Company": "Old Metals",
            "Market Cap Numeric": "1000000",
            "Shares in Issue": "1000000",
            "Status": "found_lse_share_page",
            "Snapshot Date": "2026-01-01T00:00:00+00:00",
        }
    )

    assert snapshot_is_stale("2026-01-01T00:00:00+00:00")
    assert row["snapshot_stale"]
    assert "stale_snapshot" in row["data_quality_flags"]


def test_market_snapshot_edge_case_statuses_are_explicit():
    rows = {
        ticker: normalise_market_snapshot_row(
            {
                "Ticker": ticker,
                "Company": name,
                "Market Cap Numeric": market_cap,
                "Shares in Issue": shares,
                "Status": status,
                "Primary Source": "https://example.test",
                "Snapshot Date": "2026-05-12",
            }
        )
        for ticker, name, market_cap, shares, status in [
            ("70GD", "Antofagasta Plc 5% Cum Prf #1", "", "0.00", "not_applicable_preference_share_no_market_cap"),
            ("SAUD", "Stl.au.ind.gdr", "", "0.00", "not_available_gdr_zero_shares_on_source"),
            ("ZCC", "Zccm Investments Holdings Plc", "265880000", "160.85m", "found_suspended_security"),
            ("FOX", "Focus Xplore", "695880", "3.48b", "found_via_non_constituent_search"),
        ]
    }

    assert "preference_share_no_market_cap" in rows["70GD"]["data_quality_flags"]
    assert "gdr_zero_shares" in rows["SAUD"]["data_quality_flags"]
    assert "suspended_security" in rows["ZCC"]["data_quality_flags"]
    assert rows["FOX"]["status"] == "found_via_non_constituent_search"


def test_shares_outstanding_prefers_lse_over_yahoo_and_share_page():
    identity = build_company_identity({"ticker": "TEST", "exchange": "LSE"})
    metrics = normalise_company_financials(
        identity,
        {
            "lse": {"shares_outstanding_lfy": 100, "last_price": 100, "currency": "GBX"},
            "yahoo": {"shares_outstanding_lfy": 200},
            "london_south_east_share": {"shares_outstanding_lfy": 300},
        },
        overrides=[],
    )

    assert metrics["shares_outstanding"] == 100
    assert metrics["field_provenance"]["shares_outstanding"]["source"] == "LSE official/API/PDF"


def test_revenue_status_classifies_pre_revenue_explorer_without_inventing_zero():
    identity = build_company_identity({"ticker": "EXP", "exchange": "LSE", "stage": "Exploration"})
    metrics = normalise_company_financials(
        identity,
        {"metadata": {"ticker": "EXP", "stage": "Exploration", "supply_chain_role": "Explorer"}},
        overrides=[],
    )

    assert metrics["revenue"] is None
    assert metrics["revenue_status"] == "likely_pre_revenue_unconfirmed"
    assert "likely_pre_revenue_unconfirmed" in metrics["data_quality_flags"]


def test_manual_override_applies_and_is_visible_in_notes():
    identity = build_company_identity({"ticker": "OVR", "exchange": "LSE"})
    metrics = normalise_company_financials(
        identity,
        {"metadata": {"ticker": "OVR"}},
        overrides=[
            {
                "ticker": "OVR",
                "field": "shares_outstanding",
                "value": "123000000",
                "source_name": "annual report",
                "confidence": "0.95",
                "notes": "force verified from annual report",
            }
        ],
    )

    assert metrics["shares_outstanding"] == 123_000_000
    assert "manual_override_used" in metrics["data_quality_flags"]
    assert "shares_outstanding manual override used" in metrics["data_notes"]


def test_financial_cache_state_handles_negative_and_parser_stale():
    path = Path("storage/cache/test_financial_cache_state_provider.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_text(
        json.dumps(
            {
                "parser_version": "old",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert financial_cache_state(path, ttl=timedelta(days=1)) == "parser_stale"

    path.write_text(
        json.dumps(
            {
                "parser_version": "financial_pipeline_v1",
                "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
                "negative_cache_reason": "not_found",
            }
        ),
        encoding="utf-8",
    )
    assert financial_cache_state(path, ttl=timedelta(days=1), negative_ttl=timedelta(hours=24)) == "expired_negative"
    path.unlink(missing_ok=True)


def test_coverage_audit_reports_field_failures():
    good = {
        "ticker": "GOOD",
        "name": "Good Producer",
        "fundamental": {
            "metrics": normalise_company_financials(
                build_company_identity({"ticker": "GOOD", "exchange": "LSE"}),
                {
                    "lse": {
                        "last_price": 100,
                        "currency": "GBX",
                        "shares_outstanding_lfy": 100_000_000,
                        "revenue_lfy": 1_000_000,
                        "volume": 1_000,
                        "fifty_two_week_low": 50,
                        "fifty_two_week_high": 150,
                    }
                },
                overrides=[],
            )
        },
    }
    bad = {
        "ticker": "BAD",
        "name": "Missing Shares",
        "fundamental": {
            "metrics": normalise_company_financials(
                build_company_identity({"ticker": "BAD", "exchange": "LSE"}),
                {"metadata": {"ticker": "BAD"}},
                overrides=[],
            )
        },
    }

    audit = coverage_audit([good, bad], target=0.95)

    assert audit["universe_count"] == 2
    assert audit["field_coverage"]["market_cap"]["count"] == 1
    assert "Missing Shares" in audit["failures"]["market_cap"]
    assert not audit["passed"]
