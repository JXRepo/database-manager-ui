import json
from collections import Counter
from numbers import Number

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from apps.pages.models import JSONData


CONSTRAINT_AXES = ("X", "Y", "Z")
CONSTRAINT_STATES = ("Fixed", "Loaded", "Free", "Other")
QUALITY_CHECK_LABELS = (
    "Phase metadata",
    "Software / solver",
    "Constitutive model",
    "Mechanical BC",
    "Global temperature",
    "Mesh cells",
    "RVE size",
    "Stress strain arrays",
    "Units",
)


def _normalize_text(value, default="Unknown"):
    """
    Convert a metadata value into a short text label

    Current phase names take precedence over older dictionary labels.

    Parameters
    ----------
    value : object
        Metadata value to summarize.
    default : str, optional
        Label used when the value has no readable text.

    Returns
    -------
    str
        Compact label for a chart or analysis table.
    """
    if value is None or value == "" or value == []:
        return default

    if isinstance(value, str):
        text = value.strip()
        return text if text else default

    if isinstance(value, list):
        parts = []

        for item in value:
            text = _normalize_text(item, default="")

            if text:
                parts.append(text)

        if not parts:
            return default

        return ", ".join(parts)

    if isinstance(value, dict):
        text = (
            _normalize_text(value.get("phase_name"), default="")
            or value.get("name")
            or value.get("creator_name")
            or value.get("author")
            or value.get("identifier")
            or value.get("title")
            or value.get("phase_identifier")
            or value.get("material")
            or ""
        )
        text = str(text).strip()
        return text if text else default

    text = str(value).strip()
    return text if text else default


def _has_value(value):
    """
    Return True when a metadata value is present
    """
    return value is not None and value != "" and value != []


def _iter_phase_items(value):
    """
    Yield phase dictionaries from phase metadata
    """
    if isinstance(value, list):
        for item in value:
            yield from _iter_phase_items(item)

    elif isinstance(value, dict):
        yield value


def _extract_phase_labels(value):
    """
    Extract phase or material labels from top-level phase metadata

    Prefer the current schema's phase_name and retain older name fallbacks.

    Parameters
    ----------
    value : object
        Phase metadata from one data object.

    Returns
    -------
    list of str
        Phase names for chart labels and grouping.
    """
    labels = []

    for phase in _iter_phase_items(value):
        label = (
            _normalize_text(phase.get("phase_name"), default="")
            or phase.get("phase_identifier")
            or phase.get("material")
            or phase.get("name")
            or phase.get("title")
        )
        labels.append(_normalize_text(label))

    if labels:
        return labels

    if _has_value(value):
        return [_normalize_text(value)]

    return []


def _extract_constitutive_model_labels(data):
    """
    Extract constitutive model labels from phase metadata
    """
    labels = []

    for phase in _iter_phase_items(data.get("phase")):
        model = phase.get("constitutive_model")

        if not isinstance(model, dict):
            continue

        plastic_model = _normalize_text(model.get("plastic_model_name"), default="")
        elastic_model = _normalize_text(model.get("elastic_model_name"), default="")

        if plastic_model:
            labels.append(plastic_model)
        elif elastic_model:
            labels.append(elastic_model)

    return labels


def _extract_mechanical_values(data, key):
    """
    Extract unique values from mechanical boundary condition entries
    """
    mechanical_bc = data.get("mechanical_BC", [])

    if not isinstance(mechanical_bc, list):
        return []

    values = []

    for condition in mechanical_bc:
        if not isinstance(condition, dict):
            continue

        value = _normalize_text(condition.get(key), default="")

        if value:
            values.append(value)

    return sorted(set(values))


def _extract_constraint_states(data):
    """
    Extract constraint state labels from mechanical boundary conditions
    """
    mechanical_bc = data.get("mechanical_BC", [])

    if not isinstance(mechanical_bc, list):
        return []

    states = []

    for condition in mechanical_bc:
        if not isinstance(condition, dict):
            continue

        constraints = condition.get("constraints", [])

        if not isinstance(constraints, list):
            continue

        for state in constraints:
            label = _normalize_text(state, default="")

            if label:
                states.append(label.title())

    return states


