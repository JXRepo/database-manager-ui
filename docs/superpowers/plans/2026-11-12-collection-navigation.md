# Collection navigation implementation

Approved scope: [design](../specs/2026-11-12-collection-navigation-design.md).

- Add bounded small-collection expansion with unique object nodes and actual
  multiple-group edges; preserve explicit modes and large-set pagination.
- Add signed continuation context, destination-aware POST updates and contextual
  object links. Test invalid/repeated/foreign/expired contexts, access changes,
  capacity, deduplication and original scope restoration.
- Integrate compact saving, destination banners, contextual forms and Clear
  links, object return links, copied URLs and explicit export labels.
- Exercise desktop and native browser flows, including small/large/empty sets,
  direct additions from both selection pages and object round trips.
- Review the diff independently, run focused regression suites and JavaScript
  tests, record evidence, then commit and push the verified change.
