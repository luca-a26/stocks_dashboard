# Architecture

## Runtime Flow

```text
config/tickers.yaml
        |
data.utils.load_tickers()
        |
data.lse.fetch_company_snapshot()
        |
analysis.fundamentals.analyze_stock()
        |
analysis.composite.analyze_all_stocks()
        |
dashboard.view_model.build_dashboard_rows()
        |
Dash layout and DataTable
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
- Prefer explicit YAML configuration over hardcoded company lists.
- Keep third-party research credentials out of the repository; import derived rows manually or through a compliant export.
