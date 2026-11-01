# Tensor panel cleanup — 2026-11-01

Removed the visible motion caption and supplementary Load details disclosure
from the interactive tensor panel in `templates/pages/data_detail.html`, together
with their CSS and JavaScript handling in
`static/assets/js/mechanical-bc-tensor-panel.js`.

The matrix, action selection, load record selection, animation and original JSON
remain available. Animation amplitude remains illustrative and independent of
the supplied magnitude. Native fallback details remain available without
JavaScript. README and AGENTS guidance now reflect the requested removal.

## Verification

- The updated compact-panel check failed before implementation because both
  removed elements were still present, then passed after the change.
- All 137 JavaScript tests passed, including the Chromium tensor panel and the
  existing check that changing xx from 15 to 15,000 does not scale the motion.
- All 12 focused Django tests passed, including the full boundary viewer in
  Chromium at 1280, 1440 and 1920 pixels. Checks covered Pull, Push, Shear,
  combinations, selections, multiple records, exact reset, long metadata, empty
  data, original exports and operation without JavaScript. Browser errors: zero.
- The original tensor panel and a long mixed-data desktop screenshot were
  visually inspected; the removed footer is absent and controls remain aligned.
- The full Django suite ran 903 tests with no skips and 15 existing failure
  entries, including subtests. No new failures appeared compared with the prior
  search verification. All browser cases passed in this run.

## Existing failures

The following methods still assert obsolete upload wording or a previous cube
geometry source string. They also failed in the earlier unchanged baseline
verification recorded in `2026-11-01-search-performance.md`.

In `apps.pages.test_upload_identifiers.UploadIdentifierTests`:

- `test_explicit_duplicate_identifiers_in_one_file_reject_the_whole_file`
- `test_explicit_duplicates_reject_the_file_without_reserving_ids_for_later_files`
- `test_generated_and_supplied_identifiers_share_the_same_namespace`
- `test_malformed_identifiers_are_reported_instead_of_replaced`
- `test_other_missing_fields_reject_all_objects_in_the_file`
- `test_reordered_keys_and_optional_fields_do_not_change_identifier`
- `test_repeated_generated_content_across_files_is_reported`
- `test_repeated_generated_content_in_one_file_is_reported`
- `test_supplied_ronak_identifier_and_generated_identifier_conflict_in_either_order`

In `apps.pages.tests.JSONDataSharingTests`:

- `test_detail_cube_uses_refined_visual_markers`
