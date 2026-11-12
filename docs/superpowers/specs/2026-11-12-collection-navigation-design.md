# Collection exploration refinements

The user approved four changes to the existing research collection workspace:

1. Show actual objects immediately for small selections, preserving their real
   group connections and bounded overview behavior for large sets. Collapse the
   optional save controls so the graph is visible sooner.
2. Continue selecting from Search or My Data into the current destination,
   deduplicating without a second collection choice or a new temporary token.
3. Preserve the collection scope through object detail and graph navigation,
   including group, both page numbers and Compact/Detailed presentation.
4. Label JSON as all accessible members and images as the current graph page;
   individual object image exports still contain their complete graph.

Keep raw JSON, existing permissions and standalone routes unchanged. Use signed,
user-bound context with an allowed set of display parameters, never an arbitrary
return URL. Validate destination ownership on every use and reject malformed or
stale continuation submissions without changing membership. Ordinary GET links
and POST forms must work without JavaScript. Ontology mapping, relationship
editing and RO-Crate packaging remain outside this change.