def _is_numeric_list(value):
    """
    Return True when a value is a non-empty numeric list
    """
    if not isinstance(value, list) or not value:
        return False

    return all(isinstance(item, Number) for item in value)


def _as_number(value):
    """
    Return a numeric value or None
    """
    if isinstance(value, Number) and not isinstance(value, bool):
        return value

    return None


def _format_number(value):
    """
    Format a number for compact display
    """
    if isinstance(value, int):
        return f"{value:,}"

    if isinstance(value, float):
        return f"{value:g}"

    return str(value)


def _format_number_range(values, unit=""):
    """
    Format a list of numeric values as a compact range
    """
    if not values:
        return "-"

    low = min(values)
    high = max(values)
    suffix = f" {unit}" if unit else ""

    if low == high:
        return f"{_format_number(low)}{suffix}"

    return f"{_format_number(low)} - {_format_number(high)}{suffix}"


def _format_common_value(counter):
    """
    Format the most common value from a counter
    """
    if not counter:
        return "-"

    value, count = counter.most_common(1)[0]

    if len(counter) == 1:
        return value

    return f"{value} ({count} objects)"


def _format_common_unit(counter):
    """
    Return the most common unit label from a counter
    """
    if not counter:
        return ""

    return counter.most_common(1)[0][0]


def _serialize_counter(counter, limit=10):
    """
    Serialize a counter into chart labels and series
    """
    items = counter.most_common(limit)
    labels = [item[0] for item in items]
    series = [item[1] for item in items]
    return labels, series


def _count_once_per_object(counter, labels, fallback="Not specified"):
    """
    Count a label once for each object
    """
    unique_labels = sorted(set(label for label in labels if label))

    if not unique_labels:
        counter[fallback] += 1
        return

    for label in unique_labels:
        counter[label] += 1


def _format_label_list(labels, default="Not specified"):
    """
    Format a set of labels into one compact display value
    """
    unique_labels = sorted(set(label for label in labels if label))

    if not unique_labels:
        return default

    return " / ".join(unique_labels)


def _format_optional_number(value, unit=""):
    """
    Format a scalar metadata number for display
    """
    number = _as_number(value)

    if number is None:
        return "-"

    suffix = f" {unit}" if unit else ""
    return f"{_format_number(number)}{suffix}"


def _format_unit(value):
    """
    Format a unit value without showing unitless placeholders
    """
    if value in {None, "", 1, "1"}:
        return ""

    return str(value)


def _format_rve_size(data):
    """
    Format RVE size metadata as one display value
    """
    rve_size = data.get("RVE_size")

    if not isinstance(rve_size, list) or not rve_size:
        return "-"

    size_parts = []

    for item in rve_size:
        number = _as_number(item)

        if number is not None:
            size_parts.append(_format_number(number))

    if not size_parts:
        return "-"

    return " x ".join(size_parts)


def _get_nested_value(data, path):
    """
    Return a nested dictionary value for the given path
    """
    value = data

    for key in path:
        if not isinstance(value, dict):
            return None

        value = value.get(key)

    return value


def _get_numeric_series(data, path):
    """
    Return a numeric series from a nested JSON path
    """
    value = _get_nested_value(data, path)

    if _is_numeric_list(value):
        return value

    return []


def _peak_abs(values):
    """
    Return the largest absolute value in a numeric series
    """
    if not values:
        return None

    return max(abs(value) for value in values)


