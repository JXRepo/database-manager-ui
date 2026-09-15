from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
from django.urls import Resolver404, resolve, reverse


class PublicSurfaceTests(TestCase):
    """
    Test the public deployment URL surface and readiness endpoint
    """

    def test_legacy_public_mutation_routes_are_closed(self):
        """
        Legacy public mutation and generated API routes are not exposed
        """
        legacy_routes = (
            "/api/",
            "/api/product/",
            "/dynamic-dt/",
            "/create/product/",
            "/update/product/1/",
            "/delete/product/1/",
            "/export-csv/product/",
            "/login/jwt/",
        )

        for route in legacy_routes:
            with self.subTest(route=route):
                with self.assertRaises(Resolver404):
                    resolve(route)

                response = self.client.get(route)

                self.assertEqual(response.status_code, 404)

    def test_password_reset_route_family_is_closed_for_the_pilot(self):
        """
        Every installed password reset route returns not found
        """
        reset_routes = (
            "/accounts/password-reset/",
            "/accounts/password-reset-done/",
            "/accounts/password-reset-confirm/NA/token-value/",
            "/accounts/password-reset-complete/",
        )

        for route in reset_routes:
            with self.subTest(route=route):
                response = self.client.get(route)

                self.assertEqual(response.status_code, 404)

    def test_login_and_registration_routes_remain_reachable(self):
        """
        Closing reset routes leaves ordinary account entry points available
        """
        account_routes = (
            "/login/",
            "/register/",
            "/accounts/login/",
            "/accounts/register/",
        )

        for route in account_routes:
            with self.subTest(route=route):
                response = self.client.get(route)

                self.assertEqual(response.status_code, 200)

    def test_registration_help_is_rendered_and_linked_to_inputs(self):
        """
        Show registration guidance and associate it with its input

        Username and password guidance must be visible and available to
        assistive technology when the registration page is rendered.
        """
        response = self.client.get(reverse("register"))
        form = response.context["form"]

        for field_name in ("username", "password1"):
            with self.subTest(field=field_name):
                field = form[field_name]
                help_id = f"{field.auto_id}_helptext"

                self.assertTrue(field.help_text)
                self.assertContains(response, f'id="{help_id}"')
                self.assertContains(response, f'aria-describedby="{help_id}"')
                self.assertContains(response, field.help_text)

    def test_healthz_returns_ok_when_database_is_ready(self):
        """
        Health endpoint returns ok after a live database query succeeds
        """
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})

    def test_healthz_returns_unavailable_when_database_query_fails(self):
        """
        Health endpoint returns unavailable when the database query fails
        """
        with patch(
            "apps.pages.views.connection.cursor",
            side_effect=DatabaseError("database unavailable"),
        ):
            response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(response.content, {"status": "unavailable"})
