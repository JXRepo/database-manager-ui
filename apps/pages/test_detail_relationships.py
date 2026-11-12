from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class DetailRelationshipTests(TestCase):
    """
    Keep the relationship view grounded in one accessible object's metadata
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create separate owners and readers for permission checks
        """
        cls.owner = User.objects.create_user(username="graph-owner")
        cls.reader = User.objects.create_user(username="graph-reader")

    def setUp(self):
        """
        Open detail pages as their owner by default
        """
        self.client.force_login(self.owner)

    def detail(self, data):
        """
        Read a stored record through the independent graph workspace

        Parameters
        ----------
        data : dict
            Uploaded metadata to retain unchanged.

        Returns
        -------
        tuple
            Record, rendered response and relationship graph.
        """
        obj = JSONData.objects.create(owner=self.owner, data=data)
        response = self.client.get("/graph/", {"object": obj.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue("relationship_graph" in response.context, "Graph workspace must include the selected record")
        return obj, response, response.context["relationship_graph"]

    def test_models_stay_attached_to_their_own_phase(self):
        """
        Keep equal phase names distinct and retain each model's actual parent
        """
        _, _, graph = self.detail({
            "title": "Two phases", "creator": ["Alice", "Bob"], "software": "Abaqus",
            "phase": [
                {"phase_name": "Steel", "phase_id": 0, "constitutive_model": {
                    "elastic_model_name": "Isotropic elasticity",
                    "plastic_model_name": "Crystal plasticity",
                }},
                {"phase_name": "Steel", "phase_id": 2, "constitutive_model": {
                    "elastic_model_name": "Cubic elasticity",
                }},
            ],
        })
        phases = [node for node in graph["nodes"] if node["kind"] == "phase"]
        self.assertEqual([node["label"] for node in phases], ["Steel", "Steel"])
        self.assertNotEqual(phases[0]["id"], phases[1]["id"])
        models = [node for node in graph["nodes"] if node["kind"] == "model"]
        self.assertEqual([(node["label"], node["parent"]) for node in models], [
            ("Isotropic elasticity", phases[0]["id"]),
            ("Crystal plasticity", phases[0]["id"]),
            ("Cubic elasticity", phases[1]["id"]),
        ])
        self.assertIn({"label": "Phase ID", "value": "0"}, phases[0]["details"])

    def test_compatible_names_wrappers_and_descriptions_preserve_exports(self):
        """
        Recognize accepted field variants without changing original JSON
        """
        data = {
            "Identifier": ["graph-aliases"], "Title": "Aliased fields",
            "Creator Name": "Alice", "Other Creator Name": "Bob",
            "Software": [["DAMASK"]],
            "Phase": [{"Phase Name": ["Ferrite"], "Constitutive Model": [{
                "Elastic Model Name": ["Cubic elasticity"],
            }]}],
        }
        original = deepcopy(data)
        obj, response, graph = self.detail(data)
        labels = " | ".join(node["label"] for node in graph["nodes"])
        for value in ("Alice", "Bob", "DAMASK", "Ferrite", "Cubic elasticity"):
            self.assertIn(value, labels)
            self.assertContains(response, value)
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), original)

    def test_empty_or_unknown_metadata_does_not_invent_entities(self):
        """
        Ignore unrelated names and keep numeric IDs separate from phase names
        """
        _, response, graph = self.detail({
            "creator": [], "software": None,
            "custom": {"creator": "Hidden author", "phase_name": "Hidden phase"},
            "phase": [{"phase_id": 24}], "stress": {"stress_11": []},
        })
        self.assertEqual([node["kind"] for node in graph["nodes"]], ["record", "phase"])
        self.assertEqual(graph["nodes"][1]["label"], "Phase 1")
        self.assertNotIn("Hidden author", str(graph))
        self.assertNotIn("Hidden phase", str(graph))
        _, empty_response, empty = self.detail({"title": "No relationships"})
        self.assertEqual(len(empty["nodes"]), 1)
        self.assertContains(empty_response, "No related metadata is available")

    def test_results_reuse_curve_availability_without_copying_samples(self):
        """
        Show exact series lengths and distinguish supplied and calculated output
        """
        stress = {}
        for component in ("11", "22", "33", "12", "13", "23"):
            stress[f"stress_{component}"] = [0, 1, 2]
        stress["stress_11"] = [0, 1, 2, 3, 4]
        _, response, graph = self.detail({
            "title": "Output coverage", "stress": stress,
            "total_strain": {"equivalent_strain": [0, .1, .2, .3]},
            "plastic_strain": {"plastic_strain_11": []},
            "units": {"Stress": "MPa", "Strain": "1"},
        })
        outputs = [node for node in graph["nodes"] if node["kind"] == "output"]
        self.assertEqual([node["label"] for node in outputs], ["Stress", "Total strain"])
        text = str(outputs)
        self.assertIn("5 samples", text)
        self.assertIn("4 samples", text)
        self.assertIn("Calculated", text)
        self.assertIn("MPa", text)
        self.assertNotIn("'values':", text)
        self.assertContains(response, "Relationship details")

    def test_legacy_names_and_explicit_absence_do_not_become_false_models(self):
        """
        Retain legacy phase names while treating an explicit absence as a note
        """
        _, _, graph = self.detail({
            "phase": [None, {}, {"Name": "Legacy ferrite", "phase_id": 7,
                "constitutive_model": {"elastic_model_name": "Cubic elasticity",
                    "plastic_model_name": "  No plasticity in this elastic reference  ",
                    "damage_model_name": "Ductile damage"}}],
        })
        phases = [node for node in graph["nodes"] if node["kind"] == "phase"]
        self.assertEqual([node["label"] for node in phases], ["Legacy ferrite"])
        models = [node for node in graph["nodes"] if node["kind"] == "model"]
        self.assertEqual([node["label"] for node in models], ["Cubic elasticity", "Ductile damage"])
        self.assertIn({"label": "Plasticity", "value": "No plasticity in this elastic reference"},
                      phases[0]["details"])

    def test_graph_content_is_escaped_and_unrelated_records_are_excluded(self):
        """
        Keep uploaded HTML inert in SVG labels, titles and detail panels
        """
        attack = '<script>window.graphInjection = true</script>'
        JSONData.objects.create(owner=self.reader, data={"creator": "Other private creator"})
        _, response, graph = self.detail({"title": attack, "creator": attack})
        self.assertContains(response, "&lt;script&gt;window.graphInjection = true&lt;/script&gt;")
        self.assertNotContains(response, attack)
        self.assertNotIn("Other private creator", str(graph))
        self.assertNotContains(response, "Other private creator")

    def test_inspector_keeps_model_parameters_orientation_and_loading_context(self):
        """
        Expose supplied context without inventing pairings or copying large arrays
        """
        data = {
            "title": "Inspection", "creator": ["Alice", "Bob"],
            "creator_affiliation": ["Institute A", "Institute B"],
            "phase": [{"phase_name": "Ferrite", "orientation": {
                "grain_number": [0], "texture_type": "Random",
                "euler_angles": {"Phi1": list(range(5000))},
            }, "constitutive_model": {
                "units": {"Stiffness": "MPa"},
                "elastic_model_name": "Cubic", "elastic_parameters": {
                    "C11": 233000, "units": "MPa", "extra": list(range(5000)),
                },
            }}],
            "mechanical_BC": [
                {"loading_type": "stress", "loading_mode": "tensor",
                 "vertex_list": ["V000", "V100", "V010", "V110", "V001", "V101", "V011", "V111"],
                 "constraints": ["loaded"], "applied_load": [
                    {"step": 0, "magnitude": {"xy": -5, "yx": 7}},
                    {"step": 0.5, "magnitude": {"xy": 4}},
                ]},
                {"loading_type": "displacement", "loading_mode": "X"},
            ],
        }
        original = deepcopy(data)
        obj, response, graph = self.detail(data)
        phase = next(node for node in graph["nodes"] if node["kind"] == "phase")
        self.assertIn({"label": "Grain number", "value": "0"}, phase["details"])
        self.assertIn({"label": "Texture", "value": "Random"}, phase["details"])
        model = next(node for node in graph["nodes"] if node["kind"] == "model")
        self.assertIn({"label": "C11", "value": "233000"}, model["details"])
        self.assertIn({"label": "Recorded model units", "value": '{"Stiffness": "MPa"}'}, model["details"])
        self.assertIn({"label": "units", "value": "MPa"}, model["details"])
        self.assertIn({"label": "extra", "value": "5000 items · View data details for all values"}, model["details"])
        loading = [node for node in graph["nodes"] if node["kind"] == "loading"]
        self.assertEqual([node["label"] for node in loading], ["stress · tensor", "displacement · X"])
        self.assertIn({"label": "Load records", "value": "2"}, loading[0]["details"])
        self.assertTrue(all(node["parent"] == graph["nodes"][0]["id"] for node in loading))
        self.assertNotIn("4999", str(graph))
        self.assertNotIn("compression", str(graph))
        self.assertContains(response, f'{reverse("json_data_detail", args=[obj.pk])}#data-loading')
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)

    def test_loading_without_a_cube_target_links_to_existing_details(self):
        """
        Return incomplete boundary metadata to details instead of an empty cube
        """
        obj, response, graph = self.detail({"mechanical_BC": [
            {"loading_type": "force", "loading_mode": "static"},
        ]})
        self.assertFalse(graph["has_loading_details"])
        self.assertNotContains(response, '#data-loading')
        self.assertContains(response, f'{reverse("json_data_detail", args=[obj.pk])}#data-metadata')

    def test_node_links_survive_unrelated_optional_metadata_and_list_all_connections(self):
        """
        Keep shared node links stable when other metadata categories are added
        """
        data = {"phase": [{"phase_name": "Steel", "constitutive_model": {
            "elastic_model_name": "Cubic",
        }}]}
        _, _, first = self.detail(data)
        _, response, expanded = self.detail({**data, "creator": "Alice", "software": "DAMASK"})
        for kind in ("record", "phase", "model"):
            before = next(node for node in first["nodes"] if node["kind"] == kind)
            after = next(node for node in expanded["nodes"] if node["kind"] == kind)
            self.assertEqual(before["id"], after["id"])
            self.assertContains(response, f'href="#{after["id"]}-info"')
        nodes = {node["id"]: node for node in expanded["nodes"]}
        for edge in expanded["edges"]:
            self.assertTrue(any(link["id"] == edge["target"] for link in nodes[edge["source"]]["connections"]))
            self.assertTrue(any(link["id"] == edge["source"] for link in nodes[edge["target"]]["connections"]))
            self.assertTrue(edge["label"])

    def test_graph_obeys_existing_detail_access(self):
        """
        Require login and explicit access before returning relationship metadata
        """
        obj, _, _ = self.detail({"creator": "Private relationship creator"})
        url = f"/graph/?object={obj.pk}"
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.reader)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 404)
        self.assertNotContains(denied, "Private relationship creator", status_code=404)
        obj.shared_users.add(self.reader)
        self.assertContains(self.client.get(url), "Private relationship creator")
        obj.shared_users.clear()
        obj.access_type = "all"
        obj.save(update_fields=["access_type"])
        self.assertContains(self.client.get(url), "Private relationship creator")

    def test_detail_links_to_graph_without_embedding_the_workspace(self):
        """
        Carry the current object to Graph while keeping the detail page focused
        """
        obj = JSONData.objects.create(owner=self.owner, data={"title": "Graph entry"})
        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        self.assertContains(response, f'href="/graph/?object={obj.pk}"')
        self.assertContains(response, "Open in Graph")
        self.assertNotContains(response, 'id="detail-relationships"')
        self.assertNotContains(response, "detail-relationships.js")
        self.assertFalse("relationship_graph" in response.context)

    def test_picker_lists_only_accessible_objects_once(self):
        """
        Offer owned, public and explicitly shared objects without private leaks
        """
        own = JSONData.objects.create(owner=self.owner, data={"Title": "My record"})
        public = JSONData.objects.create(owner=self.reader, access_type="all", data={"title": "Public record"})
        shared = JSONData.objects.create(owner=self.reader, data={"title": "Received record"})
        hidden = JSONData.objects.create(owner=self.reader, data={"title": "Private hidden title"})
        shared.shared_users.add(self.owner)
        public.shared_users.add(self.owner)
        response = self.client.get("/graph/", {"choose": "1"})
        self.assertEqual(response.status_code, 200)
        options = response.context["object_options"]
        self.assertCountEqual([option["pk"] for option in options], [own.pk, public.pk, shared.pk])
        self.assertNotContains(response, hidden.data["title"])
        self.assertIsNone(response.context["relationship_graph"])
        self.assertContains(response, "Choose a data object")
        self.assertContains(response, 'aria-current="page"')
        self.client.logout()
        self.assertEqual(self.client.get("/graph/").status_code, 302)

    def test_invalid_or_repeated_selection_does_not_open_another_object(self):
        """
        Reject ambiguous object arguments instead of silently choosing a record
        """
        obj = JSONData.objects.create(owner=self.owner, data={"title": "Do not select automatically"})
        for query in ("object=bad", "object=-1", "object=0", "object=99999999999999999999999999",
                      f"object={obj.pk}&object={obj.pk}", f"object=&object={obj.pk}"):
            with self.subTest(query=query):
                response = self.client.get(f"/graph/?{query}")
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, "Do not select automatically", status_code=400)
                self.assertNotContains(response, 'data-node="', status_code=400)
        self.assertEqual(self.client.get("/graph/?object=999999").status_code, 404)

    def test_picker_search_uses_complete_words_and_compatible_descriptions(self):
        """
        Find title or identifier variants without matching substrings or partial queries
        """
        match = JSONData.objects.create(owner=self.owner, data={
            "Display Title": "Steel reference", "Other Title": "Tension", "Identifier": ["run-abc"],
        })
        JSONData.objects.create(owner=self.owner, data={"title": "Steel compression"})
        JSONData.objects.create(owner=self.owner, data={"title": "Steel tensioning"})
        response = self.client.get("/graph/", {"q": "TENSION STEEL"})
        self.assertEqual([option["pk"] for option in response.context["object_options"]], [match.pk])
        response = self.client.get("/graph/", {"q": "run abc"})
        self.assertEqual([option["pk"] for option in response.context["object_options"]], [match.pk])
        response = self.client.get("/graph/", {"q": "unmatched"})
        self.assertContains(response, "No data objects match")
        self.assertContains(response, 'name="q"')
        self.assertIsNone(response.context["relationship_graph"])

    def test_picker_pagination_keeps_the_selected_graph(self):
        """
        Browse a bounded object list without replacing the current graph
        """
        records = []
        for index in range(28):
            records.append(JSONData.objects.create(owner=self.owner, data={"title": f"Record {index}"}))
        selected = records[0]
        first = self.client.get("/graph/", {"object": selected.pk, "choose": "1"})
        self.assertEqual(len(first.context["object_options"]), 25)
        self.assertNotIn(selected.pk, [option["pk"] for option in first.context["object_options"]])
        self.assertEqual(first.context["data_object"].pk, selected.pk)
        self.assertContains(first, 'class="graph-object-option', count=25)
        self.assertNotContains(first, '<select')
        next_url = first.context["next_objects_url"]
        second = self.client.get(next_url)
        self.assertEqual(len(second.context["object_options"]), 3)
        self.assertEqual(second.context["relationship_graph"]["nodes"][0]["label"], "Record 0")
        self.assertEqual(second.context["data_object"].pk, selected.pk)
        self.assertTrue(second.context["previous_objects_url"])

    def test_view_modes_keep_relationships_and_fit_supplied_card_details(self):
        """
        Keep both card layouts readable without changing nodes or their metadata
        """
        obj, compact_response, compact = self.detail({
            "identifier": "view-mode-example", "title": "Mode comparison", "creator": "Alice",
            "software": "DAMASK", "software_version": "3.0",
            "phase": [{"phase_name": "Ferrite", "phase_id": 0, "orientation": {
                "grain_count": 343, "texture_type": "Random",
            }, "constitutive_model": {
                "elastic_model_name": "Cubic", "units": {"Stiffness": "MPa"},
                "elastic_parameters": {"C11": 233000, "C12": 135000},
                "plastic_model_name": "Crystal plasticity",
            }}, {"phase_name": "Martensite"}],
        })
        detailed_response = self.client.get("/graph/", {"object": obj.pk, "view": "detailed"})
        detailed = detailed_response.context["relationship_graph"]
        self.assertContains(compact_response, 'data-view="compact"')
        self.assertContains(detailed_response, 'data-view="detailed"')
        self.assertEqual([node["id"] for node in compact["nodes"]], [node["id"] for node in detailed["nodes"]])
        self.assertEqual(compact["count"], detailed["count"])
        self.assertGreater(detailed["height"], compact["height"])
        for graph in (compact, detailed):
            for node in graph["nodes"]:
                self.assertGreaterEqual(node["x"], 0)
                self.assertGreaterEqual(node["y"], 0)
                self.assertLessEqual(node["x"] + graph["node_width"], graph["width"])
                self.assertLessEqual(node["y"] + node["height"], graph["height"])
                if node["parent"]:
                    self.assertContains(detailed_response, f'>{node["relation"]}</text>')
                for other in graph["nodes"]:
                    if other["id"] == node["id"] or other["x"] != node["x"]:
                        continue
                    self.assertTrue(node["y"] + node["height"] < other["y"] or
                                    other["y"] + other["height"] < node["y"])
        model = next(node for node in detailed["nodes"] if node["kind"] == "model")
        self.assertIn({"label": "C11", "value": "233000"}, model["preview"])
        self.assertIn({"label": "Recorded model units", "value": '{"Stiffness": "MPa"}'}, model["preview"])
        self.assertEqual(set(detailed["layouts"]), {"compact", "detailed"})

    def test_picker_is_one_direct_list_and_preserves_the_view_mode(self):
        """
        Open a result directly and retain the view while searching and paging
        """
        records = []
        for index in range(28):
            records.append(JSONData.objects.create(owner=self.owner, data={"title": f"Reference {index}"}))
        initial = self.client.get("/graph/", {"choose": "1"})
        self.assertContains(initial, 'class="graph-object-option', count=25)
        self.assertNotContains(initial, 'class="graph-object-bar"')
        self.assertNotContains(initial, 'class="graph-welcome"')
        selected = records[0]
        response = self.client.get("/graph/", {"object": selected.pk, "choose": "1", "q": "Reference", "view": "detailed"})
        next_query = parse_qs(urlsplit(response.context["next_objects_url"]).query)
        self.assertEqual(next_query["view"], ["detailed"])
        self.assertEqual(next_query["object"], [str(selected.pk)])
        self.assertEqual(next_query["q"], ["Reference"])
        self.assertContains(response, 'name="view" value="detailed"')
        self.assertContains(response, f'href="/graph/?object={records[-1].pk}&amp;view=detailed"')
        self.assertEqual(self.client.get("/graph/", {"object": selected.pk, "view": "unknown"}).context["graph_view_mode"], "compact")

    def test_graph_works_with_no_accessible_objects(self):
        """
        Keep the standalone entry useful when the viewer has no data to open
        """
        response = self.client.get("/graph/", {"choose": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No accessible data objects")
        self.assertContains(response, reverse("upload_json"))
        self.assertIsNone(response.context["relationship_graph"])
