# Changelog

All notable changes to this project should be documented here.

The format follows Keep a Changelog style, with an `Unreleased` section for work that has not yet been tagged.

## Unreleased

### Added

- Modern Dash dashboard layout with KPI cards, ranked candidates, score highlighting, and responsive styling.
- London Stock Exchange data provider with cached JSON market data and tearsheet parsing for revenue and debt/capital metrics.
- REE project pipeline, supply-chain ranking, and catalyst tracking tabs with stage/exposure/status charts.
- `config/ree_pipeline.yaml` as the manual home for REEx-derived discovery candidates, processor/magnet-maker rankings, and catalysts.
- Expanded watchlist with requested LSE/AIM critical-minerals names and added exchange/segment filter columns.
- Full methodology documentation for scoring, rating labels, display calculations, charts, and discovery workflow.
- Scalable ticker-universe architecture with metadata search, top-100 default ranking, lazy fundamentals loading, score-status labels, and score-cache support.
- Rare-earth hybrid scoring framework with technical asset, commercial/financial, and strategic supply-chain component scores, confidence, stage gates, missing-data reporting, and reason codes.
- Workbook-style rare-earth benchmark scoring layer covering deposit quality, valuation, downstream revenue integration, production visibility, strategic criticality, confidence levels, peer groups, and positive/negative drivers.
- Yahoo Finance fallback enrichment for sparse detailed rows, plus data-coverage and fallback-note fields in the comparison table.
- LSE public company-page fallback to fill or correct market cap, price, volume, 52-week range, market, segment, and instrument metadata when API/PDF data is sparse or inconsistent.
- London South East per-company share-page fallback for startup metadata rows, filling market cap, shares in issue, year high/low, volume, currency, and trade count before full detailed scoring where possible.
- Field-owned financial data pipeline with canonical company identity, per-field provenance, market-cap computation, revenue status classification, manual overrides, data-quality flags, and coverage audit reporting.
- Canonical company market snapshot resources in `data/company_market_snapshot.csv` and `data/company_market_snapshot.json`, plus a three-hour GitHub Actions refresh workflow and audit artifact.
- `config/company_financial_overrides.csv` for auditable manual corrections to company financial fields.
- Relative peer comparison popup with 1-5 equal-weight scorecards, company cards, peer add/remove controls, and `config/relative_score_overrides.csv` for criterion-level analyst overrides.
- Company overview tab for the comparison modal, including KPI blocks, driver summaries, resource links, and a lazy cached Yahoo share chart with safe fallback states.
- London South East Industrial Metals sector importer that refreshes a broad LSE universe into ignored local cache storage.
- Runtime logging to `logs/dashboard.log`.
- GitHub-ready repository infrastructure, including CI, issue templates, pull request template, `.gitignore`, `.gitattributes`, and `.editorconfig`.
- Project operating docs in `README.md`, `WORKFLOW.md`, `AGENTS.md`, and `docs/`.
- Unit tests for dashboard row building and config-driven ticker loading.

### Changed

- Made `data.load_tickers()` side-effect free so config loading no longer downloads market data.
- Consolidated dashboard data into an explainable rare-earth hybrid scoring model while preserving LSE-backed financial metrics.
- Replaced the large universe-search panel with a compact top search bar and expanded the comparison table to include the full merged LSE Industrial Metals universe.
- Moved commodity exposure beside the technical evidence fields, fixed the company/ticker columns, and added compact financial refresh for comparison rows.
- Replaced comparison scoreboard pagination with a single scrollable table so all companies remain in one continuous grid.
- Replaced the main comparison scoreboard's Dash `DataTable` with a custom scrollable HTML table to avoid stale paginated table rendering.
- Clamped long comparison-table cell content with hover titles and fixed column widths so verbose scoring notes do not expand row height.
- Extended the dashboard scoring table with benchmark score, confidence level, peer group, and positive/negative driver columns.
- Added hover tooltips for ambiguous comparison-table terms including debt metric, segment, score types, confidence, data coverage, stage gates, and fallback notes.
- Replaced silent blank comparison-table cells with explicit unresolved-state labels such as `Not found`, `Not loaded`, and `Unclassified`.
- Made tooltip-enabled comparison table headers visibly marked with `(?)` so definitions like peer group, debt metric, and score types are discoverable.
- Normalised key financial display fields through explicit statuses so revenue, market cap, shares, price, and coverage issues can be audited by source and field.
- Prioritised the committed market snapshot before live runtime scraping for broad-universe market cap and shares, with explicit edge-case statuses for preference shares, GDR zero-share rows, suspended securities, and non-constituent matches.
- Added a comparison-table display safety net that fills market cap and shares directly from `data/company_market_snapshot.csv` by ticker when cached or partial metrics are sparse.
- Fixed literal `n/a` cached financial values blocking market-cap and share-count replacement from the committed market snapshot.
- Added canonical LSE ticker normalization, snapshot ingestion runtime audit logging, and `scripts.debug_snapshot_ingestion` to trace a ticker from CSV row to final dashboard row.
- Rehydrate comparison-table callback rows from `data/company_market_snapshot.csv` so paginated pages cannot show stale `n/a` market caps when the snapshot has valid data.
- Made the comparison modal open on a company overview first, with the existing relative peer scorecard moved into a dedicated `Compare To Others` tab.

### Fixed

- Hardened comparison popup and company-search callbacks so malformed refresh payloads, non-numeric scores, noisy search input, and transform failures do not crash the dashboard.
- Hardened comparison modal tab switching by normalising unexpected tab values and reusing cached chart state instead of refetching on every tab return.
- Split comparison modal rendering into separate frame, side-panel, and chart callbacks so peer search and repeated tab switching cannot rebuild the whole popup at once.
- Added modal-specific diagnostics to `logs/dashboard.log` and ignored zero-click pattern callbacks from newly-rendered peer buttons to prevent tab/search state churn.
- Renamed the row action button from `Compare` to `More` to match the overview-first modal behavior.
- Preserved analytical score statuses for expired score-cache rows so stale cache age no longer makes valid `partial` or `full` scores display as `stale`.

### Removed

- Sentiment/AI dashboard columns and heavy model dependencies from the dashboard surface.
- Stale duplicate scripts, old notebooks, generated caches, and Python bytecode artifacts.
