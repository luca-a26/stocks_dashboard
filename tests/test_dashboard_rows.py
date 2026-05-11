from dashboard.view_model import build_dashboard_rows


def test_build_dashboard_rows_uses_lse_fundamental_fields():
    rows = build_dashboard_rows(
        [
            {
                "ticker": "PRE",
                "name": "Pensana",
                "exchange": "LSE",
                "composite_score": 6.5,
                "fundamental": {
                    "fundamentals": {"score": 6.5, "drivers": ["LSE market cap available"]},
                    "metrics": {
                        "market_cap": 1_200_000,
                        "market": "MAINMARKET",
                        "segment": "SET3",
                        "issuer_name": "PENSANA PLC",
                        "last_price": 101.2,
                        "currency": "GBX",
                        "revenue_lfy": 5_000_000,
                        "long_term_debt_to_capital_pct": 8.5,
                        "net_debt_to_equity_pct": None,
                        "shares_outstanding_lfy": 339_248_000,
                        "volume": 16_062,
                        "fifty_two_week_low": 26.6,
                        "fifty_two_week_high": 184.5,
                        "source": "London Stock Exchange",
                        "retrieved": "2026-02-11T20:00:00+00:00",
                    },
                },
            }
        ]
    )

    assert rows[0]["Ticker"] == "PRE"
    assert rows[0]["Company"] == "PENSANA PLC"
    assert rows[0]["Exchange"] == "MAINMARKET"
    assert rows[0]["Segment"] == "SET3"
    assert rows[0]["Rating"] == "Strong watchlist"
    assert rows[0]["Market Cap"] == "1.2M"
    assert rows[0]["Last Price"] == "101.2 GBX"
    assert rows[0]["Revenue LFY"] == "5.0M"
    assert rows[0]["Debt Metric"] == "8.5% LT debt/cap"
    assert rows[0]["Shares Outstanding"] == "339.2M"
    assert "Sentiment" not in rows[0]
