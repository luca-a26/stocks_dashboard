# Strategic Metals Dashboard

Professional watchlist dashboard for monitoring strategic metals companies with a fundamentals-first scoring model.

## Current Scope

- Dash web dashboard with top-100 KPIs, ranked candidates, filtering, sorting, and score highlighting.
- Searchable ticker-universe metadata layer designed for 1,000+ companies without loading fundamentals at startup.
- REE project pipeline, supply-chain ranking tracker, and catalyst tracker for discovery work.
- Curated watchlist in `config/tickers.yaml`; scalable metadata universe in `config/ticker_universe.csv`.
- YAML-driven discovery workflow in `config/ree_pipeline.yaml`.
- Runtime logging to `logs/dashboard.log`.
- GitHub-ready workflow, CI, issue templates, pull request template, and contribution standards.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m dashboard.dashboard
```

The dashboard runs locally at the URL printed by Dash, usually `http://127.0.0.1:8050`.

## Project Layout

```text
analysis/          Scoring and analytical model code
config/            Watchlist and runtime configuration
dashboard/         Dash app and dashboard assets
data/              Data access, config helpers, storage helpers, logging
docs/              Architecture, logging, and operating notes
tests/             Unit tests for dashboard and configuration behavior
logs/              Local runtime logs, ignored by Git except .gitkeep
storage/           Local caches and generated snapshots, ignored by Git except .gitkeep
```

## Verification

```powershell
python -m compileall analysis data dashboard tests
python -m pytest
```

## Methodology

The scoring, rating bands, display calculations, chart counts, and manual discovery workflow are documented in `docs/METHODOLOGY.md`.

The current company score is a rare-earth hybrid composite:

```text
technical_asset_score * 55%
commercial_financial_score * 25%
strategic_supply_chain_score * 20%
```

The dashboard also exposes score status, confidence, missing data, stage gates, and explanation bullets so scores remain auditable.

## Ticker Universe And Lazy Fundamentals

The dashboard separates cheap company metadata from expensive market data:

- `config/ticker_universe.csv` holds searchable metadata such as ticker, exchange, company name, country, commodity tags, supply-chain role, stage, market-cap tier, source, and notes.
- `config/tickers.yaml` remains the curated priority watchlist.
- `config/ree_pipeline.yaml` enriches project-stage and supply-chain context.
- `storage/cache/lse/` stores downloaded LSE JSON/PDF payloads.
- `storage/cache/scores/` stores on-demand scored ticker detail payloads.

Startup shows the top 100 ranked companies from cached scores when available, then metadata/watchlist fallback ranking. Full LSE fundamentals are fetched only when a user searches, selects a company, and clicks `Load Details`. Loaded companies can then be added to the ranked candidates table.

Set cache expiry with:

```powershell
$env:SCORE_CACHE_TTL_HOURS=6
```

`score_status` distinguishes `full`, `partial`, `metadata_only`, and `stale` rows so preliminary scores are never hidden as full fundamentals. Metadata-only companies are capped at 5.5 unless verified technical fields are present.

## Data Policy

Generated cache files, snapshots, notebooks, and local logs are not intended for source control. Keep source code, configuration, tests, and documentation in Git; keep runtime data in ignored storage folders unless a deliberate fixture is needed.

## Rare Earth Discovery Workflow

Use `config/ree_pipeline.yaml` for manual REEx-derived entries, early-stage candidates, project-stage classification, supply-chain ranking imports, and catalysts. Do not store third-party credentials in this repository.