def _build_response_summary(data):
    """
    Build stress strain readiness values for one data object
    """
    stress_values = _get_numeric_series(data, ("stress", "stress_11"))
    strain_values = _get_numeric_series(data, ("total_strain", "strain_11"))
    plastic_values = _get_numeric_series(data, ("plastic_strain", "plastic_strain_11"))
    is_ready = bool(stress_values and strain_values)
    point_count = 0

    if is_ready:
        point_count = min(len(stress_values), len(strain_values))

    return {
        "is_ready": is_ready,
        "point_count": point_count,
        "stress_peak": _peak_abs(stress_values),
        "strain_peak": _peak_abs(strain_values),
        "plastic_peak": _peak_abs(plastic_values),
    }


def _build_response_row(obj, data, response_summary):
    """
    Build one row for the response readiness table
    """
    units = data.get("units") if isinstance(data.get("units"), dict) else {}
    stress_unit = _format_unit(units.get("Stress"))
    strain_unit = _format_unit(units.get("Strain"))
    status = "Ready" if response_summary["is_ready"] else "Missing stress/strain"
    status_class = "success" if response_summary["is_ready"] else "secondary"
    phase_label = _format_label_list(_extract_phase_labels(data.get("phase")))
    model_label = _format_label_list(_extract_constitutive_model_labels(data))
    loading_type = _format_label_list(_extract_mechanical_values(data, "loading_type"))
    loading_mode = _format_label_list(_extract_mechanical_values(data, "loading_mode"))

    return {
        "id": obj.pk,
        "identifier": _normalize_text(data.get("identifier") or data.get("title"), default="Object"),
        "phase": phase_label,
        "model": model_label,
        "loading": f"{loading_type} / {loading_mode}",
        "points": _format_number(response_summary["point_count"]) if response_summary["point_count"] else "-",
        "stress_peak": _format_number_range(
            [response_summary["stress_peak"]] if response_summary["stress_peak"] is not None else [],
            unit=stress_unit,
        ),
        "strain_peak": _format_number_range(
            [response_summary["strain_peak"]] if response_summary["strain_peak"] is not None else [],
            unit=strain_unit,
        ),
        "plastic_peak": _format_number_range(
            [response_summary["plastic_peak"]] if response_summary["plastic_peak"] is not None else [],
            unit=strain_unit,
        ),
        "status": status,
        "status_class": status_class,
        "is_ready": response_summary["is_ready"],
    }


def _extract_applied_load_numbers(data, key):
    """
    Extract numeric values from mechanical applied load metadata
    """
    mechanical_bc = data.get("mechanical_BC", [])

    if not isinstance(mechanical_bc, list):
        return []

    values = []

    for condition in mechanical_bc:
        if not isinstance(condition, dict):
            continue

        applied_load = condition.get("applied_load", [])

        if isinstance(applied_load, dict):
            entries = [applied_load]
        elif isinstance(applied_load, list):
            entries = applied_load
        else:
            entries = []

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            number = _as_number(entry.get(key))

            if number is not None:
                values.append(number)

    return values


def _extract_phase_summaries(data):
    """
    Extract phase and constitutive model summaries from one data object

    Current phase names label each model without changing stored metadata.

    Parameters
    ----------
    data : dict
        Stored simulation data object.

    Returns
    -------
    list of dict
        Phase labels with their material model information.
    """
    summaries = []

    for phase in _iter_phase_items(data.get("phase")):
        phase_label = _normalize_text(
            _normalize_text(phase.get("phase_name"), default="")
            or phase.get("phase_identifier")
            or phase.get("material")
            or phase.get("name")
            or phase.get("title")
        )
        model = phase.get("constitutive_model")

        if not isinstance(model, dict):
            model = {}

        elastic_parameters = model.get("elastic_parameters")
        plastic_parameters = model.get("plastic_parameters")
        model_units = model.get("units")

        summaries.append(
            {
                "phase": phase_label,
                "elastic_model": _normalize_text(model.get("elastic_model_name"), default="-"),
                "plastic_model": _normalize_text(model.get("plastic_model_name"), default="-"),
                "elastic_parameters": elastic_parameters if isinstance(elastic_parameters, dict) else {},
                "plastic_parameters": plastic_parameters if isinstance(plastic_parameters, dict) else {},
                "units": model_units if isinstance(model_units, dict) else {},
            }
        )

    if summaries:
        return summaries

    return [
        {
            "phase": label,
            "elastic_model": "-",
            "plastic_model": "-",
            "elastic_parameters": {},
            "plastic_parameters": {},
            "units": {},
        }
        for label in _extract_phase_labels(data.get("phase"))
    ]


