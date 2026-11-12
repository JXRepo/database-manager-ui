# Collection Release Hardening Implementation Plan

**Goal:** Fix concurrent selection loss and repeated large-JSON graph work, then
verify the corrected module against realistic synthetic data and PostgreSQL.

**Architecture:** Transactional session-bound selection buckets and persistent
scalar collection summaries, with incremental legacy handling.

**Tech Stack:** Existing Django, PostgreSQL, SQLite and Chromium tooling.

**Spec:** [Design](../specs/2026-11-12-collection-release-hardening-design.md).

- [x] Reproduce the temporary-selection overwrite and implement locked database
  buckets with legacy adoption, expiry and unchanged access/capacity checks.
- [x] Add nullable collection summaries, write-path refresh/invalidation and
  transactional incremental backfill; verify exact grouping semantics.
- [x] Run selection races and capacity checks in an isolated local PostgreSQL
  database, with no production credentials or records.
- [x] Measure raw and summarized graph builds for a 1,000-object long-curve
  dataset; record query behavior, wall time and memory with dataset dimensions.
- [x] Run relevant SQLite, PostgreSQL and Chromium regressions, then review the
  complete diff independently and fix material findings.
- Record results and deployment limits, commit the reviewed changes, push,
  and distinguish verified public health/static checks from authenticated release
  acceptance.
