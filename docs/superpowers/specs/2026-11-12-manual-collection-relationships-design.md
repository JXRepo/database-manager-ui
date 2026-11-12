# Manual collection relationships

The user explicitly requested drawing and modifying graph relationships after
comparing the existing read-only graph with NovaCrate. Implement this in saved
private research collections, using the current Django and SVG architecture.
The implementation choices below are agent decisions within that request.

## Approaches

Editing uploaded JSON would mix annotations with original research evidence.
A full RO-Crate entity editor would require a separate data model and workflow.
Collection-owned directed links between existing data objects fit the existing
workspace and preserve original data. Use this approach; temporary selections
must be saved before their relationships can be edited.

## Behavior

- Drag a connection from one visible data object to another, or choose From and
  To with ordinary form controls. Enter a relationship name, then save explicitly.
- Select a manual edge or its relationship-list entry to change its label or
  endpoints, or delete it. Cancel and Escape discard the pending gesture/form.
- Display manual connections separately from metadata-derived connections using
  dashed purple arrows and explicit Manual labels. Metadata connections remain
  read only. No ontology validation or scientific inference is claimed.
- Keep graph pages bounded. The relationship list uses 12 entries per page;
  selecting a relationship focuses both accessible endpoints even if the objects
  otherwise occur on different member pages, showing only that selected manual
  connection. Ordinary pages show at most 100 manual edges with scope counts
  and distinct paths; pointer selection resolves the nearest curve. The editor offers all accessible
  members, up to the existing 1,000-object collection limit.
- Each collection permits 1,000 manual links. Labels are trimmed, nonempty and
  at most 120 characters. Reject self-links and exact duplicate directed links.
- Store links separately with collection/source/target foreign keys, a revision
  number and timestamps. Lock the collection and affected records on mutation.
  Stale updates/deletes return 409 rather than overwrite a newer revision.
- Sharing changes and data/collection deletion take the same relevant row locks
  before changing access or collecting cascading deletes. Recheck permissions
  with a fresh query after waiting for endpoint locks.
- Every read, count, graph, edit and export checks both endpoints' current access
  and membership. Foreign collections return 404. CSRF and POST remain required.
- Removing collection members removes their incident links atomically. Deleting
  an object or collection cascades its links. Access revocation hides an entire
  connection without exposing hidden labels, IDs or counts.
- Original JSON downloads stay unchanged. A separate versioned relationship JSON
  export contains accessible endpoints and user-entered links. SVG/PNG show the
  current graph page, including manual edge styling, but omit editing handles.
- Native forms work without JavaScript. Network failures retain input and offer
  an explicit retry; no automatic mutation retry. Conflicts require fresh state.

## Verification

Backend tests cover ownership, CSRF, all endpoint checks, duplicates, malformed
or repeated fields, revisions, cleanup, export and transaction boundaries.
Graph tests cover visible overlays, cross-page focus, directed geometry and
signed return navigation. Chromium tests exercise actual drawing, editing,
deleting, reloading, failed requests and native forms at desktop sizes.
