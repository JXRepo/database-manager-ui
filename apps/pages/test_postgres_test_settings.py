import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from django.test import SimpleTestCase


class LocalPostgresSettingsTests(SimpleTestCase):
    """
    Keep the PostgreSQL verification entry point isolated from production settings
    """

    def import_settings(self, **overrides):
        """
        Import the verification settings in a fresh process without local secrets

        Parameters
        ----------
        **overrides : str or None
            Explicit environment additions or removals for one validation case.

        Returns
        -------
        CompletedProcess
            Import result and a small description of the configured database.
        """
        root = Path(__file__).resolve().parents[2]
        environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")
                       if key in os.environ}
        environment.update(LOCAL_POSTGRES_PORT="55439", LOCAL_POSTGRES_DB="collection_test_graph",
                           LOCAL_POSTGRES_USER="local_test_role", PYTHONPATH=str(root))
        for key, value in overrides.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        script = textwrap.dedent(
            """
            import json
            import os
            import dotenv

            def reject_dotenv_unless_disabled(*args, **kwargs):
                '''
                Reject environment file loading before the test settings opt out
                '''
                if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
                    raise RuntimeError("Local environment file was not disabled before settings import")
                return False

            dotenv.load_dotenv = reject_dotenv_unless_disabled
            from config import settings_postgres_test as settings
            print(json.dumps({"database": settings.DATABASES["default"], "debug": settings.DEBUG}))
            """
        )
        return subprocess.run([sys.executable, "-c", script], cwd=root, env=environment,
                              text=True, capture_output=True, timeout=15)

    def test_explicit_local_database_ignores_production_environment(self):
        """
        Keep all database fields local even when production variables are supplied
        """
        result = self.import_settings(
            DEBUG="False", DB_HOST="production.invalid", DB_PORT="5432", DB_NAME="postgres",
            DB_USERNAME="production_user", DB_PASS="production_password", LOCAL_POSTGRES_HOST="production.invalid",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["debug"])
        self.assertEqual(payload["database"], {
            "ENGINE": "django.db.backends.postgresql", "HOST": "127.0.0.1", "PORT": "55439",
            "NAME": "collection_test_graph", "USER": "local_test_role", "PASSWORD": "",
            "OPTIONS": {"sslmode": "disable"}, "CONN_MAX_AGE": 0,
            "TEST": {"NAME": "test_collection_test_graph"},
        })

    def test_local_password_is_explicit(self):
        """
        Accept only the separately named password for the local database role
        """
        result = self.import_settings(LOCAL_POSTGRES_PASSWORD="local_password", DB_PASS="unused_password")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["database"]["PASSWORD"], "local_password")

    def test_local_port_must_be_explicit_and_valid(self):
        """
        Fail before connection when the local port is absent or malformed
        """
        for port in (None, "", "0", "65536", "-1", "5432x", "５４３２"):
            with self.subTest(port=port):
                result = self.import_settings(LOCAL_POSTGRES_PORT=port)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LOCAL_POSTGRES_PORT", result.stderr)

    def test_database_name_requires_the_local_test_prefix(self):
        """
        Reject absent, unrelated and unsafe database names before connection
        """
        for name in (None, "", "postgres", "collection_test_", "collection_test_bad-name", "collection_test_" + "a" * 39):
            with self.subTest(name=name):
                result = self.import_settings(LOCAL_POSTGRES_DB=name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LOCAL_POSTGRES_DB", result.stderr)

    def test_local_role_must_be_explicit(self):
        """
        Prevent fallback to a production or operating system database role
        """
        for user in (None, "", "   "):
            with self.subTest(user=user):
                result = self.import_settings(LOCAL_POSTGRES_USER=user, DB_USERNAME="production_user")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LOCAL_POSTGRES_USER", result.stderr)
