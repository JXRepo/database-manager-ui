# Research collections and relationship browsing

The user approved this direction after comparing NovaCrate's package scope with
the platform's individual simulation records. The workflow is: select accessible
objects, explore them together, save a named collection, and open an individual
object's detail or graph. A collection is an explicit research grouping, not an
inferred project, an uploader's entire account, or an upload job.

## Approach

Keep JSONData unchanged and add a lightweight ResearchCollection with owner,
title, description and member references. Collections are private to their owner
in this release. A record can belong to several collections. This preserves raw
JSON and record permissions while providing a stable unit for future RO-Crate
export. An automatic graph of the whole database would conflate unrelated work;
extending only the current single record graph would not answer the user's need.

## Product behavior

- Search and My Data offer Open selection in Graph beside their existing actions.
- Temporary selections live in the signed-in session and do not force a save.
  Keep up to eight selections, with at most 500 objects per selection.
- Save a selection as a collection, add it to an existing collection, rename or
  describe a collection, remove members, and delete the collection without
  deleting its data. A saved collection holds at most 1,000 objects.
- An explicit cleanup action removes unavailable member references without
  exposing their names or counts, so lost access cannot lock the collection's
  capacity. No references are cleaned automatically.
- The sidebar Graph workspace starts with saved collections and clear selection
  entry points. Retain existing single-object graph URLs and chooser navigation.
- Collection graphs show recorded relation values first. Software and phase
  names are explicitly labelled metadata groups. Group and member pages contain
  at most 25 entries; absent metadata remains discoverable. Expand one group to
  its objects instead of drawing every object's internal subgraph at once.
- Show a compact member table with supplied identity and parameter summaries so
  users can inspect differences as well as connections.
- Object detail pages offer Details and Graph navigation. Keep the existing
  graph controls, inspection, image exports and standalone links.
- Collection JSON downloads contain the accessible members' original JSON.
  Actual RO-Crate packaging, file hosting, dependency editing, ontology mapping,
  collection sharing and scientific curve comparisons are future work.

## Integrity and access

Every read starts from the viewer's accessible objects. Hidden records must not
contribute labels, edges or counts. Saving or adding a temporary selection
rechecks the entire selection and rejects unavailable members without partial
writes. Collections do not grant access to records. Mutations require POST and
CSRF. Uploaded text is escaped, raw JSON is unchanged, and repeated names never
prove shared entity identity or scientific dependence. DOI spelling variants
may identify the same declared relation, without fetching remote content.

## Validation

Exercise private/public/shared access, permission revocation, malformed and
oversized selections, collection ownership, atomic edits, duplicate membership,
empty collections, unknown metadata, long labels and 100-record studies.
Use desktop Chromium at 1280, 1440 and 1920 pixels, including native navigation
without JavaScript and existing single-object graph and plot regressions.