def _append_parameter_value(values_by_name, key, value):
    """
    Append a numeric model parameter value when present
    """
    number = _as_number(value)

    if number is None:
        return

    values_by_name.setdefault(key, []).append(number)


def _collect_material_model_group(groups, data):
    """
    Add one data object's material model metadata to grouped summaries
    """
    for summary in _extract_phase_summaries(data):
        model_label = summary["plastic_model"]

        if model_label == "-":
            model_label = summary["elastic_model"]

        key = (summary["phase"], model_label)

        if key not in groups:
            groups[key] = {
                "phase": summary["phase"],
                "model": model_label,
                "count": 0,
                "elastic_models": Counter(),
                "plastic_models": Counter(),
                "stiffness_unit": Counter(),
                "stress_unit": Counter(),
                "elastic_values": {},
                "plastic_values": {},
            }

        group = groups[key]
        group["count"] += 1

        if summary["elastic_model"] != "-":
            group["elastic_models"][summary["elastic_model"]] += 1

        if summary["plastic_model"] != "-":
            group["plastic_models"][summary["plastic_model"]] += 1

        stiffness_unit = _format_unit(summary["units"].get("Stiffness"))
        stress_unit = _format_unit(summary["units"].get("Stress"))

        if stiffness_unit:
            group["stiffness_unit"][stiffness_unit] += 1

        if stress_unit:
            group["stress_unit"][stress_unit] += 1

        for key in ("C11", "C12", "C44"):
            _append_parameter_value(
                group["elastic_values"],
                key,
                summary["elastic_parameters"].get(key),
            )

        for key in (
            "initial_critical_resolved_shear_stress",
            "saturated_slip_resistance",
            "hardening_exponent",
            "reference_hardening_rate",
        ):
            _append_parameter_value(
                group["plastic_values"],
                key,
                summary["plastic_parameters"].get(key),
            )


def _format_named_ranges(values_by_name, fields, unit=""):
    """
    Format selected parameter ranges from a grouped value dictionary
    """
    parts = []

    for key, label in fields:
        values = values_by_name.get(key, [])

        if values:
            parts.append(f"{label} {_format_number_range(values, unit=unit)}")

    if not parts:
        return "-"

    return "; ".join(parts)


def _build_material_model_rows(groups, limit=8):
    """
    Build material model parameter rows for display
    """
    rows = []

    for group in groups.values():
        stiffness_unit = ""
        stress_unit = ""

        if group["stiffness_unit"]:
            stiffness_unit = group["stiffness_unit"].most_common(1)[0][0]

        if group["stress_unit"]:
            stress_unit = group["stress_unit"].most_common(1)[0][0]

        rows.append(
            {
                "phase": group["phase"],
                "model": group["model"],
                "objects": group["count"],
                "elastic_model": _format_common_value(group["elastic_models"]),
                "plastic_model": _format_common_value(group["plastic_models"]),
                "stiffness": _format_named_ranges(
                    group["elastic_values"],
                    (("C11", "C11"), ("C12", "C12"), ("C44", "C44")),
                    unit=stiffness_unit,
                ),
                "strength": _format_named_ranges(
                    group["plastic_values"],
                    (
                        ("initial_critical_resolved_shear_stress", "CRSS"),
                        ("saturated_slip_resistance", "Sat."),
                    ),
                    unit=stress_unit,
                ),
                "hardening": _format_named_ranges(
                    group["plastic_values"],
                    (
                        ("hardening_exponent", "n"),
                        ("reference_hardening_rate", "h0"),
                    ),
                ),
            }
        )

    rows.sort(key=lambda item: (-item["objects"], item["phase"], item["model"]))
    return rows[:limit]


