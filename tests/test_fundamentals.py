from analysis import fundamentals


def test_fetch_fundamentals_uses_yahoo_fallback_when_lse_coverage_is_sparse(monkeypatch):
    monkeypatch.setattr(
        fundamentals,
        "fetch_company_snapshot",
        lambda ticker, force_refresh=False: {
            "source": "London Stock Exchange",
            "source_ticker": ticker,
            "last_price": 12.5,
            "data_coverage_ratio": 0.14,
        },
    )
    monkeypatch.setattr(
        fundamentals,
        "fetch_yahoo_london_fallback",
        lambda ticker, force_refresh=False: {
            "fallback_source": "Yahoo Finance",
            "yahoo_symbol": f"{ticker}.L",
            "market_cap": 50_000_000,
            "revenue_lfy": 10_000_000,
            "net_debt_to_equity_pct": 0.0,
            "shares_outstanding_lfy": 100_000_000,
            "currency": "GBX",
        },
    )
    monkeypatch.setattr(fundamentals, "fetch_share_price_snapshot", lambda ticker, force_refresh=False: {})
    monkeypatch.setattr(fundamentals, "get_market_snapshot_for_ticker", lambda ticker: None)

    metrics = fundamentals.fetch_fundamentals("PRE")

    assert metrics["market_cap"] == 12_500_000
    assert metrics["last_price"] == 12.5
    assert metrics["revenue_lfy"] == 10_000_000
    assert metrics["net_debt_to_equity_pct"] == 0.0
    assert metrics["fallback_source"] == "Yahoo Finance"
    assert metrics["data_coverage_ratio"] > 0.5
