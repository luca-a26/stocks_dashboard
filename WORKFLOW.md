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

## Release Process

1. Move `CHANGELOG.md` items from `Unreleased` into a dated version section.
2. Tag the release after merge, for example `v0.1.0`.
3. Capture dashboard screenshots and attach them to the release notes when the UI changes.

## Data Handling

- Do not commit `logs/`, `storage/cache/`, generated snapshots, or exploratory notebooks.
- Keep small deterministic fixtures in `tests/fixtures/` if tests need sample data.
- Document new data providers in `docs/ARCHITECTURE.md`.
