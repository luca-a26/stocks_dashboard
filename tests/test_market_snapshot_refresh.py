from scripts.refresh_company_market_snapshot import _repair_share_count_units, _status_for_row


def test_refresh_repairs_unitless_lse_share_count_from_market_cap_and_price():
    repaired = _repair_share_count_units(
        5.08,
        market_cap=160_850_000_000,
        last_price=3166,
        price_currency="GBX",
    )

    assert round(repaired or 0) == 5_080_543_272


def test_refresh_preserves_preference_share_non_applicable_status():
    assert (
        _status_for_row("not_applicable_preference_share_no_market_cap", None, 985_857_000)
        == "not_applicable_preference_share_no_market_cap"
    )
