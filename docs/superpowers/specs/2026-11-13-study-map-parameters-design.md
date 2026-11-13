# Parameter map and detailed recorded settings

The user approved the next iteration with “弄” after choosing the recommended
order: deepen parameter comparison and add a collection parameter map. Named
saved analyses remain a later iteration. This design records the approved short
proposal and the implementation decisions needed to make it concrete.

## Approach

Keep the existing study workspace, candidate search, ordered two-to-four-record
comparison and curve inspection. Add a native Parameter map view and an explicit
Detailed parameters disclosure in Compare. This directly connects whole-collection
discovery to inspecting actual model and boundary values. A generic graph redesign
would not expose parameter coverage; automatic similarity or causal explanations
would exceed what the recorded metadata establishes.

## Detailed parameters

On explicit GET inspection, load the complete selected set only after current
ownership, membership and access checks. Use ordered object locks and a collection
lock, rechecking access after waits. Temporary scopes recheck their entire membership.
Before reading raw JSON, check actual database byte lengths against a combined
16-MiB allowance. Fail the complete inspection with source links when over budget.

Compare supplied constitutive model fields, elastic/plastic/damage parameters and
their supplied units under each actual phase entry, plus complete recorded loading
condition fields and top-level units. Keep phase, condition and array positions;
do not align by names or invent parameter/unit mappings. Canonicalize recognized
schema names only at their actual parents; preserve arbitrary parameter names,
exact numeric text, original types, zero/false, ordering and original JSON.
Conflicting aliases, missing values and truncated content are never complete matches.

Bound traversal and rendering: at most 300 rows, 6,000 visited nodes, depth 30,
32 entries per array and 512 characters per cell. Make omitted content explicit,
retain links to complete source data, and never present bounded coverage as a full
scientific equivalence check. Show a short factual difference summary followed by
the expandable field table. Include ordinary GET navigation without JavaScript.

## Parameter map

First version supports two scalar axes: global temperature and discretization
count, with axis swapping. Temperature retains explicit units; units are selected
separately and never converted or merged. Numeric projection uses original values
and Decimal sorting, not rendered labels or binary floating-point comparisons.
Numeric zero remains valid; invalid, conflicting, absent or unknown-unit values
are counted explicitly outside the grid. Do not collapse multi-phase grain counts.

Use a versioned bounded map projection in collection summaries, prepared through
the existing shared 25-record, 16-MiB, one-second allowance. Warm map aggregation
never reads raw JSON. No partial map counts while preparation is incomplete. Retain existing
operator backfill and ordinary legacy graph compatibility.

Show at most eight values per axis (64 visible cells), exact full-scope counts,
independent axis pages, and native links on populated cells/rows. A selection filters
the existing 25-record member browser; pins persist across cells and pages and open
the existing comparison/curves workflow. Cells count actual accessible records,
not scientific replicates. Empty cells mean no visible records in this collection.
Invalid controls and stale cell references fail explicitly rather than broadening
the displayed members. Canonical map and inspection state survives signed source
return, manual relationship actions and temporary selection saves.

## Delivery

Retain desktop styling and existing detail plots, raw exports and object permissions.
Use the current Django/templates/plain JavaScript stack without new dependencies
or models. Verify precision, unit partitioning, incomplete metadata, access changes,
cache preparation, deep conflicts and limits, signed navigation, real Chromium
1280/1440/1920 workflows and the existing regression suites. Independently review,
commit and integrate the isolated branch, then push under existing delivery consent.
Public deployment checks remain distinct from authenticated hosted acceptance.
