"""
Describe declared references and reported metadata within an accessible collection
"""

import hashlib
import json
import re
from urllib.parse import unquote, urlencode, urlsplit

from django.core.paginator import Paginator
from django.urls import reverse

from apps.dyn_api.metadata_compat import field_name, field_value, metadata_view


PAGE_SIZE = 25
SMALL_COLLECTION_LIMIT = 8
MAX_EXPANDED_NODES = 25
LINK_MODES = {
    "relations": (
        "Declared relations", "No declared relation",
        "References supplied in each object's relation field. A shared reference does not establish a dependency between simulations.",
    ),
    "software": (
        "Software names", "No software name",
        "Groups use reported software names. Matching names do not establish the same version or configuration.",
    ),
    "phase": (
        "Phase names", "No phase name",
        "Groups use reported phase names. Matching names do not establish the same material or model parameters.",
    ),
    "members": (
        "Collection members", "",
        "Objects explicitly selected for this workspace. Membership does not establish a scientific dependency.",
    ),
}
DOI = re.compile(r"10\.\d{4,9}/\S+\Z", re.IGNORECASE)


def _names(value, fallback_keys=()):
    """
    Collect supplied text without turning identifiers or arbitrary objects into names

    Parameters
    ----------
    value : object
        A recognized metadata value.
    fallback_keys : tuple, optional
        Explicit name fields, in their preferred order.

    Returns
    -------
    list of str
        Distinct labels in supplied order, ignoring case and surrounding spaces.
    """
    names = {}
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and item.strip():
            label = item.strip()
            names.setdefault(label.casefold(), label)
        elif isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, dict):
            for key in fallback_keys:
                labels = _names(field_value(item, key))
                if labels:
                    pending.extend(reversed(labels))
                    break
    return list(names.values())


def _reference_key(label):
    """
    Recognize explicit DOI forms while keeping other reference text exact

    Parameters
    ----------
    label : str
        A nonempty supplied relation string.

    Returns
    -------
    str
        Comparable DOI identity or the unchanged reference text.
    """
    candidate = label
    if candidate.lower().startswith("doi:"):
        candidate = candidate[4:].strip()
    elif candidate.lower().startswith(("http://", "https://")):
        try:
            url = urlsplit(candidate)
        except ValueError:
            return "text:" + label
        if url.netloc.lower() not in {"doi.org", "dx.doi.org"} or url.query or url.fragment:
            return "text:" + label
        try:
            candidate = unquote(url.path.lstrip("/"), errors="strict")
        except UnicodeDecodeError:
            return "text:" + label
    if DOI.fullmatch(candidate):
        return "doi:" + candidate.casefold()
    return "text:" + label


def _relations(value):
    """
    Retain explicit reference strings without searching nested metadata

    Parameters
    ----------
    value : object
        The record's recognized top level relation field.

    Returns
    -------
    dict
        Comparable reference keys and their first supplied spelling.
    """
    references = {}
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, str) and item.strip():
            label = item.strip()
            references.setdefault(_reference_key(label), label)
    return references


def _version_text(value):
    """
    Preserve recorded textual and numeric software versions for comparison

    Parameters
    ----------
    value : object
        Supplied software version or descriptive values in their stored order.

    Returns
    -------
    str
        Complete scalar versions without interpreting numbers as software names.
    """
    versions = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
            continue
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, (int, float, bool)):
            text = json.dumps(item)
        else:
            continue
        if text and text not in versions:
            versions.append(text)
    return "; ".join(versions)


