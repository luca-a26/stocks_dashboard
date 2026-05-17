# Architecture

## Runtime Flow

```text
storage/cache/london_south_east/industrial_metals_universe.csv
        +
config/ticker_universe.csv + config/tickers.yaml + config/ree_pipeline.yaml
        +
data/company_market_snapshot.csv or data/company_market_snapshot.json
        |
data.universe.load_ticker_universe()
        |
analysis.composite.load_default_ranked_stocks()
        |
analysis.rare_earth_scoring
        |
dashboard.view_model.build_dashboard_rows()
        |
Dash comparison table and compact company search
```

Expensive market/fundamental data is now lazy:

```text
Click Load financials for matching comparison rows
        |
analysis.composite.load_detailed_stock()
        |
data.market_snapshot.load_market_snapshot()
        |
data.lse.fetch_company_snapshot()
        |
analysis.rare_earth_scoring
        |
storage/cache/lse + storage/cache/scores
```

The London South East sector import is refreshable and cached:

```text
python -m data.london_south_east
        |
London South East Industrial Metals constituents page
        |
storage/cache/london_south_east/industrial_metals_universe.csv
```

That cache stores only cheap metadata: ticker, exchange, company name, sector,
commodity tag, source, and notes. It does not fetch all company fundamentals.

The canonical market snapshot is committed data, not runtime cache:

```text
.github/workflows/market-snapshot.yml
        |
python -m scripts.refresh_company_market_snapshot
        |
London South East per-company pages + optional LSE/Yahoo fallbacks
        |
data/company_market_snapshot.csv + data/company_market_snapshot.json
        |
storage/audit/company_market_snapshot_audit.json artifact
```

Dashboard runtime loads the snapshot before live market fallbacks. Live startup
refreshes are controlled by `ENABLE_LIVE_MARKET_REFRESH` and default to off so
page loads remain fast and reproducible.

Rare-earth discovery data follows a separate manual-enrichment path:

```text
config/ree_pipeline.yaml
        |
data.discovery
        |
dashboard.discovery_view_model
        |
Dash tabs, tables, and charts
```

## Boundaries

- `config/` owns static watchlist and runtime settings.
- `data/` owns configuration helpers, storage paths, logging, and data-source adapters.
- `analysis/` owns scoring logic and transforms raw metrics into structured signals.
- `dashboard/` owns presentation, layout, styling, and table-ready rows.
- `tests/` owns deterministic validation and should avoid live network dependencies.

## Design Principles

- Keep imports lightweight.
- Keep generated runtime data out of Git.
- Keep dashboard logic testable without starting a web server.
- Prefer explicit configuration files over hardcoded company lists.
- Keep ticker-universe metadata separate from expensive fundamentals.
- Use the committed market snapshot as the stable first source for market cap and shares before runtime scraping.
- Keep third-party research credentials out of the repository; import derived rows manually or through a compliant export.
- Use the London South East sector cache as a generated universe input, not as a committed source file.