def _add_comparable_group(groups, obj, data, response_summary):
    """
    Add one object to a simulation comparability group
    """
    phase_label = _format_label_list(_extract_phase_labels(data.get("phase")))
    software_label = _normalize_text(data.get("software"), default="Not specified")
    model_label = _format_label_list(_extract_constitutive_model_labels(data))
    loading_type = _format_label_list(_extract_mechanical_values(data, "loading_type"))
    loading_mode = _format_label_list(_extract_mechanical_values(data, "loading_mode"))
    temperature = _format_optional_number(data.get("global_temperature"), unit="K")
    mesh_count = _format_optional_number(data.get("discretization_count"))
    rve_size = _format_rve_size(data)
    key = (
        phase_label,
        software_label,
        model_label,
        loading_type,
        loading_mode,
        temperature,
        mesh_count,
        rve_size,
    )

    if key not in groups:
        groups[key] = {
            "phase": phase_label,
            "software": software_label,
            "model": model_label,
            "loading_type": loading_type,
            "loading_mode": loading_mode,
            "temperature": temperature,
            "mesh_count": mesh_count,
            "rve_size": rve_size,
            "objects": 0,
            "ready": 0,
            "representative_id": obj.pk,
        }

    groups[key]["objects"] += 1

    if response_summary["is_ready"]:
        groups[key]["ready"] += 1


def _build_comparable_group_rows(groups, limit=8):
    """
    Build comparable simulation group rows for display
    """
    rows = []

    for group in groups.values():
        ready = group["ready"]
        objects = group["objects"]
        readiness_class = "secondary"
        group_status = "Single setup"
        group_status_class = "secondary"

        if ready == objects and objects:
            readiness_class = "success"
        elif ready:
            readiness_class = "warning"

        if objects >= 2:
            group_status = "Comparable"
            group_status_class = "success"

        rows.append(
            {
                **group,
                "setup": f"{group['software']} / {group['model']}",
                "loading": f"{group['loading_type']} / {group['loading_mode']}",
                "conditions": (
                    f"{group['temperature']} / "
                    f"{group['mesh_count']} cells / "
                    f"RVE {group['rve_size']}"
                ),
                "ready_label": f"{ready} / {objects}",
                "readiness_class": readiness_class,
                "group_status": group_status,
                "group_status_class": group_status_class,
            }
        )

    rows.sort(
        key=lambda item: (
            -item["objects"],
            -item["ready"],
            item["phase"],
            item["setup"],
        )
    )
    return rows[:limit]


def _collect_constraint_axis_counts(axis_counters, data):
    """
    Add axis level constraint states from mechanical boundary conditions
    """
    mechanical_bc = data.get("mechanical_BC", [])

    if not isinstance(mechanical_bc, list):
        return

    for condition in mechanical_bc:
        if not isinstance(condition, dict):
            continue

        constraints = condition.get("constraints", [])

        if not isinstance(constraints, list):
            continue

        for index, axis in enumerate(CONSTRAINT_AXES):
            if index >= len(constraints):
                continue

            state = _normalize_text(constraints[index], default="Other").title()

            if state not in CONSTRAINT_STATES:
                state = "Other"

            axis_counters[axis][state] += 1


def _build_constraint_matrix_rows(axis_counters):
    """
    Build rows for the boundary condition axis matrix
    """
    rows = []

    for axis in CONSTRAINT_AXES:
        counter = axis_counters[axis]
        total = sum(counter.values())
        rows.append(
            {
                "axis": axis,
                "fixed": counter["Fixed"],
                "loaded": counter["Loaded"],
                "free": counter["Free"],
                "other": counter["Other"],
                "total": total,
            }
        )

    return rows


