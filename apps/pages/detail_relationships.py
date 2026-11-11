"""
Describe one data object's supplied metadata as an explorable relationship graph
"""

import json
from itertools import islice

from apps.dyn_api.metadata_compat import field_name, field_value, unwrap_single_value
from apps.dyn_api.required_schema import is_empty


def _text(value):
    """
    Join textual descriptions without turning containers or IDs into names

    Parameters
    ----------
    value : object
        A recognized descriptive field.

    Returns
    -------
    str
        Supplied text in its original order, or an empty string.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        descriptions = []
        for item in value:
            text = _text(item)
            if text:
                descriptions.append(text)
        return "; ".join(descriptions)
    return ""


def _details(data, fields):
    """
    Format a few supplied fields for a node's information panel

    Parameters
    ----------
    data : dict
        Metadata at the node's own schema parent.
    fields : tuple
        Field names and their visible labels.

    Returns
    -------
    list of dict
        Labels and complete values, including numeric zero.
    """
    details = []
    for field, label in fields:
        value = data.get(field)
        if not is_empty(value):
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            details.append({"label": label, "value": text})
    return details


def _summary(value):
    """
    Summarize containers without copying large parameter or orientation arrays

    Parameters
    ----------
    value : object
        A supplied parameter value.

    Returns
    -------
    str
        A complete scalar, small flat container or explicitly labelled summary.
    """
    if isinstance(value, (dict, list)):
        values = value.values() if isinstance(value, dict) else value
        if len(value) > 8 or any(isinstance(item, (dict, list)) for item in values):
            unit = "fields" if isinstance(value, dict) else "items"
            return f"{len(value)} {unit} · View data details for all values"
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _add_node(nodes, kind, label, parent="", relation="", details=(), key=None):
    """
    Append a node with a local identity and a complete accessible label

    Parameters
    ----------
    nodes : list of dict
        Nodes belonging only to this data object.
    kind : str
        Visible category and styling key.
    label : str
        Full label, retained alongside its compact diagram text.
    parent : str, optional
        Local ID of the node that supplies this relationship.
    relation : str, optional
        Human readable description of the outgoing relationship.
    details : sequence, optional
        Additional supplied metadata or output summaries.
    key : str, optional
        Stable field and entry identity for shareable links within the record.

    Returns
    -------
    dict
        The appended node.
    """
    node = {
        "id": f"relationship-{key or kind}", "kind": kind, "label": label,
        "parent": parent, "relation": relation, "details": list(details),
        "connections": [], "legacy_id": f"relationship-{len(nodes)}",
        "category": {
            "record": "Data object", "creator": "Creator", "software": "Software",
            "phase": "Phase", "model": "Constitutive model", "output": "Output",
            "loading": "Loading condition",
        }[kind],
    }
    nodes.append(node)
    return node


def _geometry(nodes, detailed):
    """
    Arrange cards without overlaps and connect each incoming relationship header

    Parameters
    ----------
    nodes : list of dict
        Nodes with parent IDs and supplied preview fields.
    detailed : bool
        Whether cards include their supplied field previews.

    Returns
    -------
    dict
        Positions and paths for one view, without duplicating metadata.
    """
    node_width = 232
    gap = 24
    heights = {}
    for node in nodes:
        heights[node["id"]] = 88 + len(node["preview"]) * 28 if detailed and node["preview"] else 80
    left = []
    branches = []
    children = {}
    for node in nodes[1:]:
        if node["kind"] in ("creator", "software"):
            left.append(node)
        elif node["kind"] == "model":
            children.setdefault(node["parent"], []).append(node)
        else:
            branches.append(node)

    positions = {}
    cursor = 0
    for node in branches:
        models = children.get(node["id"], [])
        model_span = sum(heights[model["id"]] for model in models) + max(0, len(models) - 1) * gap
        span = max(heights[node["id"]], model_span)
        positions[node["id"]] = {"x": 612, "y": cursor + (span - heights[node["id"]]) // 2}
        model_cursor = cursor + (span - model_span) // 2
        for model in models:
            positions[model["id"]] = {"x": 908, "y": model_cursor}
            model_cursor += heights[model["id"]] + gap
        cursor += span + gap

    branch_span = max(0, cursor - gap)
    left_span = sum(heights[node["id"]] for node in left) + max(0, len(left) - 1) * gap
    height = max(220, branch_span, left_span, heights[nodes[0]["id"]]) + 40
    for position in positions.values():
        position["y"] += (height - branch_span) // 2
    left_cursor = (height - left_span) // 2
    for node in left:
        positions[node["id"]] = {"x": 20, "y": left_cursor}
        left_cursor += heights[node["id"]] + gap
    positions[nodes[0]["id"]] = {"x": 316, "y": (height - heights[nodes[0]["id"]]) // 2}
    for node_id, position in positions.items():
        position["height"] = heights[node_id]

    paths = []
    for node in nodes[1:]:
        parent = positions[node["parent"]]
        child = positions[node["id"]]
        parent_x = parent["x"] + (node_width if child["x"] > parent["x"] else 0)
        node_x = child["x"] + (0 if child["x"] > parent["x"] else node_width)
        middle = (parent_x + node_x) // 2
        parent_y = parent["y"] + parent["height"] // 2
        node_y = child["y"] + 14
        paths.append(f"M {parent_x} {parent_y} C {middle} {parent_y}, {middle} {node_y}, {node_x} {node_y}")
    return {"width": 1160 if children else 864, "height": height,
            "positions": positions, "paths": paths}


def _layout(nodes, view):
    """
    Prepare compact and detailed views of the same nodes and relationships

    Parameters
    ----------
    nodes : list of dict
        Nodes with their complete inspector details.
    view : str
        Initial compact or detailed view for ordinary HTML navigation.

    Returns
    -------
    dict
        Graph metadata with shared geometry for native and interactive views.
    """
    for node in nodes:
        details = [item for item in node["details"] if item["label"] != "Model family"]
        if node["kind"] == "model":
            details.sort(key=lambda item: item["label"].casefold() not in {"recorded model units", "units"})
        node["preview"] = details[:3]
        node["preview_height"] = len(node["preview"]) * 28
    layouts = {"compact": _geometry(nodes, False), "detailed": _geometry(nodes, True)}
    layout = layouts[view]
    for node in nodes:
        node.update(layout["positions"][node["id"]])
    by_id = {node["id"]: node for node in nodes}
    edges = []
    for index, node in enumerate(nodes[1:]):
        parent = by_id[node["parent"]]
        edges.append({
            "source": parent["id"], "target": node["id"],
            "label": f'{parent["label"]} → {node["relation"]} → {node["label"]}',
            "path": layout["paths"][index],
        })
        node["parent_label"] = parent["label"]
        parent["connections"].append({"id": node["id"], "label": node["label"],
                                      "relation": node["relation"], "direction": "Outgoing"})
        node["connections"].append({"id": parent["id"], "label": parent["label"],
                                    "relation": node["relation"], "direction": "Incoming"})
    categories = {}
    for node in nodes:
        category = categories.setdefault(node["kind"], {"kind": node["kind"],
                                                       "label": node["category"], "count": 0})
        category["count"] += 1
    return {"nodes": nodes, "edges": edges, "width": layout["width"], "height": layout["height"],
            "node_width": 232, "count": len(nodes) - 1, "categories": list(categories.values()),
            "layouts": layouts, "view": view}


def build_relationship_graph(metadata, plot_variables, view="compact"):
    """
    Build a read only graph from the detail page's existing compatibility view

    Relationships stay within one record and models stay under their own phase.
    Output summaries reuse available curves without retaining their sample arrays.

    Parameters
    ----------
    metadata : dict
        The shared metadata compatibility view for an accessible record.
    plot_variables : list of dict
        Supplied and calculated series already prepared by the detail page.
    view : str, optional
        Initial compact or detailed card presentation.

    Returns
    -------
    dict
        Template ready graph with complete labels and local relationships.
    """
    nodes = []
    root = _add_node(
        nodes, "record", _text(metadata.get("title")) or _text(metadata.get("identifier")) or "Data object",
        details=_details(metadata, (("identifier", "Identifier"), ("date", "Date"),
                                   ("description", "Description"), ("rights", "Rights"))),
    )
    for field, relation in (("creator", "Created by"), ("software", "Uses software")):
        label = _text(metadata.get(field))
        if label:
            fields = (("software_version", "Recorded versions"),) if field == "software" else (
                ("creator_affiliation", "Recorded affiliations"), ("creator_ORCID", "Recorded ORCIDs"),
            )
            _add_node(nodes, field, label, root["id"], relation, _details(metadata, fields))

    phases = metadata.get("phase", [])
    if not isinstance(phases, list):
        phases = [phases]
    for index, phase in enumerate(phases):
        if isinstance(phase, str) and phase.strip():
            _add_node(nodes, "phase", phase.strip(), root["id"], "Has phase", key=f"phase-{index}")
            continue
        if not isinstance(phase, dict) or not phase:
            continue
        label = _text(phase.get("phase_name"))
        for legacy in ("phase_identifier", "name", "identifier"):
            if not label:
                label = _text(field_value(phase, legacy))
        phase_node = _add_node(
            nodes, "phase", label or f"Phase {index + 1}", root["id"], "Has phase",
            _details(phase, (("phase_id", "Phase ID"), ("lattice_structure", "Lattice structure"),
                             ("volume_fraction", "Volume fraction"))), key=f"phase-{index}",
        )
        orientation = phase.get("orientation")
        if isinstance(orientation, dict):
            phase_node["details"].extend(_details(orientation, (
                ("texture_type", "Texture"),
                ("frame", "Orientation frame"), ("rotation_type", "Rotation type"),
                ("orientation_identifier", "Orientation identifier"),
            )))
            grains = [(name, unwrap_single_value(value)) for name, value in orientation.items()
                      if field_name(name) in {"graincount", "grainnumber"} and not is_empty(value)]
            phase_node["details"].extend({
                "label": "Grain number" if len(grains) == 1 else f"Grain number · {name}",
                "value": _summary(value),
            } for name, value in grains)
        models = phase.get("constitutive_model", [])
        if not isinstance(models, list):
            models = [models]
        for model_index, model in enumerate(models):
            if not isinstance(model, dict):
                continue
            for family in ("elastic", "plastic", "damage"):
                label = _text(model.get(f"{family}_model_name"))
                if not label:
                    continue
                if family == "plastic" and label.casefold() == "no plasticity in this elastic reference":
                    phase_node["details"].append({"label": "Plasticity", "value": label})
                    continue
                details = [{"label": "Model family", "value": family.capitalize()}]
                if not is_empty(model.get("units")):
                    details.append({"label": "Recorded model units", "value": _summary(model["units"])})
                parameters = model.get(f"{family}_parameters")
                if isinstance(parameters, dict):
                    details.extend({"label": name, "value": _summary(value)}
                                   for name, value in islice(parameters.items(), 20))
                    if len(parameters) > 20:
                        details.append({"label": "More parameters", "value":
                                        f"{len(parameters) - 20} fields · View data details for all values"})
                elif not is_empty(parameters):
                    details.append({"label": "Parameters", "value": _summary(parameters)})
                _add_node(nodes, "model", label, phase_node["id"], f"Uses {family} model", details,
                          key=f"phase-{index}-model-{model_index}-{family}")

    for group, label in (("stress", "Stress"), ("total_strain", "Total strain"),
                         ("plastic_strain", "Plastic strain")):
        series = []
        for variable in plot_variables:
            if not variable["key"].startswith(f"{group}."):
                continue
            count = len(variable["values"])
            summary = f"{count} sample{'s' if count != 1 else ''}"
            if variable["unit"]:
                summary += f" · {variable['unit']}"
            summary += " · Calculated" if variable.get("calculated") else " · Supplied"
            series.append({"label": variable["short_label"], "value": summary})
        if series:
            _add_node(nodes, "output", label, root["id"], "Contains results", series, key=group)

    conditions = metadata.get("mechanical_BC", [])
    if not isinstance(conditions, list):
        conditions = [conditions]
    for index, condition in enumerate(conditions):
        if not isinstance(condition, dict) or is_empty(condition):
            continue
        label = " · ".join(filter(None, (_text(condition.get("loading_type")),
                                         _text(condition.get("loading_mode")))))
        details = _details(condition, (("loading_type", "Loading type"), ("loading_mode", "Loading mode")))
        for field, name in (("vertex_list", "Vertices"), ("constraints", "Constraints")):
            if not is_empty(condition.get(field)):
                details.append({"label": name, "value": _summary(condition[field])})
        loads = condition.get("applied_load")
        if not is_empty(loads):
            details.append({"label": "Load records", "value": str(len(loads) if isinstance(loads, list) else 1)})
        _add_node(nodes, "loading", label or f"Loading condition {index + 1}", root["id"],
                  "Has loading condition", details, key=f"loading-{index}")
    return _layout(nodes, view)
