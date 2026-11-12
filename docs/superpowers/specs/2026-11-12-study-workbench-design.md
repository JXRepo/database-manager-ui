# Materials study workbench

The user asked for another release audit and a distinctive improvement beyond
imitating NovaCrate. They explicitly chose **cross-data exploration and comparison**
as this iteration's priority. The existing release audit found no new proven code
blocker and confirmed deployed assets/routes, but authenticated hosted acceptance
and redeployment persistence remain separate from local test evidence.

## Product decision

Visual polish alone would leave the workflow unchanged. A general RO-Crate editor
would duplicate NovaCrate's existing strength and broaden the platform's purpose.
Build a materials study workspace: select a few simulation records from a large
collection, inspect their recorded setup differences, and follow their existing
relationships and source data. This is a focused workflow for this platform's
permission-controlled simulation database, not a claim of universal superiority.

The current iteration includes bounded recorded-metadata comparison, selection
across pages, graph context, an accessible desktop workspace and snapshot export.
Embedded response overlays, inferred scientific comparability, causal conclusions,
ontology validation and new annotation rationale fields are outside this iteration.
Existing individual response plots remain reachable through their detail links.

## Interaction

- Collections and temporary selections retain their routes and access rules.
- Pin up to four accessible members across browser pages and searches. The first
  is the reference; reorder the reference or remove a pin explicitly.
- One selection is a useful waiting state. Two to four selections show the
  comparison matrix. Invalid, duplicate, inaccessible or nonmember IDs reject the
  whole comparison without dropping records or presenting a partial comparison.
- Explore and Compare are ordinary GET modes enhanced by JavaScript. The URL
  stores one canonical `compare=ID,ID,...`, mode and browser state. Signed return
  context preserves them through object details, graph pages and copied links.
- Explore can focus its bounded graph on the pinned records. It displays only
  actual existing membership and manual connections, without inferred edges.
- Compare groups reported material/microstructure, simulation setup and output
  availability. Rows distinguish same recorded values, different recorded values
  and incomplete information. Difference-only mode retains incomplete rows.
- Phase and loading entries retain their original parent/index contexts. Names
  do not align phases automatically. Units remain explicit; equal labels and
  matched metadata never imply scientifically comparable simulations.
- Source field paths and links to original metadata/curves make values inspectable.
  A separate CSV exports the displayed metadata snapshot and status, with safe
  spreadsheet text. Original JSON downloads remain unchanged.

## Data and performance

Extend the internal scalar `collection_summary` projection with version 2 and a
bounded comparison payload. Prepare it on upload/save; the deployment backfill
upgrades old summaries in batches. Ordinary graphs can still read legacy summaries.
Comparison requests upgrade only their selected records using the existing
25-record, 16-MiB actual-JSON-byte and one-second boundary limits. Unknown/oversized
records require operator preparation rather than unbounded array reads.

The comparison projection has 16 rows: software/version, phase entries, texture,
lattice structure, grain counts, elastic/plastic model names, RVE size/continuity,
discretization type/count, temperature, paired mechanical loading, explicit units
and output availability. Each row retains up to eight entries and 240 characters
per displayed value; total projection is bounded to 32 KiB. Missing, ambiguous
or truncated values are visibly distinct and never classified as a complete match.
Typed fingerprints retain order/type distinctions; display truncation cannot
create a false equality. No mechanical arrays are retained in the projection.

Preparation feedback belongs to the selected comparison and must not replace the
collection's full accessible-member count. Every comparison read/export validates
the complete selection against current access and membership. Temporary export
also respects the existing full-selection access rule.

## Visual direction

Use a compact study header, a restrained member browser, a pinned-record rail and
one main Explore/Compare workspace. The comparison matrix is the distinctive
element; avoid decorative statistics cards and marketing sections. Reduce the
vertical separation between choosing records and inspecting them.

Palette: paper `#ffffff`, cool background `#f5f7fb`, ink `#25354b`, selected study
teal `#087f8c`, recorded-difference amber `#b7791f`, existing manual-edge purple
`#8054a8`. Retain the application font and global navigation. State labels and
keyboard focus accompany color. No new fonts or dependencies. Verify desktop
widths 1280, 1440 and 1920, including long metadata and empty selections.

## Evidence

Backend tests cover typed projections, parent contexts, ambiguity, limits, cache
versioning, permissions, complete-selection failures and safe exports. Real
Chromium tests cover cross-page/search pins, reference changes, filtering, native
GET flows, graph/detail return context, downloads and actual desktop layout.
Run relevant existing collection/manual graph regression checks; independently
review new boundaries before committing and pushing. Do not equate a push,
public health check or static asset match with authenticated hosted acceptance.
