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
- Score-cache hits, misses, stale reads, and writes.
- On-demand detail fetches from the search workflow.
- Search query match counts and search/detail errors.
- Scoring fallback status such as `metadata_only`, `partial`, or `stale`.
- Operational warnings that would help diagnose stale or missing data.

## What Not To Log

- Secrets or API tokens.
- Large raw provider payloads.
- Generated table exports unless explicitly requested.

## Git Policy

The `logs/` directory is kept with `.gitkeep`, but log files are ignored by Git.
