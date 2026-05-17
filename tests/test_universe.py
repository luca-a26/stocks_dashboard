from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from analysis import composite
from data import universe
from dashboard.view_model import build_dashboard_rows


def _large_universe_records():
    records = {}
    for index in range(1005):
        ticker = f"T{index:04d}"
        records[ticker] = {
            "ticker": ticker,
            "exchange": "LSE",
            "company_name": f"Test Metals {index}",
            "country": f"Country {index % 7}",
            "sector": "Basic Materials",
            "commodity_tags": ["rare earths", "copper"],
            "supply_chain_role": "Explorer",
            "stage": "Exploration",
            "market_cap_tier": "micro",
            "source": "fixture",
            "notes": "",
            "priority": "Low",
        }
    return records


def test_load_ticker_universe_supports_1000_plus_rows(monkeypatch):
    monkeypatch.setattr(universe, "_records_from_universe_csv", lambda _path: _large_universe_records())

    records = universe.load_ticker_universe(Path("fixture.csv"), include_curated=False, include_discovery=False)

    assert len(records) == 1005
    assert records[0]["commodity_tags"] == ["rare earths", "copper"]


def test_default_metadata_ranking_returns_top_100():
    records = list(_large_universe_records().values())

    ranked = universe.rank_metadata_universe(records, limit=100)

    assert len(ranked) == 100
    assert all(universe.preliminary_score(record) >= 0 for record in ranked)


def test_default_ranked_stocks_can_return_full_comparison_universe(monkeypatch):
    records = list(_large_universe_records().values())[:116]
    monkeypatch.setattr(composite, "load_ticker_universe", lambda: records)
    monkeypatch.setattr(composite, "load_cached_scored_stocks", lambda include_stale=True: [])
    monkeypatch.setattr(composite, "load_tickers", lambda: {})

    stocks, source = composite.load_default_ranked_stocks(limit=None)

    assert len(stocks) == 116
    assert all(stock["score_status"] == "metadata_only" for stock in stocks)
    assert "metadata" in source


def test_metadata_stock_keeps_sector_market_snapshot(monkeypatch):
    monkeypatch.setattr(composite, "build_rns_technical_metrics", lambda ticker, company_name: {})
    market_snapshot = {
        "RIO": {
            "ticker": "RIO",
            "market_cap": 126_290_000_000,
            "market_cap_currency": "GBP",
            "last_price": 7766,
            "price_currency": "GBX",
            "price_unit": "GBp",
            "volume": 2_783_924,
            "status": "found_lse_share_page",
        }
    }
    stock = composite._metadata_stock(
        {
            "ticker": "RIO",
            "company_name": "Rio Tinto",
            "exchange": "LSE",
            "commodity_tags": ["industrial metals"],
            "last_price": "7927",
            "volume": "2827539",
        },
        market_snapshot,
    )

    metrics = stock["fundamental"]["metrics"]
    assert stock["score_status"] == "metadata_only"
    assert metrics["last_price"] == 7766
    assert metrics["volume"] == 2_783_924


def test_metadata_stock_with_rns_evidence_becomes_partial(monkeypatch):
    monkeypatch.setattr(
        composite,
        "build_rns_technical_metrics",
        lambda ticker, company_name: {
            "metallurgical_testwork": True,
            "technical_evidence_status": "structured_fields_extracted",
            "data_fallbacks": ["RNS technical evidence applied (1 announcement)"],
        },
    )
    stock = composite._metadata_stock(
        {
            "ticker": "RIO",
            "company_name": "Rio Tinto",
            "exchange": "LSE",
            "commodity_tags": ["industrial metals"],
            "last_price": "7927",
            "volume": "2827539",
        },
        {},
    )

    metrics = stock["fundamental"]["metrics"]
    assert stock["score_status"] == "partial"
    assert metrics["last_price"] == 7927
    assert metrics["volume"] == 2_827_539


