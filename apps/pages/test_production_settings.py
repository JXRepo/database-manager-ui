import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class ProductionSettingsImportTests(SimpleTestCase):
    """
    Test production settings import behavior
    """

    @classmethod
    def setUpClass(cls):
        """
        Set shared paths for subprocess imports
        """
        super().setUpClass()
        cls.project_root = Path(__file__).resolve().parents[2]
        cls.import_script = textwrap.dedent(
            """
            import importlib
            import json

            import dotenv

            dotenv.load_dotenv = lambda *args, **kwargs: False
            settings = importlib.import_module("config.settings")
            print(
                json.dumps(
                    {
                        "allowed_hosts": settings.ALLOWED_HOSTS,
                        "csrf_trusted_origins": settings.CSRF_TRUSTED_ORIGINS,
                        "database": settings.DATABASES["default"],
                        "debug": settings.DEBUG,
                        "orcid_base_url": settings.ORCID_BASE_URL,
                        "secret_key": settings.SECRET_KEY,
                        "trusted_proxy_hops": settings.TRUSTED_PROXY_HOPS,
                    },
                    default=str,
                    sort_keys=True,
                )
            )
            """
        )

    def _import_settings(self, **overrides):
        """
        Import config.settings in a controlled subprocess
        """
        env = {}
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT"):
            value = os.environ.get(key)
            if value is not None:
                env[key] = value

        env["PYTHONPATH"] = str(self.project_root)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            [sys.executable, "-c", self.import_script],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_production_database_uses_postgres_ssl_settings(self):
        """
        Production imports configure PostgreSQL with secure defaults
        """
        result = self._import_settings(
            DEBUG="False",
            SECRET_KEY="test-secret",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["database"],
            {
                "ENGINE": "django.db.backends.postgresql",
                "HOST": "db.example.com",
                "NAME": "pilot-db",
                "OPTIONS": {"sslmode": "require"},
                "PASSWORD": "pilot-pass",
                "PORT": "5432",
                "USER": "pilot-user",
                "CONN_HEALTH_CHECKS": True,
                "CONN_MAX_AGE": 60,
            },
        )
        self.assertFalse(payload["debug"])

    def test_production_database_ignores_weaker_sslmode_values(self):
        """
        Production imports always enforce sslmode=require
        """
        result = self._import_settings(
            DEBUG="False",
            SECRET_KEY="test-secret",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
            DB_SSLMODE="disable",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["database"]["OPTIONS"],
            {"sslmode": "require"},
        )

    def test_production_requires_secret_key(self):
        """
        Production imports fail when SECRET_KEY is missing
        """
        result = self._import_settings(
            DEBUG="False",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_rejects_default_secret_key_value(self):
        """
        Production imports fail when SECRET_KEY uses the default value
        """
        result = self._import_settings(
            DEBUG="False",
            SECRET_KEY="Super_Secr3t_9999",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_database_requires_all_connection_values(self):
        """
        Production imports fail when any database setting is missing
        """
        required_values = {
            "DB_ENGINE": "postgresql",
            "DB_NAME": "pilot-db",
            "DB_USERNAME": "pilot-user",
            "DB_PASS": "pilot-pass",
            "DB_HOST": "db.example.com",
            "DB_PORT": "5432",
        }

        for missing_key in required_values:
            with self.subTest(missing_key=missing_key):
                env = dict(required_values)
                env.pop(missing_key)
                result = self._import_settings(
                    DEBUG="False",
                    SECRET_KEY="test-secret",
                    **env,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn("production database", result.stderr)
                self.assertIn(missing_key, result.stderr)

    def test_production_uses_only_configured_allowed_hosts(self):
        """
        Production imports keep only configured hosts and Render hostname
        """
        result = self._import_settings(
            DEBUG="False",
            SECRET_KEY="test-secret",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
            ALLOWED_HOSTS="pilot.example.com,api.example.com",
            RENDER_EXTERNAL_HOSTNAME="pilot-app.onrender.com",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["allowed_hosts"],
            [
                "pilot.example.com",
                "api.example.com",
                "pilot-app.onrender.com",
            ],
        )

    def test_production_uses_only_configured_https_csrf_origins(self):
        """
        Production imports keep only configured HTTPS origins and Render origin
        """
        result = self._import_settings(
            DEBUG="False",
            SECRET_KEY="test-secret",
            DB_ENGINE="postgresql",
            DB_NAME="pilot-db",
            DB_USERNAME="pilot-user",
            DB_PASS="pilot-pass",
            DB_HOST="db.example.com",
            DB_PORT="5432",
            CSRF_TRUSTED_ORIGINS="https://pilot.example.com,https://api.example.com",
            RENDER_EXTERNAL_HOSTNAME="pilot-app.onrender.com",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["csrf_trusted_origins"],
            [
                "https://pilot.example.com",
                "https://api.example.com",
                "https://pilot-app.onrender.com",
            ],
        )

    def test_local_debug_can_use_sqlite(self):
        """
        Local debug imports can use SQLite without database settings
        """
        result = self._import_settings(DEBUG="True", SECRET_KEY="local-only")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("django.db.backends.sqlite3", result.stdout)

    def test_parent_application_settings_cannot_poison_subprocess_import(self):
        """
        The subprocess receives defaults instead of parent application values
        """
        poisoned_parent = {
            "TRUSTED_PROXY_HOPS": "not-an-integer",
            "ORCID_BASE_URL": "https://parent.example.invalid",
        }

        with patch.dict(os.environ, poisoned_parent):
            result = self._import_settings(
                DEBUG="True",
                SECRET_KEY="local-only",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["trusted_proxy_hops"], 0)
        self.assertEqual(
            payload["orcid_base_url"],
            "https://sandbox.orcid.org",
        )
