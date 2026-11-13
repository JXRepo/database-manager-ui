"""
Describe declared references and reported metadata within an accessible collection
"""

import hashlib
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import BigIntegerField, BinaryField, Count, F, Func, Q, TextField
from django.db.models.functions import Cast
from django.urls import reverse

from .collection_summary import build_collection_summary
from .study_comparison import SUMMARY_VERSION, outdated_summary_query


PAGE_SIZE = 25
SMALL_COLLECTION_LIMIT = 8
MAX_EXPANDED_NODES = 25
MAX_VISIBLE_MANUAL_EDGES = 100
MAX_REQUEST_SUMMARY_OBJECTS = 25
MAX_REQUEST_SUMMARY_BYTES = 16 * 1024 * 1024
MAX_REQUEST_SUMMARY_SECONDS = 1
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


class CollectionSummaryPending(Exception):
    """
    Report actual accessible preparation progress without returning a partial graph
    """

    def __init__(self, ready_count, total_count, requires_admin):
        """
        Keep public progress values for the collection workspace

        Parameters
        ----------
        ready_count, total_count : int
            Current prepared and total accessible member counts.
        requires_admin : bool
            Whether any remaining row requires preparation outside a web request.
        """
        self.ready_count = ready_count
        self.total_count = total_count
        self.requires_admin = requires_admin
        super().__init__("Collection summaries are still being prepared.")


@dataclass
class SummaryPreparationBudget:
    """
    Share web preparation allowances across the parts of one workspace request
    """

    started: float = field(default_factory=lambda: monotonic())
    checked_count: int = 0
    prepared_bytes: int = 0