def _get_quality_checks(data, response_summary):
    """
    Return ordered metadata quality checks for one data object
    """
    units = data.get("units")

    return [
        ("Phase metadata", bool(_extract_phase_labels(data.get("phase")))),
        ("Software / solver", _has_value(data.get("software"))),
        ("Constitutive model", bool(_extract_constitutive_model_labels(data))),
        ("Mechanical BC", _has_value(data.get("mechanical_BC"))),
        ("Global temperature", _as_number(data.get("global_temperature")) is not None),
        ("Mesh cells", _as_number(data.get("discretization_count")) is not None),
        ("RVE size", _format_rve_size(data) != "-"),
        ("Stress strain arrays", response_summary["is_ready"]),
        ("Units", isinstance(units, dict) and bool(units)),
    ]


def _build_quality_rows(present_counter, total_objects):
    """
    Build metadata coverage rows for display
    """
    rows = []

    for label in QUALITY_CHECK_LABELS:
        present = present_counter[label]
        missing = total_objects - present
        coverage = 0

        if total_objects:
            coverage = round((present / total_objects) * 100)

        status_class = "success"

        if coverage < 70:
            status_class = "danger"
        elif coverage < 100:
            status_class = "warning"

        rows.append(
            {
                "label": label,
                "present": present,
                "missing": missing,
                "coverage": coverage,
                "status_class": status_class,
            }
        )

    return rows


def _build_quality_issue_rows(present_counter, total_objects, issue_examples):
    """
    Build rows that point to the most important metadata gaps
    """
    rows = []

    for label in QUALITY_CHECK_LABELS:
        missing = total_objects - present_counter[label]

        if missing <= 0:
            continue

        example = issue_examples.get(label, {})
        status_class = "warning"

        if missing == total_objects:
            status_class = "danger"

        rows.append(
            {
                "label": label,
                "missing": missing,
                "status_class": status_class,
                "example_id": example.get("id"),
                "example_label": example.get("label", "-"),
            }
        )

    rows.sort(key=lambda item: (-item["missing"], item["label"]))
    return rows[:6]


def _build_condition_rows(stats):
    """
    Build compact simulation condition rows for the charts page
    """
    rve_value = "-"

    if stats["rve_total"]:
        rve_value = f"{stats['rve_continuous_count']} / {stats['rve_total']} continuous"

    return [
        {
            "label": "Metadata Date",
            "value": _format_common_value(stats["date_counter"]),
        },
        {
            "label": "Global Temperature",
            "value": _format_number_range(stats["temperature_values"], unit="K"),
        },
        {
            "label": "Mesh Cells",
            "value": _format_number_range(stats["mesh_values"]),
        },
        {
            "label": "RVE Size",
            "value": _format_common_value(stats["rve_size_counter"]),
        },
        {
            "label": "RVE Continuity",
            "value": rve_value,
        },
        {
            "label": "Load Magnitude",
            "value": _format_number_range(
                stats["load_magnitude_values"],
                unit=stats["force_unit"],
            ),
        },
        {
            "label": "Load Duration",
            "value": _format_number_range(stats["load_duration_values"]),
        },
        {
            "label": "Load Ratio R",
            "value": _format_number_range(stats["load_ratio_values"]),
        },
    ]


