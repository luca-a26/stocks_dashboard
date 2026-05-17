from __future__ import annotations

from data.london_south_east import _parse_share_price_page, parse_industrial_metals_constituents
from data import universe


SECTOR_HTML = """
<html>
  <body>
    <a href="/SharePrice.html?shareprice=AVCT&share=Avacta-Group">
      Avacta Group (AVCT)
    </a>
    <table class="sp-constituents__table">
      <tr>
        <td>
          <a href="/SharePrice.html?shareprice=ARA&share=Aclara-Resources">
            Aclara Resources (ARA)
          </a>
        </td>
        <td>12.50</td>
        <td>1,234</td>
        <td>3.20%</td>
        <td>12.00</td>
        <td>13.00</td>
        <td>8</td>
      </tr>
      <tr>
        <td>
          <a href="/SharePrice.html?shareprice=SVML&share=Sovereign-Metals">
            Sovereign Metals (SVML)
          </a>
        </td>
      </tr>
      <tr>
        <td>
          <a href="/SharePrice.html?shareprice=NMX551020">Industrial Metals (NMX551020)</a>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def test_parse_industrial_metals_constituents_extracts_company_metadata():
    records = parse_industrial_metals_constituents(SECTOR_HTML)

    assert [record["ticker"] for record in records] == ["ARA", "SVML"]
    assert records[0]["exchange"] == "LSE"
    assert records[0]["sector"] == "Industrial Metals"
    assert records[0]["commodity_tags"] == "industrial metals"
    assert records[0]["source"] == "London South East Industrial Metals"
    assert records[0]["last_price"] == 12.5
    assert records[0]["volume"] == 1234


def test_parse_share_price_page_extracts_basic_market_cap_fields():
    parsed = _parse_share_price_page(
        """
        Share Price Information for Anglo Asian Mining PLC (AAZ)
        Share Price is delayed by 15 minutes
        Get Live Data
        247.50 0.00 (0.00%)
        Market Cap: £274.42m
        Price | 247.50 | Open | 0.00
        Volume
        200,187
        Currency
        GBX
        Issue Country
        GB
        Shares in Issue
        114.34m
        Year High
        327.50
        Year Low
        117.50
        # Trades
        106
        """
    )

    assert parsed["market_cap"] == 274_420_000
    assert parsed["last_price"] == 247.5
    assert parsed["volume"] == 200_187
    assert parsed["shares_outstanding_lfy"] == 114_340_000
    assert parsed["fifty_two_week_high"] == 327.5
    assert parsed["fifty_two_week_low"] == 117.5
    assert parsed["currency"] == "GBX"


def test_load_ticker_universe_merges_lse_sector_cache_with_tracked_metadata(monkeypatch):
    monkeypatch.setattr(
        universe,
        "_records_from_sector_cache",
        lambda: {
            "ARA": {
                "ticker": "ARA",
                "exchange": "LSE",
                "company_name": "Aclara Resources",
                "sector": "Industrial Metals",
                "commodity_tags": ["industrial metals"],
            }
        },
    )
    monkeypatch.setattr(
        universe,
        "_records_from_universe_csv",
        lambda _path: {
            "ARA": {
                "ticker": "ARA",
                "company_name": "Aclara Resources",
                "commodity_tags": ["rare earths", "HREE"],
                "priority": "High",
            },
            "PRE": {
                "ticker": "PRE",
                "exchange": "LSE",
                "company_name": "Pensana",
                "commodity_tags": ["rare earths"],
            },
        },
    )

    records = universe.load_ticker_universe(include_curated=False, include_discovery=False)
    by_ticker = {record["ticker"]: record for record in records}

    assert set(by_ticker) == {"ARA", "PRE"}
    assert by_ticker["ARA"]["sector"] == "Industrial Metals"
    assert by_ticker["ARA"]["commodity_tags"] == ["industrial metals", "rare earths", "HREE"]
    assert by_ticker["ARA"]["priority"] == "High"