def collection_summaries(accessible_queryset, *, prepare_all=False, require_comparison=False, budget=None):
    """
    Read cached labels and prepare missing summaries one accessible row at a time

    Parameters
    ----------
    accessible_queryset : QuerySet
        Records already restricted to the viewer and current collection.
    prepare_all : bool, optional
        Allow operator commands to prepare their bounded batch without web limits.
    require_comparison : bool, optional
        Upgrade only the selected records when their comparison projection is outdated.
    budget : SummaryPreparationBudget or None, optional
        Shared request allowance, or a fresh allowance for an independent caller.

    Yields
    ------
    dict
        Scalar summaries with current record IDs and local navigation links.

    Raises
    ------
    CollectionSummaryPending
        Some accessible summaries could not be prepared within this request.
    """
    budget = budget if budget is not None else SummaryPreparationBudget()
    pending = False
    operator_rows = set()
    objects = accessible_queryset.only("pk", "collection_summary", "size_bytes").order_by("-uploaded_at", "-pk")

    def needs_preparation(summary):
        """
        Keep legacy discovery summaries usable until comparison explicitly needs them

        Parameters
        ----------
        summary : dict or None
            Stored scalar metadata projection.

        Returns
        -------
        bool
            Whether this caller requires a new projection.
        """
        return summary is None or (require_comparison and summary.get("summary_version") != SUMMARY_VERSION)

    def within_budget(size_bytes):
        """
        Check the remaining request allowance before loading one original JSON

        Parameters
        ----------
        size_bytes : int
            Stored original JSON size, with zero representing an unknown size.

        Returns
        -------
        bool
            Whether this record may be prepared by the current operation.
        """
        return prepare_all or (
            0 < size_bytes <= MAX_REQUEST_SUMMARY_BYTES
            and budget.prepared_bytes + size_bytes <= MAX_REQUEST_SUMMARY_BYTES
            and monotonic() - budget.started < MAX_REQUEST_SUMMARY_SECONDS
        )

    for obj in objects.iterator(chunk_size=100):
        summary = obj.collection_summary
        if needs_preparation(summary):
            if not prepare_all and (obj.size_bytes <= 0 or obj.size_bytes > MAX_REQUEST_SUMMARY_BYTES):
                operator_rows.add(obj.pk)
            if not within_budget(obj.size_bytes):
                pending = True
                continue
            if not prepare_all and budget.checked_count >= MAX_REQUEST_SUMMARY_OBJECTS:
                pending = True
                continue
            budget.checked_count += 1
            with transaction.atomic(using=accessible_queryset.db):
                skip_locked = not prepare_all and connections[accessible_queryset.db].features.has_select_for_update_skip_locked
                current = accessible_queryset.filter(pk=obj.pk).select_for_update(skip_locked=skip_locked).only(
                    "pk", "size_bytes", "collection_summary",
                ).first()
                if current is None:
                    pending = True
                    continue
                summary = current.collection_summary
                if needs_preparation(summary):
                    if not within_budget(current.size_bytes):
                        if current.size_bytes <= 0 or current.size_bytes > MAX_REQUEST_SUMMARY_BYTES:
                            operator_rows.add(current.pk)
                        pending = True
                        continue
                    raw_bytes = current.size_bytes
                    if not prepare_all:
                        postgres = connections[accessible_queryset.db].vendor == "postgresql"
                        byte_length = Func(
                            Cast(F("data"), TextField() if postgres else BinaryField()),
                            function="OCTET_LENGTH" if postgres else "LENGTH",
                            output_field=BigIntegerField(),
                        )
                        raw_bytes = accessible_queryset.filter(pk=current.pk).annotate(
                            summary_raw_bytes=byte_length,
                        ).values_list("summary_raw_bytes", flat=True).first()
                        if raw_bytes is None:
                            pending = True
                            continue
                        if not within_budget(raw_bytes):
                            if raw_bytes <= 0 or raw_bytes > MAX_REQUEST_SUMMARY_BYTES:
                                operator_rows.add(current.pk)
                            pending = True
                            continue
                    summary = build_collection_summary(current.data)
                    current.collection_summary = summary
                    current.save(using=accessible_queryset.db, update_fields=["collection_summary"])
                    budget.prepared_bytes += raw_bytes
            del current
        detail_url = reverse("json_data_detail", args=[obj.pk])
        displayed = summary if require_comparison else {key: value for key, value in summary.items()
                                                        if key not in {"comparison", "parameter_map"}}
        yield {**displayed, "pk": obj.pk, "detail_url": detail_url, "graph_url": detail_url + "?tab=graph"}
    if pending and not prepare_all:
        missing = outdated_summary_query() if require_comparison else Q(collection_summary__isnull=True)
        counts = accessible_queryset.aggregate(
            total=Count("pk"), ready=Count("pk", filter=~missing),
            blocked=Count("pk", filter=missing & (
                Q(size_bytes__lte=0) | Q(size_bytes__gt=MAX_REQUEST_SUMMARY_BYTES)
                | Q(pk__in=operator_rows)
            )),
        )
        raise CollectionSummaryPending(
            counts["ready"], counts["total"],
            bool(counts["blocked"]),
        )


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
        manual_lane = 0
        manual_count = sum(bool(connection.get("manual_id")) for connection in connections)
        lane_step = min(18, 198 / max(1, manual_count - 1))
        for connection in connections:
            parent = positions[connection["source"]]
            target = positions[connection["target"]]
            start_x = parent["x"] + 232
            start_y = parent["y"] + parent["height"] // 2
            if connection.get("manual_id"):
                end_x = target["x"] + 232
                end_y = target["y"] + target["height"] // 2
                bend = round(max(start_x, end_x) + 64 + manual_lane * lane_step, 3)
                paths.append(f"M {start_x} {start_y} C {bend} {start_y}, {bend} {end_y}, {end_x} {end_y}")
                manual_lane += 1
                continue
            end_x, end_y = target["x"], target["y"] + 14
            middle = (start_x + end_x) // 2
            paths.append(f"M {start_x} {start_y} C {middle} {start_y}, {middle} {end_y}, {end_x} {end_y}")
        layouts[mode] = {
            "width": 272 + max(columns) * 296 + (280 if manual_lane else 0), "height": height,
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
            "manual_id": connection.get("manual_id"),
            "revision": connection.get("revision"),
        })
        if connection.get("manual_id"):
            edges[-1]["label"] = "Manual: " + edges[-1]["label"]
            relation = "Manual: " + relation
        parent["connections"].append({"id": node["id"], "label": node["label"], "relation": relation, "direction": "Outgoing"})
        node["connections"].append({"id": parent["id"], "label": parent["label"], "relation": relation, "direction": "Incoming"})
    return {
        "nodes": nodes, "edges": edges, "node_width": 232, "count": len(edges),
        "width": layout["width"], "height": layout["height"], "view": view,
        "layouts": layouts, "categories": list(categories.values()), "is_collection": True,
    }