def _object_summary(obj):
    """
    Release one object's arrays after extracting its comparison and grouping labels

    Parameters
    ----------
    obj : JSONData
        One record already restricted to the viewer's access.

    Returns
    -------
    dict
        Scalar descriptions and label groups, without retained raw metadata.
    """
    conflicts = []
    data = metadata_view(obj.data, conflicts=conflicts)
    for first, second in conflicts:
        for field in ("identifier", "relation", "phase", "mechanical_BC"):
            if field_name(first) == field_name(field) or field_name(second) == field_name(field):
                data.pop(field, None)
        if first.startswith("mechanical_BC[") or first.startswith("mechanical_BC."):
            data.pop("mechanical_BC", None)
    software = _names(data.get("software"), ("name", "software_name"))
    phases = _names(data.get("phase"), ("phase_name", "phase_identifier", "name", "identifier"))
    references = _relations(data.get("relation"))
    loading = []
    conditions = data.get("mechanical_BC", [])
    if not isinstance(conditions, list):
        conditions = [conditions]
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        label = " · ".join(filter(None, (
            "; ".join(_names(condition.get("loading_type"))),
            "; ".join(_names(condition.get("loading_mode"))),
        )))
        if label and label not in loading:
            loading.append(label)
    identifier = "; ".join(_names(data.get("identifier")))
    title = "; ".join(_names(data.get("title"))) or identifier or "Untitled data object"
    return {
        "pk": obj.pk, "title": title, "identifier": identifier,
        "software": "; ".join(software),
        "software_version": _version_text(data.get("software_version")),
        "phase": "; ".join(phases), "loading": "; ".join(loading),
        "creator": "; ".join(_names(data.get("creator"), ("name", "creator_name"))),
        "relations": "; ".join(references.values()),
        "detail_url": reverse("json_data_detail", args=[obj.pk]),
        "graph_url": reverse("json_data_detail", args=[obj.pk]) + "?tab=graph",
        "groups": {
            "relations": references,
            "software": {name.casefold(): name for name in software},
            "phase": {name.casefold(): name for name in phases},
        },
    }


def _argument(params, key, default=""):
    """
    Reject repeated scope arguments rather than choosing an arbitrary value

    Parameters
    ----------
    params : QueryDict or dict
        Requested workspace controls.
    key : str
        Argument to read once.
    default : str, optional
        Value for an absent argument.

    Returns
    -------
    str
        The single supplied value or its default.

    Raises
    ------
    ValueError
        The argument appears more than once.
    """
    values = params.getlist(key) if hasattr(params, "getlist") else [params.get(key, default)]
    if len(values) > 1:
        raise ValueError("Choose one relationship view and one group.")
    return values[0] if values else default


def _node(node_id, kind, category, label, *, parent="", relation="", details=(), source_url="", source_label=""):
    """
    Create one collection node using the shared graph renderer's data shape

    Parameters
    ----------
    node_id, kind, category, label : str
        Stable identity, styling and visible descriptions.
    parent, relation : str, optional
        Parent ID and the explicit meaning of its connection.
    details : sequence, optional
        Small recorded descriptions for the inspector.
    source_url, source_label : str, optional
        Internal link for opening the node's members or source object.

    Returns
    -------
    dict
        A complete node before geometry is calculated.
    """
    return {
        "id": node_id, "legacy_id": node_id, "kind": kind, "category": category,
        "label": label, "parent": parent, "relation": relation,
        "details": list(details), "connections": [],
        "source_url": source_url, "source_label": source_label,
    }


def _layout(nodes, view, connections):
    """
    Arrange a bounded collection, optional group and one page of member cards

    Parameters
    ----------
    nodes : list of dict
        Collection graph nodes with at most three levels.
    view : str
        Compact or detailed card presentation.
    connections : list of dict
        Actual source, target and relation edges, including shared group membership.

    Returns
    -------
    dict
        Shared renderer geometry, inspector connections and view controls.
    """
    by_id = {}
    columns = {}
    for node in nodes:
        node["preview"] = node["details"][:3]
        node["preview_height"] = len(node["preview"]) * 28
        node["depth"] = by_id[node["parent"]]["depth"] + 1 if node["parent"] else 0
        by_id[node["id"]] = node
        columns.setdefault(node["depth"], []).append(node)
    layouts = {}
    for mode in ("compact", "detailed"):
        heights = {}
        spans = {}
        for depth, column in columns.items():
            for node in column:
                heights[node["id"]] = 88 + node["preview_height"] if mode == "detailed" and node["preview"] else 80
            spans[depth] = sum(heights[node["id"]] for node in column) + 24 * (len(column) - 1)
        height = max(220, *spans.values()) + 40
        positions = {}
        for depth, column in columns.items():
            y = (height - spans[depth]) // 2
            for node in column:
                positions[node["id"]] = {"x": 20 + depth * 296, "y": y, "height": heights[node["id"]]}
                y += heights[node["id"]] + 24
        paths = []
        for connection in connections:
            parent = positions[connection["source"]]
            target = positions[connection["target"]]
            start_x = parent["x"] + 232
            start_y = parent["y"] + parent["height"] // 2
            end_x, end_y = target["x"], target["y"] + 14
            middle = (start_x + end_x) // 2
            paths.append(f"M {start_x} {start_y} C {middle} {start_y}, {middle} {end_y}, {end_x} {end_y}")
        layouts[mode] = {
            "width": 272 + max(columns) * 296, "height": height,
            "positions": positions, "paths": paths,
        }
    layout = layouts[view]
    edges = []
    categories = {}
    for node in nodes:
        node.update(layout["positions"][node["id"]])
        category = categories.setdefault(node["kind"], {"kind": node["kind"], "label": node["category"], "count": 0})
        category["count"] += 1
    for connection in connections:
        parent = by_id[connection["source"]]
        node = by_id[connection["target"]]
        relation = connection["relation"]
        edges.append({
            "source": parent["id"], "target": node["id"],
            "label": f'{parent["label"]} → {relation} → {node["label"]}',
            "path": layout["paths"][len(edges)],
        })
        parent["connections"].append({"id": node["id"], "label": node["label"], "relation": relation, "direction": "Outgoing"})
        node["connections"].append({"id": parent["id"], "label": parent["label"], "relation": relation, "direction": "Incoming"})
    return {
        "nodes": nodes, "edges": edges, "node_width": 232, "count": len(edges),
        "width": layout["width"], "height": layout["height"], "view": view,
        "layouts": layouts, "categories": list(categories.values()), "is_collection": True,
    }


