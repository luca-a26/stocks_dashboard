# Strategic Metals Dashboard

Professional watchlist dashboard for monitoring strategic metals companies with a rare-earth-specific hybrid scoring model.

## Current Scope

- Dash web dashboard with comparison-universe KPIs, ranked candidates, filtering, sorting, and score highlighting.
- Searchable ticker-universe metadata layer designed for 1,000+ companies without loading fundamentals at startup.
- REE project pipeline, supply-chain ranking tracker, and catalyst tracker for discovery work.
- Curated watchlist in `config/tickers.yaml`; scalable metadata universe in `config/ticker_universe.csv`.
- Optional London South East Industrial Metals sector import for a broad LSE company universe.
- YAML-driven discovery workflow in `config/ree_pipeline.yaml`.
- Runtime logging to `logs/dashboard.log`.
- RNS-derived technical evidence for mineralogy, recovery, impurity/radioactivity, resource confidence, study stage, and processing depth.
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

The hybrid model is enhanced by a workbook-style benchmark layer for deposit value, NPV, reserve/resource value, downstream revenue, production visibility, NdPr/DyTb exposure, and peer-group context. The dashboard also exposes score status, confidence, missing data, stage gates, benchmark score, peer group, and explanation bullets so scores remain auditable.

Technical evidence that market feeds do not carry is loaded from recent RNS evidence. Tracked analyst-reviewed entries live in `config/rns_technical_evidence.csv`; automated refresh output can be written to `data/rns_technical_evidence.csv`. These fields feed the same technical asset score rather than a separate score, and are shown directly in the table and company overview.

The relative peer comparison popup is separate from the hybrid score. Click a company row in the scoreboard to open a company card, then add up to three more peers. The popup converts existing hybrid score signals into five equal-weight 1-5 relative criteria: grade/deposit quality, commodity price outlook, jurisdiction, dilution risk, and application/strategic relevance. Optional criterion-level analyst overrides live in `config/relative_score_overrides.csv`.

## Ticker Universe And Lazy Fundamentals

The dashboard separates cheap company metadata from expensive market data:

- `config/ticker_universe.csv` holds searchable metadata such as ticker, exchange, company name, country, commodity tags, supply-chain role, stage, market-cap tier, source, and notes.
- `data/company_market_snapshot.csv` and `data/company_market_snapshot.json` hold the canonical refreshed market snapshot used before live scraping. The snapshot stores market cap, shares in issue, source URL, status, snapshot date, and optional price/volume/range fields.
- `storage/cache/london_south_east/industrial_metals_universe.csv` is an ignored generated cache of the London South East Industrial Metals sector constituents.
- `config/tickers.yaml` remains the curated priority watchlist.
- `config/ree_pipeline.yaml` enriches project-stage and supply-chain context.
- `config/rns_technical_evidence.csv` and optional `data/rns_technical_evidence.csv` supply RNS-derived technical fields such as mineralogy, metallurgical testwork, recovery, impurity profile, resource confidence, study stage, capex/opex, and processing depth.
- `storage/cache/lse/` stores downloaded LSE JSON/PDF payloads.
- `storage/cache/rns/` stores cached London Stock Exchange RNS article pages used during deliberate technical-evidence refreshes.
- `storage/cache/scores/` stores on-demand scored ticker detail payloads.

Startup shows the full merged comparison universe from cached scores when available, then London South East sector metadata, tracked metadata, and watchlist fallback ranking. The compact search bar above the dashboard filters the comparison table by company, ticker, exchange, commodity, country, role, status, rating, or source.

Full fundamentals remain lazy. The default comparison table uses metadata scores for companies without fetched detail so the LSE Industrial Metals list can be compared quickly. Basic market fields are loaded from the canonical market snapshot before any fragile runtime scraping. Use the compact `Load financials` control to fetch revenue LFY, debt metrics, and any remaining fields for the current search result set. LSE is the primary detailed source; sparse rows are enriched from the LSE public company pages, Yahoo Finance fallback data, London South East share pages, and the London South East sector cache where possible. The refresh writes results into `storage/cache/scores/`, and the refresh batch size defaults to 100 rows:

```powershell
$env:FINANCIAL_REFRESH_LIMIT=100
```

Set cache expiry with:

```powershell
$env:SCORE_CACHE_TTL_HOURS=6
```

Dashboard runtime live market refresh is disabled by default so page loads do not repeatedly scrape every company. Enable it only when you deliberately want missing/stale metadata rows to call live fallback sources during startup:

```powershell
$env:ENABLE_LIVE_MARKET_REFRESH=true
```

Financial fields are normalised through a field-owned pipeline in `data/financial_pipeline.py`. Each key field carries provenance, source rank, status, confidence, and notes. Market cap is computed as `normalised price x shares outstanding` when both inputs are valid, with GBp prices converted to GBP first. Manual corrections can be added in:

```text
config/company_financial_overrides.csv
```

Override rows include `ticker`, `field`, `value`, `currency`, `unit`, `source_url`, `source_name`, `confidence`, `notes`, and verification dates. High-confidence or `force` notes can override populated automated values; otherwise overrides only fill missing fields.

Refresh RNS-derived technical evidence manually with:

```powershell
python -m scripts.refresh_rns_technical_evidence --input config/ticker_universe.csv --output-csv data/rns_technical_evidence.csv --output-json storage/audit/rns_technical_evidence_audit.json
```

Dashboard startup does not scrape RNS pages by default. Enable live RNS technical refresh only for deliberate update sessions:

```powershell
$env:ENABLE_RNS_TECHNICAL_REFRESH=true
$env:RNS_CACHE_TTL_HOURS=24
```

Refresh the canonical market snapshot manually with:

```powershell
python -m scripts.refresh_company_market_snapshot --input data/company_market_snapshot.csv --output-csv data/company_market_snapshot.csv --output-json data/company_market_snapshot.json --audit-output storage/audit/company_market_snapshot_audit.json --force-refresh
```

Trace a ticker from CSV row to final dashboard row with:

```powershell
python -m scripts.debug_snapshot_ingestion --tickers BHP RIO PREM RBW ZNWD FOX ZCC 70GD SAUD
```

GitHub Actions runs the same refresh every three hours, commits changed snapshot files, and uploads the coverage audit artifact. Snapshot settings:

```powershell
$env:MARKET_SNAPSHOT_PATH="data/company_market_snapshot.csv"
$env:MARKET_SNAPSHOT_MAX_AGE_HOURS=6
$env:MARKET_SNAPSHOT_REQUIRED_COVERAGE=0.95
```

Refresh the London South East sector universe with:

```powershell
python -m data.london_south_east
```

The dashboard uses that cached sector list when present, then merges the tracked metadata CSV, curated watchlist, and REE pipeline on top. This keeps startup lightweight: the sector scrape only downloads the constituents page, and detailed LSE market/fundamental data is still loaded on demand for selected tickers.

Set the sector-list cache expiry with:

```powershell
$env:LSE_SECTOR_CACHE_TTL_DAYS=7
```

`score_status` distinguishes `full`, `partial`, `metadata_only`, and `stale` rows so preliminary scores are never hidden as full fundamentals. Metadata-only companies are capped at 5.5 unless verified technical fields are present.

## Data Policy

Generated cache files, ad hoc snapshots, notebooks, and local logs are not intended for source control. Keep source code, configuration, tests, and documentation in Git; keep runtime data in ignored storage folders unless a deliberate fixture is needed. The exception is the canonical market snapshot in `data/company_market_snapshot.csv` and `data/company_market_snapshot.json`, which is an intentional committed data resource refreshed by automation.

## Rare Earth Discovery Workflow

Use `config/ree_pipeline.yaml` for manual REEx-derived entries, early-stage candidates, project-stage classification, supply-chain ranking imports, and catalysts. Do not store third-party credentials in this repository.
