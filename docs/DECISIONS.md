# Decision Log

## 2026-05-01: Fundamentals-First Dashboard

The dashboard now presents a fundamentals-first watchlist view and removes sentiment/AI dashboard sections. This keeps the app lighter, avoids expensive model loads at startup, and makes the primary investment signal easier to review.

## 2026-05-01: Generated Data Is Local Runtime State

Generated logs, caches, snapshots, notebooks, and bytecode are excluded from Git. The repository should track source, configuration, docs, and deterministic tests.