def build_collection_context(accessible_queryset, *, title, base_url, params):
    """
    Prepare a collection graph and comparison rows from currently accessible records

    Raw metadata is read one record at a time. Names are discovery groups;
    references only come from the supplied relation field.

    Parameters
    ----------
    accessible_queryset : QuerySet
        Selected records after the caller applies current access rules.
    title : str
        The collection or temporary workspace title.
    base_url : str
        Internal URL for this collection or temporary selection.
    params : QueryDict or dict
        Relationship mode, group and pagination arguments.

    Returns
    -------
    dict
        Bounded graph, group navigation, comparison rows and exact counts.

    Raises
    ------
    ValueError
        A relationship mode or group is invalid or repeated.
    """
    mode = _argument(params, "links", "relations")
    selected_key = _argument(params, "group")
    if mode not in LINK_MODES or (mode == "members" and selected_key):
        raise ValueError("Choose a valid relationship view and group.")
    view = "detailed" if _argument(params, "view", "compact") == "detailed" else "compact"
    summaries = [
        _object_summary(obj)
        for obj in accessible_queryset.only("pk", "data").order_by("-uploaded_at", "-pk").iterator(chunk_size=1)
    ]
    if "links" not in params and "group" not in params:
        reference_keys = {
            identity
            for row in summaries
            for identity in row["groups"]["relations"] or [None]
        }
        no_references = not reference_keys or reference_keys == {None}
        crowded_small_collection = (
            len(summaries) <= SMALL_COLLECTION_LIMIT
            and 1 + len(summaries) + len(reference_keys) > MAX_EXPANDED_NODES
        )
        if no_references or crowded_small_collection:
            mode = "members"
    arguments = {"links": mode}
    if selected_key:
        arguments["group"] = selected_key
    if view == "detailed":
        arguments["view"] = view

    def url(**changes):
        """
        Keep workspace scope while changing explicit navigation controls

        Parameters
        ----------
        **changes : str or int or None
            Arguments to replace or remove.

        Returns
        -------
        str
            Local workspace URL with encoded query values.
        """
        values = {**arguments, **changes}
        values = {key: value for key, value in values.items() if value is not None and value != ""}
        return base_url + "?" + urlencode(values)

    groups = {}
    for row in summaries:
        labels = row.pop("groups").get(mode, {})
        row["group_keys"] = set()
        if mode == "members":
            continue
        for identity, label in labels.items() or [(None, LINK_MODES[mode][1])]:
            key = hashlib.sha256((mode + "\0" + identity).encode()).hexdigest()[:24] if identity is not None else "missing"
            group = groups.setdefault(key, {"key": key, "label": label, "count": 0, "url": url(group=key), "selected": key == selected_key})
            group["count"] += 1
            row["group_keys"].add(key)
    if selected_key and selected_key not in groups:
        raise ValueError("This group is unavailable. Choose a group from the collection overview.")
    group_values = sorted(groups.values(), key=lambda group: (group["key"] == "missing", -group["count"], group["label"].casefold()))
    group_page = Paginator(group_values, PAGE_SIZE).get_page(params.get("groups_page"))
    selected = groups.get(selected_key)
    matches = [row for row in summaries if not selected_key or selected_key in row["group_keys"]]
    object_page = Paginator(matches, PAGE_SIZE).get_page(params.get("page"))
    object_rows = list(object_page.object_list)
    auto_expanded = bool(
        summaries and mode != "members" and not selected
        and len(summaries) <= SMALL_COLLECTION_LIMIT
        and 1 + len(summaries) + len(groups) <= MAX_EXPANDED_NODES
    )
    graph = None
    if summaries:
        root = _node(
            "collection-root", "collection", "Research collection", title,
            details=[{"label": "Accessible objects", "value": str(len(summaries))}],
            source_url=url(group=None), source_label="View collection overview",
        )
        nodes = [root]
        connections = []
        visible_groups = [selected] if selected else group_page.object_list
        for group in visible_groups:
            missing = group["key"] == "missing"
            kind = "missing" if missing else {"relations": "reference", "software": "software", "phase": "phase"}[mode]
            category = "Metadata coverage" if missing else {"relations": "Declared relation", "software": "Reported software name", "phase": "Reported phase name"}[mode]
            relation = "Without metadata" if missing else {"relations": "Declared in collection", "software": "Reported software", "phase": "Reported phase"}[mode]
            nodes.append(_node(
                "collection-group-" + group["key"], kind, category, group["label"],
                parent=root["id"], relation=relation,
                details=[{"label": "Data objects", "value": str(group["count"])}, {"label": "Meaning", "value": LINK_MODES[mode][2]}],
                source_url=group["url"], source_label=f"View {group['count']} object{'s' if group['count'] != 1 else ''}",
            ))
            connections.append({"source": root["id"], "target": nodes[-1]["id"], "relation": relation})
        if mode == "members" or selected or auto_expanded:
            for row in object_rows:
                parents = [group for group in visible_groups if group["key"] in row["group_keys"]]
                parent_id = "collection-group-" + parents[0]["key"] if parents else root["id"]
                relation = "Contains object" if mode == "members" else "Includes object" if row["group_keys"] == {"missing"} else "Declared by" if mode == "relations" else "Reported by"
                details = []
                for field, label in (("identifier", "Identifier"), ("software", "Software"), ("software_version", "Recorded versions"), ("phase", "Phase names"), ("loading", "Loading"), ("creator", "Creator"), ("relations", "Declared relations")):
                    if row[field]:
                        details.append({"label": label, "value": row[field]})
                node = _node(
                    f"collection-object-{row['pk']}", "record", "Data object", row["title"],
                    parent=parent_id, relation=relation, details=details,
                    source_url=row["detail_url"], source_label="View data details",
                )
                node["object_pk"] = row["pk"]
                node["graph_url"] = row["graph_url"]
                nodes.append(node)
                for source in ["collection-group-" + group["key"] for group in parents] or [root["id"]]:
                    connections.append({"source": source, "target": node["id"], "relation": relation})
        graph = _layout(nodes, view, connections)
    context = {
        "relationship_graph": graph, "links_mode": mode, "auto_expanded": auto_expanded,
        "links_description": LINK_MODES[mode][2], "links_options": [],
        "group_options": list(group_page.object_list), "group_page": group_page,
        "selected_group": selected, "object_rows": object_rows, "object_page": object_page,
        "object_total": len(summaries), "matching_object_count": len(matches),
        "overview_url": url(group=None), "graph_view_mode": view,
        "graph_compact_url": url(view=None, page=object_page.number, groups_page=group_page.number),
        "graph_detailed_url": url(view="detailed", page=object_page.number, groups_page=group_page.number),
        "graph_export_name": "collection-relationships",
    }
    for value, (label, _, _) in LINK_MODES.items():
        context["links_options"].append({"value": value, "label": label, "url": url(links=value, group=None), "active": value == mode})
    for prefix, page, parameter in (("objects", object_page, "page"), ("groups", group_page, "groups_page")):
        page_arguments = {"page": object_page.number, "groups_page": group_page.number}
        if page.has_previous():
            context[f"previous_{prefix}_url"] = url(**{**page_arguments, parameter: page.previous_page_number()})
        else:
            context[f"previous_{prefix}_url"] = ""
        if page.has_next():
            context[f"next_{prefix}_url"] = url(**{**page_arguments, parameter: page.next_page_number()})
        else:
            context[f"next_{prefix}_url"] = ""
    return context
