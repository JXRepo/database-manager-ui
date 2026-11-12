"""
Measure collection graph work against isolated synthetic long-curve records
"""

import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def arguments():
    """
    Read the explicit local database and benchmark operation

    Returns
    -------
    Namespace
        Synthetic dataset dimensions and isolated database settings.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "baseline", "current", "cold"))
    parser.add_argument("--settings", required=True)
    parser.add_argument("--objects", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--baseline-ref", default="3e86b6a")
    options = parser.parse_args()
    if not 1 <= options.objects <= 1000 or not 1 <= options.samples <= 100000:
        parser.error("Use 1–1000 objects and 1–100000 samples per component.")
    if not 1 <= options.repeats <= 10:
        parser.error("Use 1–10 repetitions.")
    return options


def prepare(options):
    """
    Populate an empty benchmark database with owned synthetic records

    Parameters
    ----------
    options : Namespace
        Object count and sample count per mechanical component.
    """
    from django.contrib.auth.models import User
    from django.core.management import call_command
    from django.db import connection
    from apps.pages.models import JSONData, ResearchCollection

    call_command("migrate", verbosity=0, interactive=False)
    if User.objects.exists() or JSONData.objects.exists():
        raise RuntimeError("Prepare requires an empty isolated benchmark database.")
    owner = User.objects.create_user(username="collection-benchmark")
    collection = ResearchCollection.objects.create(owner=owner, title="Synthetic long curves")
    components = ("11", "22", "33", "12", "13", "23")
    curves = {
        quantity: {
            f"{quantity}_{component}": [round(index * scale * (offset + 1), 6)
                                       for index in range(options.samples)]
            for offset, component in enumerate(components)
        }
        for quantity, scale in (("stress", 0.0137), ("total_strain", 0.000013))
    }
    batch = []
    raw_bytes = 0
    started = time.perf_counter()
    for index in range(options.objects):
        data = {
            "identifier": f"benchmark-{index:04d}", "title": f"Synthetic simulation {index}",
            "creator": "Benchmark researcher", "software": "DAMASK", "software_version": "3.0",
            "phase": [{"phase_name": "Copper"}],
            "relation": [f"10.1234/benchmark-{index % 20}"],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic"}],
            **curves,
        }
        size = len(json.dumps(data, separators=(",", ":")).encode())
        raw_bytes += size
        batch.append(JSONData(owner=owner, data=data, size_bytes=size))
        if len(batch) == 10 or index + 1 == options.objects:
            JSONData.objects.bulk_create(batch, batch_size=10)
            collection.members.add(*batch)
            batch.clear()
            connection.queries_log.clear()
    print(json.dumps({"mode": "prepare", "objects": options.objects,
                      "samples_per_component": options.samples, "components": 12,
                      "raw_json_bytes": raw_bytes, "seconds": time.perf_counter() - started}))


def measure(options):
    """
    Measure repeated graph builds in the current fresh Python process

    Parameters
    ----------
    options : Namespace
        Implementation choice and number of repetitions.
    """
    from django.db import connection
    from django.db.models import Sum
    from django.http import QueryDict
    from apps.pages.collection_graph import CollectionSummaryPending, build_collection_context
    from apps.pages.models import ResearchCollection
    from apps.pages.research_collections import accessible_objects

    collection = ResearchCollection.objects.select_related("owner").get(title="Synthetic long curves")
    objects = accessible_objects(collection.owner).filter(research_collections=collection)
    count = objects.count()
    if count != options.objects:
        raise RuntimeError("The benchmark dataset does not match --objects.")
    if options.mode == "baseline":
        source = subprocess.check_output(
            ["git", "show", f"{options.baseline_ref}:apps/pages/collection_graph.py"],
            cwd=ROOT, text=True,
        )
        module = ModuleType("apps.pages.collection_graph_baseline")
        module.__package__ = "apps.pages"
        exec(compile(source, "collection_graph_baseline.py", "exec"), module.__dict__)
        build_collection_context = module.build_collection_context
    elif options.mode == "cold":
        objects.update(collection_summary=None)
    raw_bytes = objects.aggregate(total=Sum("size_bytes"))["total"]
    connection.queries_log.clear()
    baseline_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    timings = []
    progress = []
    for _ in range(options.objects + 10 if options.mode == "cold" else options.repeats):
        started = time.perf_counter()
        try:
            context = build_collection_context(objects, title=collection.title,
                                               base_url="/graph/collections/1/", params=QueryDict())
        except CollectionSummaryPending as pending:
            timings.append(time.perf_counter() - started)
            if options.mode != "cold" or pending.requires_admin:
                raise RuntimeError("This dataset needs operator preparation before benchmarking.") from pending
            progress.append(pending.ready_count)
            if len(progress) >= 10 and progress[-10] == progress[-1]:
                raise RuntimeError("Cold preparation stopped making progress.")
            continue
        timings.append(time.perf_counter() - started)
        if context["object_total"] != count or len(context["object_rows"]) != min(count, 25):
            raise AssertionError("Graph counts changed during the benchmark.")
        if options.mode == "cold":
            break
    else:
        if options.mode == "cold":
            raise RuntimeError("Cold preparation exceeded the bounded request count.")
    queries = [item["sql"] for item in connection.queries]
    raw_reads = sum('"pages_jsondata"."data"' in query for query in queries)
    if options.mode == "current" and raw_reads:
        raise AssertionError("A warm graph still selected raw JSON.")
    summary_bytes = sum(len(json.dumps(value, separators=(",", ":")).encode())
                        for value in objects.values_list("collection_summary", flat=True)
                        if value is not None)
    print(json.dumps({
        "mode": options.mode, "objects": count, "samples_per_component": options.samples,
        "raw_json_bytes": raw_bytes, "summary_json_bytes": summary_bytes,
        "seconds": timings, "median_seconds": statistics.median(timings),
        "total_seconds": sum(timings), "max_request_seconds": max(timings),
        "preparation_progress": progress,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "peak_rss_before_build_mib": baseline_rss / 1024,
        "raw_json_selects": raw_reads, "database": connection.vendor,
    }))


def main():
    """
    Reject nonlocal databases before any benchmark migration or write
    """
    options = arguments()
    os.environ["DJANGO_SETTINGS_MODULE"] = options.settings
    os.environ["DEBUG"] = "True"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection

    database = connection.settings_dict
    if (not settings.DEBUG or connection.vendor != "postgresql"
            or database["HOST"] != "127.0.0.1"
            or database["NAME"] != "collection_benchmark"):
        raise RuntimeError("Use DEBUG=True and the isolated loopback collection_benchmark database.")
    if options.mode == "prepare":
        prepare(options)
    else:
        measure(options)


if __name__ == "__main__":
    main()
