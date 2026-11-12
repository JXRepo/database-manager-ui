"""
Prepare a bounded annotation editor from already accessible graph summaries
"""

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.urls import reverse

from .collection_graph import _argument


def relationship_editor_context(collection, context, params, form=None):
    """
    Describe saved manual relationships without loading original data arrays

    Parameters
    ----------
    collection : ResearchCollection
        Collection already restricted to the requesting owner.
    context : dict
        Graph context containing accessible summaries and filtered annotations.
    params : QueryDict or dict
        Current workspace navigation arguments.
    form : RelationshipForm or None, optional
        Submitted form to retain on a failed mutation.

    Returns
    -------
    dict
        Native form, bounded list and graph editing metadata.
    """
    from .collection_relationships import RelationshipForm

    members = context["manual_member_summaries"]
    by_id = {row["pk"]: row for row in members}
    base_url = reverse("collection_detail", args=[collection.pk])
    presentation = context["graph_view_mode"]
    rows = []
    for relation in context["manual_relationship_rows"]:
        row = dict(relation)
        row.update(
            source_title=by_id[row["source_id"]]["title"],
            target_title=by_id[row["target_id"]]["title"],
            edit_url=base_url + "?" + urlencode({"links": "members", "edge": row["id"], "view": presentation}),
            delete_url=reverse("collection_relationship_delete", args=[collection.pk, row["id"]]),
        )
        rows.append(row)
    selected_id = (context.get("manual_selected") or {}).get("id")
    if form is not None and form.is_bound:
        form.is_valid()
        selected_id = form.cleaned_data.get("relationship_id") or selected_id
    selected = next((row for row in rows if row["id"] == selected_id), None)
    page_number = _argument(params, "relationships_page", "1")
    page = Paginator(rows, 12).get_page(page_number)
    visible_ids = {row["id"] for row in context["manual_visible"]}
    editable_ids = visible_ids | {row["id"] for row in page.object_list}
    if selected:
        editable_ids.add(selected["id"])
    choices = [(row["pk"], row["title"] + (f" · {row['identifier']}" if row["identifier"] else ""))
               for row in members]
    if form is None:
        initial = {}
        if selected:
            initial = {
                "relationship_id": selected["id"], "revision": selected["revision"],
                "source": selected["source_id"], "target": selected["target_id"], "label": selected["label"],
            }
        form = RelationshipForm(initial=initial, choices=choices)
    else:
        form.fields["source"].widget.choices = [("", "Choose a data object"), *choices]
        form.fields["target"].widget.choices = [("", "Choose a data object"), *choices]
    arguments = {}
    for key in ("links", "group", "page", "groups_page", "edge", "view"):
        value = _argument(params, key)
        if value:
            arguments[key] = value
    previous_url = ""
    next_url = ""
    if page.has_previous():
        previous_url = base_url + "?" + urlencode({**arguments, "relationships_page": page.previous_page_number()}) + "#manual-relationships"
    if page.has_next():
        next_url = base_url + "?" + urlencode({**arguments, "relationships_page": page.next_page_number()}) + "#manual-relationships"
    return {
        "save_url": reverse("collection_relationship_save", args=[collection.pk]),
        "export_url": reverse("collection_relationship_export", args=[collection.pk]),
        "members": members, "rows": list(page.object_list), "page": page,
        "previous_url": previous_url, "next_url": next_url,
        "total": len(rows), "visible_count": len(visible_ids),
        "visible_total": context["manual_visible_total"],
        "selected": selected, "form": form,
        "editable_rows": [row for row in rows if row["id"] in editable_ids],
        "members_url": base_url + "?" + urlencode({"links": "members", "view": presentation}),
        "reload_url": selected["edit_url"] if selected else base_url + "?links=members",
    }