def test_metadata_stock_uses_london_south_east_share_page_for_market_cap(monkeypatch):
    monkeypatch.setattr(composite, "STARTUP_BASIC_MARKET_FALLBACK", True)
    monkeypatch.setattr(
        composite,
        "fetch_share_price_snapshot",
        lambda ticker, company_name: {
            "market_cap": 274_420_000,
            "shares_outstanding_lfy": 114_340_000,
            "fifty_two_week_low": 117.5,
            "fifty_two_week_high": 327.5,
            "currency": "GBX",
            "source": "London South East share page",
        },
    )

    stock = composite._metadata_stock(
        {
            "ticker": "AAZ",
            "company_name": "Anglo Asian Mining PLC",
            "exchange": "LSE",
            "commodity_tags": ["industrial metals"],
            "last_price": "247.5",
            "volume": "200187",
            "source": "London South East Industrial Metals",
        },
        {},
    )

    metrics = stock["fundamental"]["metrics"]
    assert metrics["market_cap"] == 274_420_000
    assert metrics["shares_outstanding_lfy"] == 114_340_000
    assert metrics["fifty_two_week_high"] == 327.5
    assert "London South East share page" in metrics["source"]


def test_search_matches_company_ticker_country_commodity_and_role():
    records = [
        {
            "ticker": "HRE",
            "company_name": "Heavy Rare Earth Co",
            "exchange": "ASX",
            "country": "Australia",
            "sector": "Basic Materials",
            "commodity_tags": ["HREE", "dysprosium"],
            "supply_chain_role": "Magnet metals developer",
            "stage": "Exploration",
        }
    ]

    assert universe.search_ticker_universe("HRE", records)[0]["ticker"] == "HRE"
    assert universe.search_ticker_universe("australia dysprosium", records)[0]["ticker"] == "HRE"
    assert universe.search_ticker_universe("magnet developer", records)[0]["ticker"] == "HRE"


