"""
Verify field filtering and stable focus within bounded parameter inspection.
"""

from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from . import study_details


class DetailNavigationTests(SimpleTestCase):
    """
Keep native field controls precise, bounded and independent of record values.
    """

    def context(self):
        """
        Build a small inspected table with all three field states.

        Returns
        -------
        dict
            Independent table fixture with source paths and preview values.
        """
        rows = []
        for path, label, group, status in (
            ("phase[0].constitutive_model.elastic_parameters.C11", "C11", "Phase 1", "different"),
            ("phase[0].constitutive_model.elastic_parameters.C12", "C12", "Phase 1", "same"),
            ("mechanical_BC[0].magnitude", "magnitude", "Loading condition 1", "incomplete"),
        ):
            key = sha256(path.encode()).hexdigest()[:24]
            rows.append({"path": path, "label": label, "group": group, "status": status,
                         "key": key, "id": "study-parameter-" + key, "cells": [{"value": "secretvalue"}]})
        return {"ready": True, "open": True, "error": "", "rows": rows,
                "objects": [{"pk": 1, "title": "Reference", "identifier": "reference"},
                            {"pk": 2, "title": "Other", "identifier": "other"}],
                "counts": {"total": 3, "same": 1, "different": 1, "incomplete": 1},
                "differences": [deepcopy(rows[0]), deepcopy(rows[2])], "limited": True,
                "limit_reasons": ["Some values shortened."], "scope_note": "Recorded values only."}

    def apply(self, params):
        """
        Apply real navigation to the synthetic table.

        Parameters
        ----------
        params : dict or QueryDict
            Native field controls.

        Returns
        -------
        dict
            Mutated table including all retained rows and visible state.
        """
        from .study_detail_navigation import apply_detail_navigation

        context = self.context()
        result = apply_detail_navigation(context, params, base_url="/graph/collections/1/",
                                         navigation_params={"compare": "1,2", "panel": "compare",
                                                            "inspect": "1", "map_unit": "a" * 64})
        self.assertIs(result, context)
        return result

    def test_scalar_controls_are_bounded_and_canonical(self):
        """
        Reject malformed controls while omitting defaults from native state.
        """
        from .study_detail_navigation import detail_parameters

        self.assertEqual(detail_parameters({"detail_status": "all", "detail_q": "  "}), {})
        self.assertEqual(detail_parameters({"detail_status": "different", "detail_q": "  C11  "}),
                         {"detail_status": "different", "detail_q": "C11"})
        for values in (QueryDict("detail_q=x&detail_q=y"), {"detail_status": "missing"},
                       {"detail_q": "a" * 201}, {"detail_q": ["C11"]},
                       {"detail_focus": "<script>"}, {"detail_focus": "A" * 24}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                detail_parameters(values)

    def test_filter_keeps_all_rows_but_shows_exact_states_and_groups(self):
        """
        Keep incomplete information separate from known differences.
        """
        different = self.apply({"detail_status": "different"})
        self.assertEqual(len(different["rows"]), 3)
        self.assertEqual([row["label"] for row in different["rows"] if row["visible"]], ["C11"])
        self.assertEqual(different["navigation"]["visible_count"], 1)
        self.assertEqual([group["visible"] for group in different["navigation"]["groups"]], [True, False])
        incomplete = self.apply({"detail_status": "incomplete"})
        self.assertEqual([row["label"] for row in incomplete["rows"] if row["visible"]], ["magnitude"])
        self.assertEqual(incomplete["counts"], {"total": 3, "same": 1, "different": 1, "incomplete": 1})
        self.assertTrue(incomplete["limited"])

    def test_search_uses_all_case_insensitive_field_terms_not_cell_values(self):
        """
        Find fields by label and canonical location without matching source values.
        """
        matched = self.apply({"detail_q": "ELASTIC C11"})
        self.assertEqual([row["label"] for row in matched["rows"] if row["visible"]], ["C11"])
        self.assertEqual(self.apply({"detail_q": "secretvalue"})["navigation"]["visible_count"], 0)

    def test_summary_focus_clears_filters_and_preserves_workspace(self):
        """
        Jump to a real field with a native URL and open table.
        """
        key = self.context()["rows"][0]["key"]
        context = self.apply({"detail_status": "incomplete", "detail_q": "unmatched", "detail_focus": key})
        navigation = context["navigation"]
        self.assertEqual(navigation["state"], {"detail_focus": key})
        self.assertTrue(navigation["table_open"])
        self.assertEqual(navigation["focus_id"], "study-parameter-" + key)
        self.assertEqual(navigation["visible_count"], 3)
        link = urlsplit(context["differences"][0]["focus_url"])
        values = parse_qs(link.query)
        self.assertEqual(values["compare"], ["1,2"])
        self.assertEqual(values["map_unit"], ["a" * 64])
        self.assertEqual(values["detail_focus"], [key])
        self.assertNotIn("detail_q", values)
        self.assertNotIn("detail_status", values)
        self.assertEqual(link.fragment, "study-parameter-" + key)

    def test_missing_focus_has_explicit_message_without_faking_a_row(self):
        """
        Keep stale source-field links understandable after data changes.
        """
        context = self.apply({"detail_focus": "f" * 24})
        self.assertTrue(context["navigation"]["focus_missing"])
        self.assertEqual(context["navigation"]["focus_id"], "")
        self.assertEqual(context["navigation"]["visible_count"], 3)

    def test_template_keeps_native_controls_and_escapes_field_text(self):
        """
        Render safe native filters, hidden unmatched rows and an empty result.
        """
        context = self.apply({"detail_q": '<script>alert(1)</script>'})
        html = render_to_string("pages/study_details.html", {
            "study_details": context, "study_comparison": {"close_inspect_url": "/graph/collections/1/"},
        })
        self.assertIn('id="study-detail-search"', html)
        self.assertIn('name="detail_q"', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('id="study-detail-empty"', html)
        self.assertIn('data-parameter-row', html)

    def test_stable_ids_use_complete_paths_even_when_labels_are_shortened(self):
        """
        Distinguish long fields whose displayed source paths share a prefix.
        """
        record = {"pk": 1, "title": "Reference"}
        paths = ["a" * 600 + "x", "a" * 600 + "y"]
        fields = {}
        for path in paths:
            fields[path] = ("Phase 1", {"state": "recorded", "token": "1", "value": "1"}, "long field")
        context = study_details._finish_context(study_details._empty_context(), [(record, fields)],
                                                study_details.InspectionBudget())
        self.assertEqual(context["rows"][0]["path"], context["rows"][1]["path"])
        self.assertNotEqual(context["rows"][0]["key"], context["rows"][1]["key"])
        self.assertEqual(context["rows"][0]["key"], sha256(paths[0].encode()).hexdigest()[:24])
