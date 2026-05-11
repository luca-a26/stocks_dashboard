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
- Operational warnings that would help diagnose stale or missing data.

## What Not To Log

- Secrets or API tokens.
- Large raw provider payloads.
- Generated table exports unless explicitly requested.

## Git Policy

The `logs/` directory is kept with `.gitkeep`, but log files are ignored by Git.