@login_required
def index(request):
    """
    Display simulation metadata charts for accessible data objects
    """
    data_objects = list(
        JSONData.objects
        .filter(
            Q(owner=request.user)
            | Q(access_type="all")
            | Q(shared_users=request.user, access_type="c")
        )
        .select_related("owner")
        .prefetch_related("shared_users")
        .distinct()
        .order_by("-uploaded_at")
    )

    phase_counter = Counter()
    software_counter = Counter()
    loading_type_counter = Counter()
    loading_mode_counter = Counter()
    model_counter = Counter()
    constraint_counter = Counter()
    date_counter = Counter()
    rve_size_counter = Counter()
    quality_present_counter = Counter()
    force_unit_counter = Counter()
    stress_unit_counter = Counter()
    strain_unit_counter = Counter()
    axis_counters = {axis: Counter() for axis in CONSTRAINT_AXES}
    material_model_groups = {}
    comparable_groups = {}
    quality_issue_examples = {}

    temperature_values = []
    mesh_values = []
    load_magnitude_values = []
    load_duration_values = []
    load_ratio_values = []
    response_point_values = []
    stress_peak_values = []
    strain_peak_values = []
    plastic_peak_values = []
    response_rows = []
    mechanical_bc_count = 0
    plot_ready_count = 0
    rve_continuous_count = 0
    rve_total = 0
    data_gap_count = 0

    for obj in data_objects:
        data = obj.data or {}
        units = data.get("units") if isinstance(data.get("units"), dict) else {}
        phase_labels = _extract_phase_labels(data.get("phase"))
        software_label = _normalize_text(data.get("software"), default="")
        model_labels = _extract_constitutive_model_labels(data)
        loading_type_labels = _extract_mechanical_values(data, "loading_type")
        loading_mode_labels = _extract_mechanical_values(data, "loading_mode")
        response_summary = _build_response_summary(data)
        force_unit = _format_unit(units.get("Force"))
        stress_unit = _format_unit(units.get("Stress"))
        strain_unit = _format_unit(units.get("Strain"))

        if force_unit:
            force_unit_counter[force_unit] += 1

        if stress_unit:
            stress_unit_counter[stress_unit] += 1

        if strain_unit:
            strain_unit_counter[strain_unit] += 1

        _count_once_per_object(phase_counter, phase_labels)
        _count_once_per_object(software_counter, [software_label])
        _count_once_per_object(model_counter, model_labels)
        _count_once_per_object(loading_type_counter, loading_type_labels)
        _count_once_per_object(loading_mode_counter, loading_mode_labels)

        for constraint_state in _extract_constraint_states(data):
            constraint_counter[constraint_state] += 1

        _collect_constraint_axis_counts(axis_counters, data)
        _collect_material_model_group(material_model_groups, data)
        _add_comparable_group(comparable_groups, obj, data, response_summary)

        if _has_value(data.get("mechanical_BC")):
            mechanical_bc_count += 1

        if response_summary["is_ready"]:
            plot_ready_count += 1
            response_point_values.append(response_summary["point_count"])

        if response_summary["stress_peak"] is not None:
            stress_peak_values.append(response_summary["stress_peak"])

        if response_summary["strain_peak"] is not None:
            strain_peak_values.append(response_summary["strain_peak"])

        if response_summary["plastic_peak"] is not None:
            plastic_peak_values.append(response_summary["plastic_peak"])

        response_rows.append(_build_response_row(obj, data, response_summary))

        missing_any_quality_field = False

        for label, is_present in _get_quality_checks(data, response_summary):
            if is_present:
                quality_present_counter[label] += 1
            else:
                missing_any_quality_field = True

                if label not in quality_issue_examples:
                    quality_issue_examples[label] = {
                        "id": obj.pk,
                        "label": _normalize_text(
                            data.get("identifier") or data.get("title"),
                            default=f"Object {obj.pk}",
                        ),
                    }

        if missing_any_quality_field:
            data_gap_count += 1

        temperature = _as_number(data.get("global_temperature"))

        if temperature is not None:
            temperature_values.append(temperature)

        mesh_count = _as_number(data.get("discretization_count"))

        if mesh_count is not None:
            mesh_values.append(mesh_count)

        rve_size_label = _format_rve_size(data)

        if rve_size_label != "-":
            rve_size_counter[rve_size_label] += 1

        if data.get("RVE_continuity") is not None:
            rve_total += 1

            if data.get("RVE_continuity") is True:
                rve_continuous_count += 1

        date_value = _normalize_text(data.get("date"), default="")

        if date_value:
            date_counter[date_value] += 1

        load_magnitude_values.extend(_extract_applied_load_numbers(data, "magnitude"))
        load_duration_values.extend(_extract_applied_load_numbers(data, "duration"))
        load_ratio_values.extend(_extract_applied_load_numbers(data, "R"))

    total_objects = len(data_objects)
    comparable_group_rows = _build_comparable_group_rows(comparable_groups)
    comparable_group_count = sum(
        1 for group in comparable_groups.values() if group["objects"] >= 2
    )
    material_model_rows = _build_material_model_rows(material_model_groups)
    constraint_matrix_rows = _build_constraint_matrix_rows(axis_counters)
    quality_rows = _build_quality_rows(quality_present_counter, total_objects)
    quality_issue_rows = _build_quality_issue_rows(
        quality_present_counter,
        total_objects,
        quality_issue_examples,
    )
    response_rows.sort(key=lambda row: (not row["is_ready"], row["identifier"]))
    response_rows = response_rows[:8]
    phase_labels, phase_series = _serialize_counter(phase_counter)
    software_labels, software_series = _serialize_counter(software_counter)
    loading_type_labels, loading_type_series = _serialize_counter(loading_type_counter)
    loading_mode_labels, loading_mode_series = _serialize_counter(loading_mode_counter)
    model_labels, model_series = _serialize_counter(model_counter)
    constraint_labels, constraint_series = _serialize_counter(constraint_counter)
    condition_rows = _build_condition_rows(
        {
            "temperature_values": temperature_values,
            "mesh_values": mesh_values,
            "rve_size_counter": rve_size_counter,
            "rve_continuous_count": rve_continuous_count,
            "rve_total": rve_total,
            "date_counter": date_counter,
            "load_magnitude_values": load_magnitude_values,
            "load_duration_values": load_duration_values,
            "load_ratio_values": load_ratio_values,
            "force_unit": _format_common_unit(force_unit_counter),
        }
    )
    response_overview_rows = [
        {
            "label": "Curve-Ready Objects",
            "value": f"{plot_ready_count} / {total_objects}",
        },
        {
            "label": "Response Points",
            "value": _format_number_range(response_point_values),
        },
        {
            "label": "Peak |stress_11|",
            "value": _format_number_range(
                stress_peak_values,
                unit=_format_common_unit(stress_unit_counter),
            ),
        },
        {
            "label": "Peak |strain_11|",
            "value": _format_number_range(
                strain_peak_values,
                unit=_format_common_unit(strain_unit_counter),
            ),
        },
        {
            "label": "Peak |plastic_strain_11|",
            "value": _format_number_range(
                plastic_peak_values,
                unit=_format_common_unit(strain_unit_counter),
            ),
        },
    ]

    context = {
        "segment": "charts",
        "total_objects": total_objects,
        "comparable_group_count": comparable_group_count,
        "phase_count": len(phase_counter),
        "mechanical_bc_count": mechanical_bc_count,
        "plot_ready_count": plot_ready_count,
        "data_gap_count": data_gap_count,
        "condition_rows": condition_rows,
        "response_overview_rows": response_overview_rows,
        "comparable_group_rows": comparable_group_rows,
        "response_rows": response_rows,
        "material_model_rows": material_model_rows,
        "constraint_matrix_rows": constraint_matrix_rows,
        "quality_rows": quality_rows,
        "quality_issue_rows": quality_issue_rows,
        "phase_labels_json": json.dumps(phase_labels),
        "phase_series_json": json.dumps(phase_series),
        "software_labels_json": json.dumps(software_labels),
        "software_series_json": json.dumps(software_series),
        "loading_type_labels_json": json.dumps(loading_type_labels),
        "loading_type_series_json": json.dumps(loading_type_series),
        "loading_mode_labels_json": json.dumps(loading_mode_labels),
        "loading_mode_series_json": json.dumps(loading_mode_series),
        "model_labels_json": json.dumps(model_labels),
        "model_series_json": json.dumps(model_series),
        "constraint_labels_json": json.dumps(constraint_labels),
        "constraint_series_json": json.dumps(constraint_series),
    }
    return render(request, "charts/index.html", context)
