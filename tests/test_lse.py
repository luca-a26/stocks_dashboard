from data.lse import _parse_ftse_analytics_page, _parse_tearsheet_page


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
