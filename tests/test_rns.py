from __future__ import annotations

from pathlib import Path

from analysis.composite import _metadata_stock
from data.rns import (
    RnsAnnouncement,
    build_rns_technical_metrics_from_announcements,
    extract_technical_evidence_from_text,
    is_relevant_technical_source,
    load_tracked_rns_technical_metrics,
    parse_london_south_east_rns_article,
    parse_london_south_east_rns_links,
    parse_lse_news_article_payload,
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
    assert metrics["technical_evidence_status"] == "structured_fields_extracted"
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


def test_parse_lse_news_article_payload_extracts_body():
    payload = {
        "components": [
            {
                "type": "news-article-content",
                "content": [
                    {
                        "name": "newsarticle",
                        "value": {
                            "title": "Updated Mineral Resource Estimate",
                            "datetime": "2026-01-02T07:00:00.000",
                            "companycode": "RBW",
                            "body": "<html><body><p>12.4 Mt indicated resource grading 2.1% TREO.</p></body></html>",
                        },
                    }
                ],
            }
        ]
    }

    announcement = parse_lse_news_article_payload(
        payload,
        "https://www.londonstockexchange.com/news-article/RBW/test/1",
        "rbw.l",
    )

    assert announcement is not None
    assert announcement.ticker == "RBW"
    assert announcement.title == "Updated Mineral Resource Estimate"
    assert announcement.released == "2026-01-02T07:00:00.000"
    assert "2.1% TREO" in announcement.text


def test_parse_london_south_east_rns_links_extracts_headlines_and_dates():
    html = """
    <table>
      <tr>
        <td>1st Sep 2025</td><td><small>7:00 am</small></td><td>RNS</td>
        <td><a href="https://www.lse.co.uk/rns/RBW/cix-test-work.html">CIX Test Work</a></td>
      </tr>
      <tr><td><a href="https://www.lse.co.uk/rns/MKA/other.html">Other</a></td></tr>
    </table>
    """

    links = parse_london_south_east_rns_links(html, "rbw.l")

    assert links == [
        {
            "url": "https://www.lse.co.uk/rns/RBW/cix-test-work.html",
            "title": "CIX Test Work",
            "released": "1st Sep 2025 7:00 am",
        }
    ]


def test_parse_london_south_east_rns_article_extracts_article_node():
    html = """
    <html><body>
      <nav>Market Cap: noisy navigation</nav>
      <div class="rns__article-content">
        <p class="rns__date">1 Sep 2025 07:00</p>
        <div>RNS Number : 3726X</div>
        <p>Metallurgical test work confirmed 76% recovery and 55% TREO concentrate.</p>
      </div>
    </body></html>
    """

    announcement = parse_london_south_east_rns_article(
        html,
        "https://www.lse.co.uk/rns/RBW/cix-test-work.html",
        "RBW",
        title="CIX Test Work",
    )

    assert announcement.title == "CIX Test Work"
    assert announcement.released == "1 Sep 2025 07:00"
    assert "76% recovery" in announcement.text
    assert "noisy navigation" not in announcement.text


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


def test_project_rns_candidate_is_kept_when_structured_fields_are_missing():
    announcement = RnsAnnouncement(
        ticker="EEE",
        title="Pitfield Project Update",
        url="https://example.com/eee-rns",
        released="1 May 2026",
        text="The company issued a project update and investor presentation for the Pitfield project.",
    )

    metrics = build_rns_technical_metrics_from_announcements([announcement])

    assert metrics["technical_evidence_status"] == "rns_or_document_found_needs_review"
    assert metrics["technical_field_count"] == 0
    assert metrics["rns_latest_title"] == "Pitfield Project Update"
    assert "review" in metrics["rns_technical_notes"].lower()


def test_representative_source_prefers_structured_evidence_over_newer_review_item():
    metrics = build_rns_technical_metrics_from_announcements(
        [
            RnsAnnouncement(
                ticker="PRE",
                title="Corporate Presentation",
                url="https://example.com/presentation",
                released="2026-02-01",
                text="The company published an investor presentation.",
            ),
            RnsAnnouncement(
                ticker="PRE",
                title="Longonjo drill programme",
                url="https://example.com/drilling",
                released="2026-01-01",
                text="The updated mineral resource includes 12.4 Mt indicated resource grading 2.1% TREO.",
            ),
        ]
    )

    assert metrics["technical_evidence_status"] == "structured_fields_extracted"
    assert metrics["rns_latest_title"] == "Longonjo drill programme"


def test_irrelevant_corporate_rns_is_ignored():
    assert not is_relevant_technical_source("PDMR Shareholding", "director dealing")
    assert not is_relevant_technical_source("Reduction of the Share Premium Reserve", "")
    assert is_relevant_technical_source("Mineral Resource Estimate", "")
    assert is_relevant_technical_source("Publication of Annual Report and Notice of AGM", "")


def test_financial_reserve_phrase_does_not_create_resource_category():
    evidence = extract_technical_evidence_from_text(
        "The company approved a distribution of assets from the reserve for invested unrestricted equity.",
        "Distribution of assets from the reserve",
    )

    assert "resource_category" not in evidence


def test_proven_without_resource_context_does_not_create_resource_category():
    evidence = extract_technical_evidence_from_text(
        "The company has a proven processing route for metallurgical grade chrome ore concentrate.",
        "Production update",
    )

    assert evidence["metallurgical_testwork"] is True
    assert "resource_category" not in evidence


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
