# Logging And Tracking

Runtime logs are written to:

```text
logs/dashboard.log
```

The default log level is `INFO`. Override it with:

```powershell
$env:LOG_LEVEL = "DEBUG"
python -m dashboard.dashboard
```

## What To Log

- Data provider failures and retries.
- Dashboard data-load failures.
- Scoring exceptions with ticker context.
- Ticker-universe load size and default top-100 selection source.
- London South East sector-list cache hits, stale-cache fallback, scrape size, and written universe row count.
- Market snapshot load size, stale snapshot count, refresh failures, coverage audit results, and source/status notes used for dashboard display.
- RNS technical-evidence row counts, refresh failures, parser/cache fallbacks, and source announcement counts used for technical scoring.
- Score-cache hits, misses, stale reads, and writes.
- On-demand detail fetches from the search workflow.
- Compact financial refresh batches from the comparison table.
- Search query match counts and search/detail errors.
- Scoring fallback status such as `metadata_only`, `partial`, or `stale`.
- Operational warnings that would help diagnose stale or missing data.

## What Not To Log

- Secrets or API tokens.
- Large raw provider payloads.
- Generated table exports unless explicitly requested.

## Git Policy

The `logs/` directory is kept with `.gitkeep`, but log files are ignored by Git.
