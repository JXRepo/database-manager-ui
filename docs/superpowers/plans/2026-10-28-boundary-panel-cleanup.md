# Compact boundary controls

User request: remove duplicated whole-cube tensor information, combine ordinary
XYZ point/edge/face/cube conditions into one categorized table, reduce explanatory
copy, and remove Calculated strain. The existing cube and action animation stay.

Implementation choices:
- One tensor panel with quantity/unit/mode, optional condition/record selectors,
  action toggles, complete component matrix, and a compact illustrative-motion note.
  Keep convention/precision/selection guidance in accessible titles and details.
- One ordinary XYZ table with a single header/frame and category rows. Tensor
  records never enter that table. Keep complete native tensor details as a fallback
  in the upper area until the interactive panel initializes; expose extra load fields
  in an optional compact details disclosure for the current record.
- Remove numerical preview wiring and its unused calculation helpers/tests. Keep
  supplied values, export, geometry, selection, record and unit behavior intact.
- Gripping pads appear only while the cube is displaced (including a paused action)
  and disappear on exact return/reset. Keep the current illustrative amplitude.

Verification: update existing panel/schema/browser regression contracts; exercise
pure tensor, ordinary-only, mixed categories, no-JavaScript fallback, long/empty
records, keyboard controls and real animated grip visibility at desktop widths.
Inspect rendered screenshots and diff; run relevant tests, commit and push, then
verify deployed assets independently. No production data changes.
