# Agent Operating Guide

This repository is managed as a production-quality dashboard codebase. Future coding agents must preserve the current project shape unless a task explicitly asks for a larger migration.

The goal is to keep this repository safe, reviewable, testable, documented, and maintainable to professional software engineering standards.

---

## 1. Repository-Specific Priorities

These project rules take priority over general guidance in this file.

- Keep `analysis/`, `data/`, and `dashboard/` as the canonical source paths.
- Avoid reintroducing sentiment, assistant, or AI dashboard tabs unless the product owner explicitly asks for them.
- Keep config loading side-effect free.
- Network calls belong in data fetchers, services, or analysis functions, not in configuration modules.
- Treat files in `logs/`, `storage/cache/`, generated snapshots, temporary exports, and runtime artifacts as local/generated files unless explicitly required.
- Add focused tests for dashboard transformations, config behavior, scoring changes, data normalization, and user-visible calculations.
- Preserve the current architecture unless the task specifically requests a refactor or migration.
- Do not introduce new frameworks, package managers, or architectural layers without a clear need.
- Keep documentation practical and aligned with actual operational behavior.
- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.
- Update `WORKFLOW.md` when changing release, branch, review, or deployment practices.

---

## 2. Core Operating Principles

### 2.1 Work Safely

- Do not push directly to `main`, `master`, `production`, or protected release branches.
- Work on a dedicated branch for each logical change.
- Keep changes scoped to the requested task.
- Avoid unrelated rewrites, broad formatting changes, or opportunistic refactors.
- Preserve existing behavior unless the requested task requires changing it.
- Prefer small, understandable changes over large opaque diffs.
- Do not remove tests, validation, logging, error handling, documentation, or security controls unless there is a clear reason.
- Do not ignore failing tests.
- Never commit secrets, credentials, tokens, private keys, passwords, or sensitive environment values.
- Do not commit generated files, build artifacts, caches, logs, temporary files, virtual environments, or editor-specific files unless the repo explicitly requires them.

### 2.2 Be Reviewable

Every meaningful change should make it easy for a reviewer to understand:

- What changed.
- Why it changed.
- How it was tested.
- What risks remain.
- Whether any migration, rollback, deployment, or compatibility concerns exist.

A reviewer should not need to infer intent from the code alone.

### 2.3 Follow Existing Conventions

Before modifying code:

- Inspect the repository structure.
- Identify the existing style, naming, packaging, testing, and documentation conventions.
- Follow the dominant project pattern.
- Reuse existing utilities and abstractions where appropriate.
- Do not introduce duplicate helper functions, parallel config systems, or inconsistent module boundaries.
- If conventions are inconsistent, follow the pattern nearest to the code being changed and document any ambiguity.

---

## 3. Canonical Repository Areas

The expected project shape is:

- `analysis/` — analytical logic, scoring, transformations, calculations, and domain-specific processing.
- `data/` — data loading, fetching, normalization, storage access, and data interfaces.
- `dashboard/` — dashboard UI, views, layout, rendering, and user-facing presentation logic.
- `tests/` — automated tests.
- `docs/` — project documentation, if present.
- `logs/` — local runtime logs; generally not committed.
- `storage/cache/` — local cache data; generally not committed.
- `CHANGELOG.md` — user-visible change history.
- `WORKFLOW.md` — release, branch, review, and operational workflow.

Do not create new top-level directories unless the project already has a convention for them or the task clearly requires it.

---

## 4. Git Rules

### 4.1 Branching

Use clear branch names.

Recommended prefixes:

- `feature/short-description`
- `fix/short-description`
- `hotfix/short-description`
- `chore/short-description`
- `docs/short-description`
- `refactor/short-description`
- `test/short-description`
- `release/version-number`

Examples:

```text
feature/add-critical-minerals-filter
fix/scoring-null-value-handling
docs/update-local-setup
chore/update-dashboard-dependencies
test/add-config-loading-tests
```

Branch rules:

- Use lowercase branch names.
- Use hyphens between words.
- Avoid vague names such as `updates`, `misc`, `changes`, or `final`.
- One branch should represent one logical unit of work.

