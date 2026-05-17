from __future__ import annotations

from pathlib import Path

from analysis.composite import _metadata_stock
from data.rns import (
    RnsAnnouncement,
    build_rns_technical_metrics_from_announcements,
    extract_technical_evidence_from_text,
    load_tracked_rns_technical_metrics,
    parse_lse_news_links,
)


def test_extract_technical_evidence_from_rns_text():
    text = """
    The updated mineral resource includes 12.4 Mt indicated resource grading 2.1% TREO.
    Metallurgical test work confirmed 76.5% recovery into a mixed rare earth concentrate
    with low thorium and low uranium. The project has completed a PFS and uses monazite
    mineralisation.
    """

    evidence = extract_technical_evidence_from_text(text, "Metallurgical test work update")

    assert evidence["mineralogy"] == "monazite"
    assert evidence["metallurgical_testwork"] is True
    assert evidence["recovery_pct"] == 76.5
    assert evidence["treo_grade_pct"] == 2.1
    assert evidence["resource_tonnage_mt"] == 12.4
    assert evidence["resource_category"] == "Indicated"
    assert evidence["study_stage"] == "PFS"
    assert "low radioactivity" in evidence["impurity_profile"]


def test_load_tracked_rns_technical_metrics(tmp_path: Path):
    csv_path = tmp_path / "rns_technical_evidence.csv"
    csv_path.write_text(
        "\n".join(
            [
                "ticker,company,announcement_date,announcement_title,source_url,mineralogy,metallurgical_testwork,recovery_pct,concentrate_grade_pct,resource_category,study_stage,treo_grade_pct,resource_tonnage_mt,contained_treo_tonnes,contained_ndpr_tonnes,ndpr_pct_of_treo,impurity_profile,thorium_ppm,uranium_ppm,capex,opex,processing_depth,source_name,confidence,notes,last_verified",
                "RBW,Rainbow,2026-01-01,Met test,https://example.com/rns,monazite,true,82,,Measured,PFS,4.2,20,,,,low thorium,,,120000000,45,carbonate,RNS,High,Strong testwork,2026-01-02",
            ]
        ),
        encoding="utf-8",
    )

    metrics = load_tracked_rns_technical_metrics("RBW.L", csv_path)

    assert metrics["mineralogy"] == "monazite"
    assert metrics["metallurgical_testwork"] is True
    assert metrics["recovery_pct"] == 82
    assert metrics["resource_category"] == "Measured"
    assert metrics["rns_evidence_count"] == 1
    assert metrics["technical_evidence_sources"][0]["url"] == "https://example.com/rns"


def test_parse_lse_news_links_normalises_ticker():
    html = """
    <a href="/news-article/RBW/cix-test-work/17208126">CIX Test Work</a>
    <a href="/news-article/MKA/other/1">Other</a>
    """

    links = parse_lse_news_links(html, "rbw.l")

    assert links == [
        {
            "url": "https://www.londonstockexchange.com/news-article/RBW/cix-test-work/17208126",
            "title": "CIX Test Work",
        }
    ]


def test_build_rns_technical_metrics_from_announcements():
    announcement = RnsAnnouncement(
        ticker="MKA",
        title="First recycled rare earth alloy production",
        url="https://example.com/mka-rns",
        released="7 July 2025",
        text="Pilot plant metallurgical testwork produced rare earth alloy from magnet recycling.",
    )

    metrics = build_rns_technical_metrics_from_announcements([announcement])

    assert metrics["metallurgical_testwork"] is True
    assert metrics["processing_depth"] == "metals/alloys/recycling"
    assert metrics["rns_latest_title"] == "First recycled rare earth alloy production"


def test_metadata_stock_uses_rns_technical_evidence(monkeypatch):
    monkeypatch.setattr(
        "analysis.composite.build_rns_technical_metrics",
        lambda ticker, company_name: {
            "mineralogy": "monazite",
            "metallurgical_testwork": True,
            "recovery_pct": 78,
            "resource_category": "Indicated",
            "study_stage": "PFS",
            "technical_data_source": "RNS technical evidence",
            "technical_evidence_sources": [{"title": "Metallurgical update", "date": "2026-01-01"}],
            "data_fallbacks": ["RNS technical evidence applied (1 announcement)"],
        },
    )
    record = {
        "ticker": "TEST",
        "company_name": "Test Rare Earths",
        "commodity_tags": ["rare earths", "NdPr"],
        "stage": "Development",
    }

    stock = _metadata_stock(record, {})

    assert stock["score_status"] == "partial"
    assert stock["technical_asset_score"] > 5
    assert stock["fundamental"]["metrics"]["mineralogy"] == "monazite"
    assert "RNS technical evidence" in stock["fundamental"]["metrics"]["source"]
