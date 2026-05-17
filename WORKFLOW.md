# Development Workflow

## Branching

- `main` should stay releasable.
- Use short feature branches such as `feature/dashboard-refresh` or `fix/config-loader`.
- Keep pull requests focused on one product or infrastructure change.

## Pull Requests

Every pull request should include:

- A short summary of user-facing changes.
- Screenshots for dashboard UI changes.
- Test evidence from `python -m compileall analysis data dashboard tests` and `python -m pytest`.
- Notes on any data-source, logging, or configuration impact.

## Quality Gates

Before merge:

1. CI must pass.
2. Dashboard imports must not trigger live finance/network calls.
3. Runtime artifacts must remain ignored by Git.
4. `CHANGELOG.md` must be updated for user-visible behavior changes.
5. Market snapshot changes should include a coverage audit when the refresh workflow or canonical data shape changes.
6. RNS technical-evidence changes should include source URLs, extraction notes, and parser tests when mineralogy, recovery, impurity, resource, or study-stage fields are affected.

## Release Process

1. Move `CHANGELOG.md` items from `Unreleased` into a dated version section.
2. Tag the release after merge, for example `v0.1.0`.
3. Capture dashboard screenshots and attach them to the release notes when the UI changes.

## Data Handling

- Do not commit `logs/`, `storage/cache/`, generated snapshots, or exploratory notebooks.
- `data/company_market_snapshot.csv` and `data/company_market_snapshot.json` are intentional committed data resources refreshed by scheduled automation.
- `data/rns_technical_evidence.csv`, when present, is an intentional generated technical-evidence resource refreshed by scheduled automation and backed by source RNS URLs.
- `storage/audit/` holds generated coverage-audit artifacts and should stay ignored.
- Keep small deterministic fixtures in `tests/fixtures/` if tests need sample data.
- Document new data providers in `docs/ARCHITECTURE.md`.
