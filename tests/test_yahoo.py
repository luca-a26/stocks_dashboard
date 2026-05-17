from data.yahoo import _chart_points, _quote_metrics, _summary_metrics, fetch_yahoo_price_history, yahoo_london_symbol


def test_yahoo_london_symbol_adds_lse_suffix_once():
    assert yahoo_london_symbol("PRE") == "PRE.L"
    assert yahoo_london_symbol("PRE.L") == "PRE.L"


def test_yahoo_quote_and_summary_payloads_normalise_fallback_metrics():
    quote = _quote_metrics(
        {
            "quoteResponse": {
                "result": [
                    {
                        "marketCap": 120_000_000,
                        "regularMarketPrice": 32.5,
                        "currency": "GBp",
                        "regularMarketVolume": 45_000,
                        "fiftyTwoWeekLow": 10,
                        "fiftyTwoWeekHigh": 50,
                        "sharesOutstanding": 300_000_000,
                    }
                ]
            }
        }
    )
    summary = _summary_metrics(
        {
            "quoteSummary": {
                "result": [
                    {
                        "financialData": {
                            "totalRevenue": {"raw": 15_000_000},
                            "totalDebt": {"raw": 1_000_000},
                            "debtToEquity": {"raw": 4.2},
                        },
                        "summaryDetail": {
                            "priceToSalesTrailing12Months": {"raw": 8.0},
                        },
                        "defaultKeyStatistics": {
                            "priceToBook": {"raw": 1.5},
                        },
                    }
                ]
            }
        }
    )

    assert quote["market_cap"] == 120_000_000
    assert quote["fifty_two_week_high"] == 50
    assert summary["revenue_lfy"] == 15_000_000
    assert summary["net_debt_to_equity_pct"] == 4.2
    assert summary["price_to_book"] == 1.5


def test_yahoo_chart_payload_normalises_close_points():
    parsed = _chart_points(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "PRE.L", "currency": "GBp"},
                        "timestamp": [1767225600, 1767312000, 1767398400],
                        "indicators": {"quote": [{"close": [101.5, None, 104.0]}]},
                    }
                ]
            }
        }
    )

    assert parsed["symbol"] == "PRE.L"
    assert parsed["currency"] == "GBp"
    assert parsed["points"] == [
        {"date": "2026-01-01", "close": 101.5},
        {"date": "2026-01-03", "close": 104.0},
    ]


def test_yahoo_chart_fetch_uses_cache_parser(monkeypatch):
    def fake_get_json(url, cache_path, force_refresh=False, *, timeout=20):
        assert "range=1y" in url
        assert "interval=1d" in url
        assert cache_path.name == "PRE.L_chart_1y_1d.json"
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "PRE.L", "currency": "GBp"},
                        "timestamp": [1767225600],
                        "indicators": {"quote": [{"close": [101.5]}]},
                    }
                ]
            }
        }

    monkeypatch.setattr("data.yahoo._get_json", fake_get_json)

    parsed = fetch_yahoo_price_history("PRE")

    assert parsed["symbol"] == "PRE.L"
    assert parsed["points"] == [{"date": "2026-01-01", "close": 101.5}]
    assert parsed["source"] == "Yahoo Finance chart"


def test_yahoo_chart_parser_handles_malformed_payload():
    assert _chart_points({"chart": {"result": []}}) == {}
    assert _chart_points({"not": "a chart"}) == {}