def build_collection_context(accessible_queryset, *, title, base_url, params, manual_relationships=(), summary_budget=None):
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
    manual_relationships : sequence of dict, optional
        Collection annotations with both endpoints already checked for access.
    summary_budget : SummaryPreparationBudget or None, optional
        Request allowance shared with comparison and candidate preparation.

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
    summaries = list(collection_summaries(accessible_queryset, budget=summary_budget))
    member_ids = {row["pk"] for row in summaries}
    from .study_workspace import study_parameters

    try:
        study_state = study_parameters(params)
    except ValueError:
        study_state = {}
    focus_ids = [int(value) for value in study_state.get("compare", "").split(",") if value]
    if len(focus_ids) < 2 or not set(focus_ids).issubset(member_ids):
        focus_ids = []
    manual_relationships = [row for row in manual_relationships
                            if row["source_id"] in member_ids and row["target_id"] in member_ids]
    edge_id = _argument(params, "edge")
    selected_edge = None
    if edge_id:
        if not edge_id.isascii() or not edge_id.isdecimal() or len(edge_id) > 19:
            raise ValueError("This manual relationship is unavailable. Return to the collection overview.")
        selected_edge = next((row for row in manual_relationships if str(row["id"]) == edge_id), None)
        if selected_edge is None:
            raise ValueError("This manual relationship is unavailable. Return to the collection overview.")
        mode, selected_key = "members", ""
    elif focus_ids:
        mode, selected_key = "members", ""
    if not selected_edge and not focus_ids and "links" not in params and "group" not in params:
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
    arguments = {"links": mode, **study_state}
    if selected_edge:
        arguments["edge"] = edge_id
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
    if selected_edge:
        endpoints = {selected_edge["source_id"], selected_edge["target_id"]}
        matches = [row for row in summaries if row["pk"] in endpoints]
    object_page = Paginator(matches, PAGE_SIZE).get_page(params.get("page"))
    object_rows = list(object_page.object_list)
    auto_expanded = bool(
        summaries and mode != "members" and not selected
        and len(summaries) <= SMALL_COLLECTION_LIMIT
        and 1 + len(summaries) + len(groups) <= MAX_EXPANDED_NODES
    )
    graph = None
    visible_manual = []
    visible_manual_total = 0
    if summaries:
        root = _node(
            "collection-root", "collection", "Research collection", title,
            details=[{"label": "Accessible objects", "value": str(len(summaries))}],
            source_url=url(group=None, edge=None), source_label="View collection overview",
        )
        if focus_ids and not selected_edge:
            root["details"].append({"label": "Selected records", "value": str(len(focus_ids))})
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
            graph_rows = object_rows
            if focus_ids and not selected_edge:
                by_pk = {row["pk"]: row for row in summaries}
                graph_rows = [by_pk[pk] for pk in focus_ids]
            for row in graph_rows:
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
        visible_ids = {node["object_pk"] for node in nodes if "object_pk" in node}
        visible_manual = [row for row in manual_relationships
                          if row["source_id"] in visible_ids and row["target_id"] in visible_ids]
        if selected_edge:
            visible_manual = [selected_edge]
        visible_manual_total = len(visible_manual)
        visible_manual = visible_manual[:MAX_VISIBLE_MANUAL_EDGES]
        for row in visible_manual:
            connections.append({
                "source": f"collection-object-{row['source_id']}",
                "target": f"collection-object-{row['target_id']}",
                "relation": row["label"], "manual_id": row["id"], "revision": row["revision"],
            })
        graph = _layout(nodes, view, connections)
    context = {
        "relationship_graph": graph, "links_mode": mode, "auto_expanded": auto_expanded,
        "links_description": LINK_MODES[mode][2], "links_options": [],
        "group_options": list(group_page.object_list), "group_page": group_page,
        "selected_group": selected, "object_rows": object_rows, "object_page": object_page,
        "object_total": len(summaries), "matching_object_count": len(matches),
        "overview_url": url(group=None, edge=None), "graph_view_mode": view,
        "graph_compact_url": url(view=None, page=object_page.number, groups_page=group_page.number),
        "graph_detailed_url": url(view="detailed", page=object_page.number, groups_page=group_page.number),
        "graph_export_name": "collection-relationships",
        "manual_member_summaries": summaries, "manual_relationship_rows": manual_relationships,
        "manual_selected": selected_edge, "manual_visible": visible_manual,
        "manual_visible_total": visible_manual_total,
    }
    for value, (label, _, _) in LINK_MODES.items():
        context["links_options"].append({"value": value, "label": label, "url": url(links=value, group=None, edge=None), "active": value == mode})
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