### 4.2 Commits

Prefer clear, atomic commits.

Recommended format:

```text
type(scope): short imperative summary
```

Recommended types:

- `feat` — new feature.
- `fix` — bug fix.
- `docs` — documentation-only change.
- `style` — formatting-only change.
- `refactor` — restructuring without intended behavior change.
- `test` — tests added or updated.
- `chore` — maintenance task.
- `ci` — CI/CD change.
- `build` — build or dependency change.
- `perf` — performance improvement.
- `security` — security-related fix.

Examples:

```text
feat(dashboard): add supply risk filter
fix(analysis): handle missing scoring weights
docs(workflow): clarify release checklist
test(config): cover environment override behavior
chore(deps): update lockfile
```

Commit rules:

- Use imperative mood: `add`, `fix`, `update`, not `added` or `fixed`.
- Keep the first line concise.
- Explain why in the body when the change is not obvious.
- Do not combine unrelated changes in one commit.
- Do not commit broken intermediate states unless explicitly working in a draft branch.

---

## 5. Pull Request Standards

All meaningful changes should go through a pull request.

### 5.1 Pull Request Title

Use the same style as commit messages:

```text
feat(scope): add capability
fix(scope): resolve defect
docs(scope): update instructions
```

### 5.2 Pull Request Description

A complete PR should include:

```md
## Summary

Briefly describe what changed.

## Reason

Explain why the change was needed.

## Changes

- List key implementation changes.
- Mention important files or modules touched.

## Testing

Commands run:

```powershell
python -m compileall analysis data dashboard tests
python -m pytest
```

Additional validation, if any:

## Risk

Risk level: Low / Medium / High

Notes:

## Rollback

Describe how to revert or mitigate if needed.

## Checklist

- [ ] Code follows existing project conventions.
- [ ] Tests added or updated where appropriate.
- [ ] Existing tests pass.
- [ ] Documentation updated where appropriate.
- [ ] `CHANGELOG.md` updated for user-visible changes.
- [ ] `WORKFLOW.md` updated for workflow/release/review changes.
- [ ] No secrets or sensitive data committed.
- [ ] Runtime artifacts, logs, caches, and generated snapshots excluded unless intentional.
- [ ] Backward compatibility considered.
```

### 5.3 Pull Request Size

Prefer small PRs.

Avoid mixing:

- Feature work and broad refactors.
- Dependency updates and behavior changes.
- Formatting-only changes and logic changes.
- Documentation cleanup and functional changes.

Split large changes into staged PRs when practical.

---

## 6. Verification

Run these before opening a pull request:

```powershell
python -m compileall analysis data dashboard tests
python -m pytest
```

When relevant, also run project-specific commands for:

- Formatting.
- Linting.
- Type checking.
- Dashboard build or launch validation.
- Data transformation validation.
- Snapshot or fixture regeneration.

If a command cannot be run, state why clearly in the PR or final agent response.

Do not claim tests passed unless they were actually run.

---

## 7. Testing Standards

Every behavior change should include or update tests.

Prioritize tests for:

- Dashboard transformations.
- Config behavior.
- Scoring changes.
- Data normalization.
- Data fetching boundaries.
- Error handling.
- User-visible calculations.
- Regression cases for fixed bugs.

Test rules:

- Tests should be deterministic.
- Tests should avoid real network calls unless explicitly integration-level.
- Use fixtures or mocks for external data.
- Do not weaken or delete tests simply to make the suite pass.
- Bug fixes should include a regression test where practical.
- Keep tests focused on behavior, not incidental implementation details.

For config-related tests:

- Confirm config loading has no unintended side effects.
- Confirm environment overrides behave correctly.
- Confirm missing or invalid config fails clearly where appropriate.

For data-related tests:

- Avoid depending on live external services.
- Use stable fixtures.
- Validate schema assumptions.
- Cover nulls, missing fields, malformed values, and edge cases.

---

## 8. Configuration Standards

Config loading must remain side-effect free.

Configuration modules should:

- Read and validate configuration.
- Define defaults.
- Expose structured config objects or values.
- Avoid network calls.
- Avoid database calls.
- Avoid file writes.
- Avoid starting jobs, sessions, dashboards, or long-running processes.

Network calls belong in:

- Data fetchers.
- Service clients.
- Analysis functions.
- Explicit runtime workflows.

Configuration should be:

- Explicit.
- Documented.
- Environment-aware.
- Validated before use.
- Free of committed secrets.

Use `.env.example` or equivalent documentation for required environment variables. Never commit real `.env` files.

---

## 9. Data and Runtime Artifact Rules

Treat the following as local/generated unless explicitly required:

- `logs/`
- `storage/cache/`
- Generated snapshots.
- Temporary exports.
- Local runtime databases.
- Local dashboard session files.
- Build outputs.
- Python cache directories.
- Test cache directories.

Before committing generated data, verify:

- The file is intentionally versioned.
- It is stable and reproducible.
- It does not contain secrets.
- It does not contain private or sensitive data.
- Its generation process is documented.

Prefer small fixtures over large raw data files.

---

## 10. Dashboard Standards

Dashboard changes should be:

- Focused.
- Tested where transformation logic is involved.
- Consistent with existing layout and navigation.
- Free of unrelated tabs or product areas.
- Clear in empty, loading, and error states.
- Conservative with new dependencies.

Do not reintroduce sentiment, assistant, or AI dashboard tabs unless the product owner explicitly requests them.

When changing dashboard behavior:

- Check whether the change affects user-visible calculations.
- Update tests for transformations or computed outputs.
- Update documentation if user workflow changes.
- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.

---

## 11. Analysis and Scoring Standards

Analysis code should be:

- Deterministic where possible.
- Easy to test.
- Clear about assumptions.
- Explicit about units, scales, weights, and thresholds.
- Robust to missing, null, or malformed data.
- Separated from presentation logic.

For scoring changes:

- Add focused tests.
- Document changed assumptions.
- Preserve backward compatibility where possible.
- Update user-facing documentation if interpretations change.
- Update `CHANGELOG.md` under `Unreleased`.

Avoid burying business logic inside dashboard rendering code.

---

## 12. Data Fetching Standards

Data fetching should be separated from:

- Config loading.
- Dashboard rendering.
- Pure transformation logic.
- Static module import side effects.

Data fetchers should:

- Handle network errors clearly.
- Use timeouts where applicable.
- Avoid silent failures.
- Avoid logging sensitive values.
- Return predictable structures.
- Be testable with mocked responses or fixtures.

Do not make live network calls in tests unless the test is explicitly marked as an integration test and the project supports that pattern.

---

## 13. Documentation Standards

Update documentation in the same PR as code changes when behavior changes.

Documentation should be:

- Practical.
- Accurate.
- Close to operational behavior.
- Clear enough for a new maintainer to follow.
- Free of stale aspirational instructions.

Update documentation when changing:

- Setup steps.
- Config behavior.
- Environment variables.
- Data sources.
- Dashboard behavior.
- Scoring methods.
- Release process.
- Branch or review process.
- Test commands.
- Deployment assumptions.

Specific files:

- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.
- Update `WORKFLOW.md` for release, branch, review, or process changes.
- Update `README.md` for setup, usage, or project overview changes.
- Update comments/docstrings when behavior is non-obvious.

Use comments to explain why, not what.

---

## 14. Changelog Standards

For user-visible changes, update `CHANGELOG.md` under `Unreleased`.

Recommended sections:

```md
## [Unreleased]

### Added
### Changed
### Fixed
### Removed
### Security
```

Rules:

- Keep entries concise.
- Describe user-visible impact.
- Do not include noisy internal-only changes unless they affect maintainers or operations.
- Move entries into a versioned section during release.

---

## 15. Workflow Documentation Standards

Update `WORKFLOW.md` when changing:

- Branch strategy.
- Pull request requirements.
- Review process.
- Release process.
- Deployment process.
- Versioning policy.
- CI/CD expectations.
- Required validation commands.

Do not let `WORKFLOW.md` drift from actual practice.

---

## 16. Dependency Management

