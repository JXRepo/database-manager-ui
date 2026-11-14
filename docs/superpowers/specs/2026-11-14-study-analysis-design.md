# Difference navigation and saved analyses

The user approved the recommended first two improvements, then asked that the
feature be polished for daily research. This iteration implements those two
features and verifies the full existing study workflow. Parameter axis expansion
remains a later iteration. No scientific inference or raw-data rewrite is added.

## Approach

Extend the existing collection workspace with compact native controls, keeping
Map, Explore and Compare in their current locations. Difference navigation makes
the bounded detailed inspection useful with hundreds of fields. Named analyses
save the researcher's choices and notes beside the collection. URL bookmarks
alone cannot provide names, notes or change warnings; copying all source JSON
would duplicate private data and obscure current access, so neither replaces this
small saved-state model.

## Difference navigation

Add All / Differences / Incomplete filters and field search to detailed inspection.
Use detail_status=all|different|incomplete and detail_q (at most 200 characters).
Native GET controls work without JavaScript; enhancement filters the existing
bounded rows immediately, retains group headers only for visible rows, updates
the visible count, and keeps URL/navigation/save state in sync. Differences are
known unequal values; incomplete includes absent, conflicting or truncated values.
The existing overall inspection counts and limit messages remain visible.

Every row has a stable safe ID derived from its full canonical field path.
Difference summary links open the table and reveal/focus the exact row, clearing
filters when necessary. Keep the field and reference columns fixed while scrolling
across additional records on desktop. Match counts never imply physical equality.

## Saved analyses

SavedStudyAnalysis belongs to a ResearchCollection, inheriting its private owner.
It stores title (1–120 characters, one line), notes (at most 5,000 characters),
validated workspace state, source digests, revision, and creation/update timestamps.
At most 100 analyses per collection, with 12 entries per list page. At least two
and at most four current accessible member IDs are required to save. Temporary
selections retain the existing save-collection action before analysis saving.

Store ordered IDs/reference, map position, candidate criteria, comparison options,
deep inspection filters, and curve component/strain/open/presentation. State is
bounded to 16 KiB and contains only validated known scalar controls. Curve display
controls add curve_view=separate|overlay and curve_open=0|1; explicit incompatible
overlay stays unavailable with its existing explanation.

All create/update/delete actions use POST and CSRF, signed owner-bound collection
navigation, collection transaction locks and current selected member access checks.
Updates/deletes require matching revisions and return 409 with entered text intact
on conflict. Failed/unconfirmed saves retain inputs and never retry automatically.
Saved state never grants access. Opening applies the complete saved selection or
shows a generic unavailable message without disclosing hidden record IDs/titles.
Deleting an analysis never changes its collection or data objects.

Compute per-source MD5 digests in the database over stored JSON after access checks,
without retaining raw JSON or treating the digest as a scientific identity. A
16-MiB actual combined JSON precheck bounds this work; oversized selections retain
individual source access and require fewer or smaller records for analysis saving.
A change to accessible source JSON produces an explicit review warning. Opening a
saved analysis is read-only and never replaces its baseline or notes. Updating is
explicit; save as new remains available. Unsaved state changes remain distinguishable.

Keep save controls collapsed until requested or an error occurs. Provide a compact
analysis selector/list, active name, notes, source-change status and explicit Save
changes / Save as new actions. Preserve state through source return and manual
relationship actions. Notes are the user's own observations, not generated findings.

## Verification and delivery

Use current Django/templates/plain JS, an additive migration and synthetic records.
Test access revocation, source changes, stale revisions, malformed state, limits,
CSRF, full save/open/edit/delete, native controls and signed navigation. Verify
1280/1440/1920 desktop layouts, empty search, long fields and four-record tables.
Run application, PostgreSQL and JS regression suites and independent review before
commit/integration/push under existing delivery authorization. Preserve all plot
and research-reference changes in the main branch. Public deployment checks do
not substitute for authenticated hosted acceptance.
