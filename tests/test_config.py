from data.utils import load_tickers


def test_load_tickers_from_config_without_price_downloads():
    tickers = load_tickers()

    assert "PRE" in tickers
    assert tickers["PRE"]["name"] == "Pensana"
    assert tickers["PRE"]["ticker"] == "PRE"


def test_katoro_gold_is_tracked_under_current_lse_ticker():
    tickers = load_tickers()

    assert "FOX" in tickers
    assert tickers["FOX"]["former_ticker"] == "KAT"
