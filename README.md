# Strategic Metals Dashboard

Professional watchlist dashboard for monitoring strategic metals companies with a fundamentals-first scoring model.

## Current Scope

- Dash web dashboard with watchlist KPIs, ranked candidates, filtering, sorting, and score highlighting.
- REE project pipeline, supply-chain ranking tracker, and catalyst tracker for discovery work.
- YAML-driven company universe in `config/tickers.yaml`.
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

## Data Policy

Generated cache files, snapshots, notebooks, and local logs are not intended for source control. Keep source code, configuration, tests, and documentation in Git; keep runtime data in ignored storage folders unless a deliberate fixture is needed.

## Rare Earth Discovery Workflow

Use `config/ree_pipeline.yaml` for manual REEx-derived entries, early-stage candidates, project-stage classification, supply-chain ranking imports, and catalysts. Do not store third-party credentials in this repository.