Before adding a dependency, verify:

- It is necessary.
- It does not duplicate existing functionality.
- It is actively maintained.
- It has an acceptable license for the project.
- It does not introduce unnecessary security, size, or operational risk.
- It works with the project’s supported Python/runtime versions.

When updating dependencies:

- Keep dependency changes separate from feature work where practical.
- Update lockfiles consistently.
- Review breaking changes for major version updates.
- Run the verification commands.
- Update documentation if setup or behavior changes.

Do not introduce a new package manager unless explicitly requested.

---

## 17. Security Standards

Never commit:

- API keys.
- Access tokens.
- Passwords.
- Private keys.
- Cloud credentials.
- Database URLs containing credentials.
- Production `.env` files.
- Customer data.
- Sensitive personal data.
- Session cookies.
- OAuth secrets.

Security-sensitive changes require extra care when touching:

- Authentication.
- Authorization.
- Secrets.
- External APIs.
- File uploads/downloads.
- Data storage.
- CI/CD permissions.
- Deployment workflows.
- Admin functionality.
- User data.
- Logging.

Do not log secrets or sensitive data.

Use placeholders in examples:

```text
API_KEY=replace-with-your-api-key
DATABASE_URL=postgres://user:password@localhost:5432/app
```

---

## 18. Error Handling Standards

Errors should be:

- Clear.
- Actionable.
- Consistent with existing project behavior.
- Safe to show to the intended audience.
- Logged at the appropriate level where logging exists.

Rules:

- Do not silently swallow exceptions.
- Do not expose sensitive details in user-facing errors.
- Preserve original error context where useful.
- Add tests for important error paths.
- Avoid broad catch-all handling unless there is a clear recovery path.

---

## 19. Logging Standards

Logs should support debugging and operations without exposing sensitive data.

Log useful information such as:

- Data fetch failures.
- Validation failures.
- Scoring or transformation failures.
- Startup/runtime milestones.
- Retry exhaustion.
- Unexpected external service responses.

Do not log:

- Secrets.
- Tokens.
- Passwords.
- Private keys.
- Full credential-bearing URLs.
- Sensitive user or customer data.

Remember that `logs/` is treated as a local runtime artifact path.

---

## 20. Performance Standards

Consider performance when changing:

- Data transformations.
- Dashboard rendering.
- Large dataframe operations.
- File reads/writes.
- Network calls.
- Cache behavior.
- Repeated calculations.
- Startup/import paths.

For performance-sensitive changes:

- Avoid unnecessary recomputation.
- Prefer clear, measurable improvements.
- Add tests or benchmarks where practical.
- Do not optimize prematurely at the cost of clarity.
- Document trade-offs when relevant.

---

## 21. Compatibility Standards

Before changing behavior, consider compatibility with:

- Existing data files.
- Existing config files.
- Existing dashboard workflows.
- Existing tests and fixtures.
- Existing deployment assumptions.
- Existing user expectations.

For breaking changes:

- Document the change.
- Update `CHANGELOG.md`.
- Update relevant docs.
- Provide migration notes where practical.
- Keep the change as small and explicit as possible.

---

## 22. Generated Code, Snapshots, and Fixtures

Generated files should be handled deliberately.

Rules:

- Prefer updating the source or generator rather than editing generated output by hand.
- Regenerate snapshots only when behavior intentionally changes.
- Keep fixtures minimal and stable.
- Do not commit large generated artifacts unless required.
- Document how generated files are produced if they are committed.

Generated snapshots should not be treated as canonical source unless the repo explicitly defines them that way.

---

## 23. CI/CD Standards

If CI/CD exists or is added, it should validate:

- Python compilation.
- Test suite execution.
- Linting, if configured.
- Formatting, if configured.
- Type checking, if configured.
- Build or dashboard startup checks, if configured.
- Dependency/security checks, if configured.

CI rules:

- Do not bypass failing CI without a documented reason.
- Do not disable tests to pass CI.
- Keep CI commands aligned with local verification commands.
- Update `WORKFLOW.md` when CI expectations change.
- Keep CI jobs clear and maintainable.

---

