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
- Runtime logging to `logs/dashboard.log`.
- GitHub-ready repository infrastructure, including CI, issue templates, pull request template, `.gitignore`, `.gitattributes`, and `.editorconfig`.
- Project operating docs in `README.md`, `WORKFLOW.md`, `AGENTS.md`, and `docs/`.
- Unit tests for dashboard row building and config-driven ticker loading.

### Changed

- Made `data.load_tickers()` side-effect free so config loading no longer downloads market data.
- Consolidated dashboard data into an explainable rare-earth hybrid scoring model while preserving LSE-backed financial metrics.

### Removed

- Sentiment/AI dashboard columns and heavy model dependencies from the dashboard surface.
- Stale duplicate scripts, old notebooks, generated caches, and Python bytecode artifacts.
