# Architecture

## Runtime Flow

```text
config/ticker_universe.csv + config/tickers.yaml + config/ree_pipeline.yaml
        |
data.universe.load_ticker_universe()
        |
analysis.composite.load_default_ranked_stocks()
        |
analysis.rare_earth_scoring
        |
dashboard.view_model.build_dashboard_rows()
        |
Dash top-100 table and search workflow
```

Expensive market/fundamental data is now lazy:

```text
Search/select ticker
        |
analysis.composite.load_detailed_stock()
        |
data.lse.fetch_company_snapshot()
        |
analysis.rare_earth_scoring
        |
storage/cache/lse + storage/cache/scores
```

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
- Keep third-party research credentials out of the repository; import derived rows manually or through a compliant export.