def test_default_ranked_stocks_do_not_fetch_fundamentals(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_default")
    monkeypatch.setattr(
        composite,
        "load_ticker_universe",
        lambda: [
            {
                "ticker": "META",
                "company_name": "Metadata Only Plc",
                "exchange": "LSE",
                "commodity_tags": ["rare earths"],
                "priority": "High",
            }
        ],
    )
    called = {"count": 0}

    def fake_analyze(_ticker):
        called["count"] += 1
        raise AssertionError("fundamentals should be lazy")

    monkeypatch.setattr(composite, "fundamental_analyze", fake_analyze)

    stocks, source = composite.load_default_ranked_stocks(limit=1)

    assert called["count"] == 0
    assert stocks[0]["score_status"] == "metadata_only"
    assert "metadata" in source


def test_default_ranked_stocks_preserves_stale_cached_score_status(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_default_status")
    universe.score_cache_path("STALE").unlink(missing_ok=True)
    universe.write_scored_stock_cache(
        "STALE",
        {
            "ticker": "STALE",
            "name": "Stale Cache Plc",
            "composite_score": 6.1,
            "full_score": 6.1,
            "preliminary_score": 4.0,
            "score_status": "partial",
            "fundamental": {"fundamentals": {"drivers": ["fixture"]}, "metrics": {}},
        },
    )
    monkeypatch.setattr(universe, "cache_state", lambda _path: "stale")
    monkeypatch.setattr(
        composite,
        "load_ticker_universe",
        lambda: [{"ticker": "STALE", "company_name": "Stale Cache Plc", "exchange": "LSE"}],
    )
    monkeypatch.setattr(composite, "load_market_snapshot", lambda: {})
    monkeypatch.setattr(composite, "load_tickers", lambda: {})

    stocks, _source = composite.load_default_ranked_stocks(limit=1)

    assert stocks[0]["score_status"] == "partial"
    assert stocks[0]["score_cache_state"] == "stale"


def test_load_detailed_stock_fetches_once_then_uses_cache(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_detail")
    universe.score_cache_path("CACHE").unlink(missing_ok=True)
    monkeypatch.setattr(composite, "get_universe_record", lambda ticker: {"ticker": ticker, "company_name": "Cached Plc"})
    calls = {"count": 0}

    def fake_analyze(_ticker):
        calls["count"] += 1
        return {
            "fundamentals": {"score": 6.0, "drivers": ["fixture"]},
            "metrics": {
                "market_cap": 10_000_000,
                "revenue_lfy": 1_000_000,
                "resource_category": "Indicated",
                "recovery_pct": 72,
            },
        }

    monkeypatch.setattr(composite, "fundamental_analyze", fake_analyze)

    first = composite.load_detailed_stock("CACHE")
    second = composite.load_detailed_stock("CACHE")

    assert calls["count"] == 1
    assert first["score_status"] == "full"
    assert second["score_status"] == "full"


def test_load_detailed_stock_marks_missing_financials_as_partial(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_partial")
    universe.score_cache_path("PART").unlink(missing_ok=True)
    monkeypatch.setattr(composite, "get_universe_record", lambda ticker: {"ticker": ticker, "company_name": "Partial Plc"})

    def fake_analyze(_ticker):
        return {
            "fundamentals": {"score": 5.0, "drivers": ["Revenue LFY unavailable"]},
            "metrics": {"source": "fixture"},
        }

    monkeypatch.setattr(composite, "fundamental_analyze", fake_analyze)

    stock = composite.load_detailed_stock("PART")

    assert stock["score_status"] == "partial"
    assert 0 <= stock["full_score"] <= 10
    assert "Revenue LFY unavailable" in stock["fundamental"]["fundamentals"]["drivers"]


def test_score_cache_hit_miss_and_stale_status(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_cache")
    universe.score_cache_path("MISS").unlink(missing_ok=True)
    universe.score_cache_path("HIT").unlink(missing_ok=True)

    missing, missing_state = universe.read_scored_stock_cache("MISS")
    universe.write_scored_stock_cache("HIT", {"ticker": "HIT", "composite_score": 5})
    hit, hit_state = universe.read_scored_stock_cache("HIT")
    stale_state = universe.cache_state(universe.score_cache_path("HIT"), ttl=timedelta(seconds=0))

    assert missing is None
    assert missing_state == "missing"
    assert hit["ticker"] == "HIT"
    assert hit_state == "fresh"
    assert stale_state == "stale"


def test_stale_score_cache_preserves_analytical_score_status(monkeypatch):
    monkeypatch.setattr(universe, "SCORE_CACHE_DIR", universe.SCORE_CACHE_DIR / "pytest_scores_status")
    universe.score_cache_path("STALE").unlink(missing_ok=True)
    universe.write_scored_stock_cache(
        "STALE",
        {
            "ticker": "STALE",
            "composite_score": 5,
            "score_status": "partial",
        },
    )
    monkeypatch.setattr(universe, "cache_state", lambda _path: "stale")

    stocks = universe.load_cached_scored_stocks(include_stale=True)

    assert stocks[0]["score_status"] == "partial"
    assert stocks[0]["score_cache_state"] == "stale"


def test_dashboard_rows_show_score_status_and_score_types():
    rows = build_dashboard_rows(
        [
            {
                "ticker": "META",
                "name": "Metadata Only",
                "exchange": "LSE",
                "commodity_tags": ["rare earths"],
                "preliminary_score": 5.2,
                "full_score": None,
                "score_status": "metadata_only",
                "composite_score": 5.2,
                "fundamental": {
                    "fundamentals": {"score": 5.2, "drivers": ["metadata"]},
                    "metrics": {},
                },
            }
        ]
    )

    assert rows[0]["Score Status"] == "metadata_only"
    assert rows[0]["Full Score"] == "Not loaded"
    assert rows[0]["Prelim Score"] == 5.2
