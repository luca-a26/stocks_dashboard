from data.lse import (
    _estimate_market_cap,
    _merge_lse_website_data,
    _parse_ftse_analytics_page,
    _parse_lse_company_page,
    _parse_range_pair,
    _parse_tearsheet_page,
)


def test_parse_tearsheet_page_extracts_key_statistics():
    text = """
    Pensana PLC (PRE:LN)
    Business Description and Key Statistics
    Website:
    ICB Industry:
    ICB Subsector:
    Address:
    Employees:
    Current YTY % Chg
    Revenue LFY (M)
    EPS Diluted LFY
    Market Value (M)
    Shares Outstanding LFY (000)
    Book Value Per Share
    EBITDA Margin %
    Net Margin %
    Long-Term Debt / Capital %
    Dividends and Yield TTM
    Payout Ratio TTM %
    60-Day Average Volume (000)
    52-Week High & Low
    Price / 52-Week High & Low
    Basic Materials
    Nonferrous Metals
    https://pensana.co.uk/
    Rex House
    LONDON, ON SW1Y 4PE
    GBR
    125
    0
    -0.04
    346
    339,248
    0.29
    -78373200.00
    -66729669.5
    0.0
    0.00 - 0.00%
    0.0
    589
    1.81 - 0.28
    0.56 - 3.67
    """

    parsed = _parse_tearsheet_page(text)

    assert parsed["employees"] == 125
    assert parsed["revenue_lfy"] == 0
    assert parsed["market_value_m"] == 346
    assert parsed["shares_outstanding_lfy"] == 339_248_000
    assert parsed["long_term_debt_to_capital_pct"] == 0
    assert parsed["fifty_two_week_range"] == "1.81 - 0.28"


def test_parse_ftse_analytics_page_extracts_debt_fallback():
    parsed = _parse_ftse_analytics_page(
        """
        VALUATION
        Trailing
        PE -ve
        EV/EBITDA -ve
        PB 3.0
        PCF -ve
        Div Yield 0.0
        Price/Sales -
        Net Debt/Equity 0.1
        Div Payout 0.0
        ROE -ve
        """
    )

    assert parsed["net_debt_to_equity_pct"] == 0.1
    assert parsed["price_to_book"] == 3.0


def test_lse_fallback_helpers_parse_ranges_and_estimate_gbx_market_cap():
    assert _parse_range_pair("1.81 - 0.28") == (0.28, 1.81)
    assert _estimate_market_cap(101.2, 339_248_000, "GBX") == 343_318_976
    assert _estimate_market_cap(1.012, 339_248_000, "GBP") == 343_318_976


def test_parse_lse_company_page_extracts_public_website_metrics():
    parsed = _parse_lse_company_page(
        """
        Price (GBX)
        282.50 3.86% (10.50)
        Volume
        65,424
        52 week range
        120.00 / 330.00
        Market
        AIM
        Instrument market cap (£m)
        311.01
        ISIN
        GB00B0C18177
        Market segment
        ASQ1
        Trading service
        SETSqx
        Country of share register
        GB
        """
    )

    assert parsed["last_price"] == 282.5
    assert parsed["currency"] == "GBX"
    assert parsed["volume"] == 65_424
    assert parsed["market_cap"] == 311_010_000
    assert parsed["fifty_two_week_low"] == 120
    assert parsed["fifty_two_week_high"] == 330
    assert parsed["market"] == "AIM"
    assert parsed["segment"] == "ASQ1"


def test_lse_company_page_merge_fills_and_corrects_inconsistent_market_cap():
    merged = _merge_lse_website_data(
        {
            "source": "London Stock Exchange",
            "market_cap": 10_000_000,
            "last_price": None,
            "volume": None,
            "data_fallbacks": [],
        },
        {
            "market_cap": 311_010_000,
            "last_price": 282.5,
            "volume": 65_424,
            "lse_website_urls": ["https://www.londonstockexchange.com/stock/AAZ/example/company-page"],
        },
    )

    assert merged["market_cap"] == 311_010_000
    assert merged["last_price"] == 282.5
    assert merged["volume"] == 65_424
    assert "market_cap corrected using LSE company page" in merged["data_fallbacks"]
