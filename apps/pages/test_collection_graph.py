"""
Keep collection discovery based on supplied values and bounded accessible records
"""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import TestCase

from .collection_graph import build_collection_context
from .models import JSONData


class CollectionGraphTests(TestCase):
    """
    Check explicit references, metadata grouping and bounded graph rendering
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create a record owner without relying on production fixtures
        """
        cls.owner = User.objects.create_user(username="collection-graph-owner")

    def record(self, data):
        """
        Save a synthetic record with its original metadata

        Parameters
        ----------
        data : dict
            Metadata used by one test.

        Returns
        -------
        JSONData
            The saved independent record.
        """
        return JSONData.objects.create(owner=self.owner, data=data)

    def context(self, query="", objects=None):
        """
        Build the workspace from an explicitly scoped queryset

        Parameters
        ----------
        query : str, optional
            Encoded graph controls.
        objects : QuerySet, optional
            Records made accessible by the caller.

        Returns
        -------
        dict
            Template context with bounded graph and comparison rows.
        """
        return build_collection_context(
            objects if objects is not None else JSONData.objects.all(),
            title="Cyclic study", base_url="/graph/collections/42/", params=QueryDict(query),
        )

    def test_declared_references_count_each_object_once(self):
        """
        Combine explicit DOI spellings without inventing relationships between records
        """
        first = self.record({"title": "Run A", "relation": ["10.1234/Example", "https://doi.org/10.1234/example", "doi:10.1234/EXAMPLE"]})
        second = self.record({"title": "Run B", "relation": "https://dx.doi.org/10.1234/Example"})
        context = self.context()
        self.assertEqual(context["object_total"], 2)
        self.assertEqual(len(context["group_options"]), 1)
        self.assertEqual(context["group_options"][0]["count"], 2)
        self.assertTrue(context["auto_expanded"])
        graph = context["relationship_graph"]
        self.assertEqual({node["object_pk"] for node in graph["nodes"] if node["kind"] == "record"}, {first.pk, second.pk})
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 3)
        group = context["group_options"][0]
        selected = self.context("group=" + group["key"])
        self.assertEqual(selected["matching_object_count"], 2)
        edges = selected["relationship_graph"]["edges"]
        self.assertEqual(len(edges), 3)
        self.assertTrue(all("Declared by" in edge["label"] for edge in edges[1:]))
        self.assertNotIn("derived", str(edges).casefold())

    def test_shared_groups_connect_each_member_without_duplicating_object_nodes(self):
        """
        Keep one object identity and every supplied membership in small overviews
        """
        first = self.record({
            "title": "Run A", "relation": ["10.1234/common", "10.1234/first"],
            "software": ["Abaqus", "DAMASK"],
            "phase": [{"phase_name": "Copper"}, {"phase_name": "Steel"}],
        })
        second = self.record({
            "title": "Run B", "relation": "10.1234/common", "software": "DAMASK",
            "phase": [{"phase_name": "Steel"}],
        })
        original = deepcopy(first.data)
        for mode in ("relations", "software", "phase"):
            with self.subTest(mode=mode):
                context = self.context("links=" + mode)
                graph = context["relationship_graph"]
                members = [node for node in graph["nodes"] if node["kind"] == "record"]
                self.assertTrue(context["auto_expanded"])
                self.assertEqual(len(graph["nodes"]), 5)
                self.assertEqual(len(graph["edges"]), 5)
                self.assertEqual({node["object_pk"] for node in members}, {first.pk, second.pk})
                group_labels = {node["id"]: node["label"] for node in graph["nodes"]}
                for node in members:
                    expected = 2 if node["object_pk"] == first.pk else 1
                    incoming = [edge for edge in graph["edges"] if edge["target"] == node["id"]]
                    self.assertEqual(len(incoming), expected)
                    self.assertEqual(len({edge["source"] for edge in incoming}), expected)
                    self.assertEqual(len(node["connections"]), expected)
                    self.assertTrue(all(connection["direction"] == "Incoming" for connection in node["connections"]))
                    if node["object_pk"] == second.pk:
                        shared = {"relations": "10.1234/common", "software": "DAMASK", "phase": "Steel"}[mode]
                        self.assertEqual({group_labels[edge["source"]] for edge in incoming}, {shared})
                for layout in graph["layouts"].values():
                    self.assertEqual(len(layout["positions"]), 5)
                    self.assertEqual(len(layout["paths"]), 5)
        first.refresh_from_db()
        self.assertEqual(first.data, original)

    def test_missing_relations_default_to_members_but_explicit_scope_is_retained(self):
        """
        Open actual records immediately without overriding a requested relationship view
        """
        first = self.record({"title": "Run A", "software": "DAMASK"})
        second = self.record({"title": "Run B"})
        context = self.context("view=detailed")
        self.assertEqual(context["links_mode"], "members")
        self.assertEqual(context["graph_view_mode"], "detailed")
        self.assertFalse(context["auto_expanded"])
        self.assertEqual(context["group_options"], [])
        self.assertEqual({node["object_pk"] for node in context["relationship_graph"]["nodes"] if node["kind"] == "record"}, {first.pk, second.pk})
        for query in ("links=relations", "group=missing", "group="):
            with self.subTest(query=query):
                explicit = self.context(query)
                self.assertEqual(explicit["links_mode"], "relations")
                self.assertEqual(explicit["group_options"][0]["key"], "missing")
                self.assertEqual(explicit["matching_object_count"], 2)
                self.assertEqual(len(explicit["relationship_graph"]["nodes"]), 4)
        software = self.context("links=software")
        missing = next(group for group in software["group_options"] if group["key"] == "missing")
        selected = self.context("links=software&group=" + missing["key"])
        self.assertEqual([row["pk"] for row in selected["object_rows"]], [second.pk])
        self.assertFalse(selected["auto_expanded"])

    def test_arbitrary_relations_keep_case_sensitive_identity(self):
        """
        Preserve distinct URL paths and literal text outside recognized DOI forms
        """
        self.record({"relation": ["https://example.org/Run", "https://example.org/run", "Example", "example"]})
        self.record({"relation": ["https://example.org/Run"]})
        groups = self.context()["group_options"]
        self.assertEqual(len(groups), 4)
        self.assertEqual({group["label"]: group["count"] for group in groups}, {
            "https://example.org/Run": 2, "https://example.org/run": 1,
            "Example": 1, "example": 1,
        })

    def test_numeric_software_versions_remain_visible_in_rows_and_nodes(self):
        """
        Preserve numeric version values without treating them as software names
        """
        for value in (2024, 3.0, 0, ["2025", 2.5]):
            obj = self.record({"software": "Abaqus", "software_version": value})
            context = self.context("links=members", JSONData.objects.filter(pk=obj.pk))
            expected = "; ".join(str(item) for item in value) if isinstance(value, list) else str(value)
            self.assertEqual(context["object_rows"][0]["software_version"], expected)
            self.assertIn({"label": "Recorded versions", "value": expected}, context["relationship_graph"]["nodes"][1]["details"])
            obj.refresh_from_db()
            self.assertEqual(obj.data["software_version"], value)

    def test_encoded_doi_urls_share_reference_identity_without_changing_other_urls(self):
        """
        Decode DOI resolver paths once while retaining non DOI references exactly
        """
        self.record({"relation": ["10.1000/a/b", "https://doi.org/10.1000/a%2Fb"]})
        self.record({"relation": "doi:10.1000/A/B"})
        groups = self.context()["group_options"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)

    def test_relation_objects_and_nested_metadata_do_not_create_links(self):
        """
        Use only supplied text from the recognized top level relation field
        """
        self.record({"relation": [{"@id": "https://example.org/hidden"}, 123],
                     "custom": {"relation": "10.1234/hidden"}, "software": "10.1234/not-a-reference"})
        context = self.context("links=relations")
        self.assertEqual([(group["key"], group["count"]) for group in context["group_options"]], [("missing", 1)])
        self.assertNotIn("https://example.org/hidden", str(context["relationship_graph"]))
        self.assertNotIn("10.1234/hidden", str(context["relationship_graph"]))

    def test_same_names_are_discovery_groups_without_merging_records(self):
        """
        Count repeated phase names once per object and retain independent member nodes
        """
        first = self.record({"title": "Same title", "software": ["Abaqus", " abaqus "],
                             "software_version": "2024", "phase": [{"phase_name": "Copper", "phase_id": 1}, {"phase_name": "copper", "phase_id": 2}]})
        second = self.record({"title": "Same title", "software": "ABAQUS",
                              "software_version": "2025", "phase": [{"phase_name": "COPPER", "phase_id": 1}]})
        context = self.context("links=phase")
        self.assertEqual(len(context["group_options"]), 1)
        self.assertEqual(context["group_options"][0]["count"], 2)
        selected = self.context("links=phase&group=" + context["group_options"][0]["key"])
        members = [node for node in selected["relationship_graph"]["nodes"] if node["kind"] == "record"]
        self.assertEqual({node["id"] for node in members}, {f"collection-object-{first.pk}", f"collection-object-{second.pk}"})
        self.assertIn("do not establish the same material", selected["links_description"])
        software = self.context("links=software")
        self.assertEqual(software["group_options"][0]["count"], 2)
        self.assertIn("same version", software["links_description"])
        self.assertEqual({row["software_version"] for row in software["object_rows"]}, {"2024", "2025"})

    def test_missing_metadata_remains_visible_without_numeric_names(self):
        """
        Keep records without labels available without treating phase IDs as names
        """
        obj = self.record({"title": "No labels", "software": 42, "phase": [{"phase_id": 7}, {"phase_name": False}]})
        for mode in ("relations", "software", "phase"):
            with self.subTest(mode=mode):
                context = self.context("links=" + mode)
                self.assertEqual(context["group_options"][0]["key"], "missing")
                self.assertEqual(context["object_rows"][0]["pk"], obj.pk)
                selected = self.context("links=" + mode + "&group=missing")
                self.assertEqual(selected["matching_object_count"], 1)
        members = self.context("links=members")
        self.assertEqual(len(members["relationship_graph"]["nodes"]), 2)
        self.assertEqual(members["group_options"], [])

    def test_recognized_descriptions_and_wrappers_match_without_changing_json(self):
        """
        Reuse metadata compatibility while leaving raw uploaded values untouched
        """
        data = {
            "Identifier": ["wrapped-id"], "Title": ["Wrapped example"],
            "Software Name": [["DAMASK"]], "Other Software Name": "Abaqus",
            "Software Version": ["3.0"], "Creator Name": "Alice", "Other Creator Name": "Bob",
            "Phase": [[{"Phase Name": ["Ferrite"]}], {"Name": "Legacy copper"}],
            "Relation": [["10.1234/EXAMPLE"]],
            "Mechanical BC": [{"Loading Type": ["cyclic"], "Loading Mode": ["strain"]}],
            "stress": {"stress_11": list(range(1000))},
        }
        original = deepcopy(data)
        obj = self.record(data)
        context = self.context()
        row = context["object_rows"][0]
        self.assertEqual(row["identifier"], "wrapped-id")
        self.assertEqual(row["software"], "DAMASK; Abaqus")
        self.assertEqual(row["phase"], "Ferrite; Legacy copper")
        self.assertEqual(row["loading"], "cyclic · strain")
        self.assertEqual(row["creator"], "Alice; Bob")
        self.assertNotIn("stress_11", str(context))
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)

    def test_conflicting_functional_aliases_do_not_select_a_reference_or_phase(self):
        """
        Exclude conflicting functional fields instead of choosing the first alias
        """
        self.record({"relation": ["10.1234/one"], "Relation": ["10.1234/two"],
                     "phase": [{"phase_name": "Copper"}], "Phase": [{"phase_name": "Steel"}]})
        for mode in ("relations", "phase"):
            with self.subTest(mode=mode):
                self.assertEqual(self.context("links=" + mode)["group_options"][0]["key"], "missing")

    def test_identical_functional_aliases_still_supply_the_same_reference(self):
        """
        Accept harmless repeated aliases without counting the same record twice
        """
        self.record({"relation": ["10.1234/one"], "Relation": ["10.1234/one"]})
        group = self.context()["group_options"][0]
        self.assertNotEqual(group["key"], "missing")
        self.assertEqual(group["count"], 1)

    def test_nested_functional_conflicts_do_not_choose_loading_or_hide_phase_names(self):
        """
        Keep unaffected phase labels while omitting ambiguous loading descriptions
        """
        self.record({
            "phase": [{"phase_name": "Copper", "constitutive_model": {
                "elastic_parameters": {"C11": 10}, "Elastic Parameters": {"C11": 20},
            }}],
            "mechanical_BC": [{"loading_type": "cyclic", "Loading Type": "monotonic", "loading_mode": "strain"}],
        })
        context = self.context("links=phase")
        self.assertEqual(context["group_options"][0]["label"], "Copper")
        self.assertEqual(context["object_rows"][0]["loading"], "")

    def test_only_caller_accessible_records_contribute_counts_or_labels(self):
        """
        Build every graph summary from the provided access restriction
        """
        visible = self.record({"title": "Visible", "relation": ["10.1234/common"]})
        self.record({"title": "Hidden title", "relation": ["10.1234/common", "Secret reference"]})
        context = self.context(objects=JSONData.objects.filter(pk=visible.pk))
        self.assertEqual(context["object_total"], 1)
        self.assertEqual(context["group_options"][0]["count"], 1)
        self.assertNotIn("Hidden title", str(context))
        self.assertNotIn("Secret reference", str(context))

    def test_hundred_record_study_has_bounded_graph_and_complete_pages(self):
        """
        Show a readable page without silently discarding remaining members
        """
        records = []
        for index in range(101):
            records.append(JSONData(owner=self.owner, data={"title": f"Run {index}", "relation": "10.1234/common"}))
        JSONData.objects.bulk_create(records)
        overview = self.context()
        self.assertEqual(overview["object_total"], 101)
        self.assertEqual(len(overview["relationship_graph"]["nodes"]), 2)
        self.assertFalse(overview["auto_expanded"])
        self.assertEqual(len(overview["object_rows"]), 25)
        key = overview["group_options"][0]["key"]
        selected = self.context("group=" + key + "&page=5&view=detailed")
        self.assertEqual(selected["matching_object_count"], 101)
        self.assertEqual(len(selected["object_rows"]), 1)
        self.assertEqual(len(selected["relationship_graph"]["nodes"]), 3)
        previous = parse_qs(urlsplit(selected["previous_objects_url"]).query)
        self.assertEqual(previous["group"], [key])
        self.assertEqual(previous["view"], ["detailed"])
        self.assertEqual(previous["page"], ["4"])

    def test_many_reference_groups_are_paged_with_stable_identifiers(self):
        """
        Bound overview nodes and preserve group identity across record ordering
        """
        self.record({"relation": [f"10.1234/reference-{index}" for index in range(61)]})
        default = self.context()
        self.assertEqual(default["links_mode"], "members")
        self.assertEqual(len(default["relationship_graph"]["nodes"]), 2)
        first = self.context("links=relations")
        second = self.context("links=relations&groups_page=2&view=detailed")
        self.assertFalse(first["auto_expanded"])
        self.assertEqual(len(first["relationship_graph"]["nodes"]), 26)
        self.assertEqual(len(second["relationship_graph"]["nodes"]), 26)
        self.assertEqual(second["group_page"].paginator.count, 61)
        self.assertTrue(second["next_groups_url"])
        before = {group["label"]: group["key"] for group in first["group_options"]}
        self.record({"relation": "10.1234/reference-0"})
        after = {group["label"]: group["key"] for group in self.context("links=relations")["group_options"]}
        self.assertEqual(before["10.1234/reference-0"], after["10.1234/reference-0"])

    def test_overview_expansion_obeys_object_and_node_limits(self):
        """
        Expand at both limits and keep larger explicit overviews bounded
        """
        records = [
            self.record({"relation": [f"10.1234/reference-{index}", f"10.1234/reference-{index + 8}"]})
            for index in range(8)
        ]
        context = self.context()
        self.assertTrue(context["auto_expanded"])
        self.assertEqual(len(context["relationship_graph"]["nodes"]), 25)
        records[0].data["relation"].append("10.1234/extra")
        records[0].save(update_fields=["data"])
        context = self.context()
        self.assertEqual(context["links_mode"], "members")
        explicit = self.context("links=relations")
        self.assertFalse(explicit["auto_expanded"])
        self.assertEqual(len(explicit["relationship_graph"]["nodes"]), 18)
        self.record({"relation": "10.1234/reference-0"})
        larger = self.context()
        self.assertEqual(larger["links_mode"], "relations")
        self.assertFalse(larger["auto_expanded"])
        self.assertEqual(larger["object_total"], 9)

    def test_paging_one_list_preserves_the_other_list_and_resets_on_group_change(self):
        """
        Retain independent overview pagination without carrying it into a new group
        """
        records = []
        for index in range(76):
            records.append(JSONData(owner=self.owner, data={"title": f"Run {index}", "relation": f"10.1234/reference-{index}"}))
        JSONData.objects.bulk_create(records)
        context = self.context("page=2&groups_page=3&view=detailed")
        objects = parse_qs(urlsplit(context["next_objects_url"]).query)
        groups = parse_qs(urlsplit(context["next_groups_url"]).query)
        self.assertEqual(objects["page"], ["3"])
        self.assertEqual(objects["groups_page"], ["3"])
        self.assertEqual(groups["page"], ["2"])
        self.assertEqual(groups["groups_page"], ["4"])
        self.assertEqual(groups["view"], ["detailed"])
        selected = parse_qs(urlsplit(context["group_options"][0]["url"]).query)
        self.assertNotIn("page", selected)
        self.assertNotIn("groups_page", selected)

    def test_invalid_or_repeated_scope_does_not_fall_back_to_all_objects(self):
        """
        Reject ambiguous modes and missing groups before rendering broader results
        """
        self.record({"relation": "10.1234/example"})
        for query in ("links=unknown", "links=", "links=phase&links=software",
                      "group=missing&group=missing", "group=unknown", "links=members&group=missing"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.context(query)

    def test_empty_collection_retains_controls_without_a_fake_graph(self):
        """
        Return a usable empty list and exact zero counts
        """
        context = self.context()
        self.assertEqual(context["object_total"], 0)
        self.assertEqual(context["object_rows"], [])
        self.assertIsNone(context["relationship_graph"])
        self.assertEqual(len(context["links_options"]), 4)

    def test_renderer_escapes_labels_and_offers_native_drillthrough_links(self):
        """
        Keep supplied markup inert in SVG, inspector text and layout JSON
        """
        obj = self.record({"title": '<img src=x onerror="alert(1)">', "relation": "</script><script>alert(2)</script>"})
        context = self.context("links=members")
        rendered = render_to_string("pages/detail_relationships.html", context)
        self.assertNotIn('<img src=x onerror="alert(1)">', rendered)
        self.assertNotIn("<script>alert(2)</script>", rendered)
        self.assertIn("&lt;img", rendered)
        self.assertIn(f'href="/data-list/{obj.pk}/"', rendered)
        self.assertIn(f'href="/data-list/{obj.pk}/?tab=graph"', rendered)
        self.assertIn("View object graph", rendered)
        self.assertIn("Current graph page (SVG)", rendered)
        self.assertNotIn("Original JSON", rendered)

    def test_compact_and_detailed_geometry_keeps_cards_separate(self):
        """
        Preserve one node set and nonoverlapping cards at both presentation sizes
        """
        for index in range(8):
            self.record({"title": f"Run {index}", "identifier": f"run-{index}", "software": "DAMASK", "phase": [{"phase_name": "Copper"}]})
        graph = self.context("links=members")["relationship_graph"]
        self.assertEqual(set(graph["layouts"]["compact"]["positions"]), set(graph["layouts"]["detailed"]["positions"]))
        for mode, layout in graph["layouts"].items():
            with self.subTest(mode=mode):
                columns = {}
                for position in layout["positions"].values():
                    columns.setdefault(position["x"], []).append(position)
                for column in columns.values():
                    rows = sorted(column, key=lambda position: position["y"])
                    for first, second in zip(rows, rows[1:]):
                        self.assertGreaterEqual(second["y"], first["y"] + first["height"] + 24)
                self.assertEqual(len(layout["paths"]), len(graph["edges"]))