## 24. Pull Request Review Standards

Review for:

- Correctness.
- Scope control.
- Test coverage.
- Dashboard behavior.
- Config side effects.
- Data fetching boundaries.
- Security.
- Error handling.
- Documentation.
- Backward compatibility.
- Maintainability.

Do not approve changes that:

- Reintroduce removed product areas without explicit request.
- Move canonical code out of `analysis/`, `data/`, or `dashboard/` without a migration plan.
- Add live network calls to config loading.
- Commit logs, cache files, or runtime artifacts unintentionally.
- Remove tests without justification.
- Add dependencies without justification.
- Make broad unrelated rewrites.

---

## 25. Agent Workflow

### 25.1 Before Making Changes

Before editing:

1. Read this file.
2. Inspect the repository structure.
3. Identify the relevant modules in `analysis/`, `data/`, and `dashboard/`.
4. Read relevant docs, especially `README.md`, `WORKFLOW.md`, and `CHANGELOG.md` if present.
5. Locate relevant tests.
6. Identify the smallest safe change.
7. Check whether the change is user-visible and requires a changelog entry.
8. Check whether the change affects workflow and requires `WORKFLOW.md`.

### 25.2 While Making Changes

While editing:

- Keep diffs minimal.
- Preserve existing project shape.
- Follow existing naming and style.
- Avoid unrelated formatting.
- Add or update focused tests.
- Keep config loading side-effect free.
- Keep network calls out of config modules.
- Avoid reintroducing removed dashboard tabs or product concepts.
- Avoid speculative abstractions.
- Update docs close to the changed behavior.

### 25.3 After Making Changes

Before finishing:

1. Run:

   ```powershell
   python -m compileall analysis data dashboard tests
   python -m pytest
   ```

2. Run any additional relevant project checks.
3. Review the diff.
4. Confirm no secrets were added.
5. Confirm no logs, caches, or generated runtime artifacts were committed unintentionally.
6. Confirm docs are updated where needed.
7. Confirm `CHANGELOG.md` is updated for user-visible changes.
8. Confirm `WORKFLOW.md` is updated for process changes.
9. Summarize what changed.
10. Report exact verification commands and results.
11. Report any known limitations or tests not run.

### 25.4 When Unsure

If requirements are ambiguous:

- Prefer the least invasive change.
- State assumptions clearly.
- Do not invent product requirements.
- Do not make destructive changes.
- Do not perform large migrations without explicit instruction.
- Ask for clarification when necessary.
- If blocked by missing credentials, services, or local environment, explain exactly what is missing.

---

## 26. Do Not Do

Do not:

- Push directly to protected branches.
- Disable or weaken tests to make them pass.
- Commit secrets.
- Commit logs, caches, local snapshots, or runtime artifacts unintentionally.
- Add unrelated features.
- Reformat the whole repository unnecessarily.
- Rewrite architecture without explicit instruction.
- Reintroduce sentiment, assistant, or AI dashboard tabs without product-owner approval.
- Put network calls in config loading.
- Hide data-fetching side effects in imports.
- Change scoring logic without tests.
- Change dashboard transformations without tests.
- Change release or review practices without updating `WORKFLOW.md`.
- Make user-visible changes without updating `CHANGELOG.md`.
- Add new dependencies without justification.
- Leave temporary debugging code.
- Ignore failing tests.
- Mask real errors with broad exception handling.
- Delete migrations, fixtures, or tests without justification.
- Assume production credentials or external service access.

---

## 27. Definition of Done

A change is complete only when:

- The requested problem is solved.
- The diff is scoped and reviewable.
- Existing project shape is preserved unless a migration was requested.
- Relevant tests are added or updated.
- Verification commands pass, or failures are clearly explained.
- Config loading remains side-effect free.
- Network calls remain outside config modules.
- Runtime artifacts are not committed unintentionally.
- Documentation is updated where needed.
- `CHANGELOG.md` is updated for user-visible changes.
- `WORKFLOW.md` is updated for process changes.
- Security impact is considered.
- Dependency impact is considered.
- Backward compatibility is considered.
- Known risks or limitations are documented.