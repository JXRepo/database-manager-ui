import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml
from django.test import SimpleTestCase


class DeploymentArtifactTests(SimpleTestCase):
    """
    Verify Render blueprint and build script artifacts
    """

    @classmethod
    def setUpClass(cls):
        """
        Set shared artifact paths
        """
        super().setUpClass()
        cls.project_root = Path(__file__).resolve().parents[2]
        cls.render_yaml_path = cls.project_root / "render.yaml"
        cls.build_script_path = cls.project_root / "build.sh"

    def test_render_blueprint_matches_public_pilot_contract(self):
        """
        Render blueprint uses the public pilot free service contract
        """
        with self.render_yaml_path.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        self.assertEqual(list(payload), ["services"])
        self.assertEqual(len(payload["services"]), 1)

        service = payload["services"][0]
        self.assertEqual(service["type"], "web")
        self.assertEqual(service["name"], "fair-materials-data-hub")
        self.assertEqual(service["plan"], "free")
        self.assertEqual(service["runtime"], "python")
        self.assertEqual(service["region"], "frankfurt")
        self.assertEqual(service["buildCommand"], "bash build.sh")
        self.assertEqual(service["healthCheckPath"], "/healthz/")
        self.assertEqual(
            " ".join(service["startCommand"].split()),
            (
                "python -m gunicorn config.wsgi:application "
                "--bind 0.0.0.0:$PORT "
                "--workers 1 "
                "--access-logfile - "
                "--access-logformat '%(m)s %(s)s %(L)s %(b)s' "
                "--error-logfile -"
            ),
        )

        env_vars = {
            item["key"]: item
            for item in service["envVars"]
        }
        self.assertEqual(
            {key: env_vars[key]["value"] for key in (
                "PYTHON_VERSION",
                "DEBUG",
                "DB_ENGINE",
                "DB_PORT",
                "DB_SSLMODE",
                "ALLOWED_HOSTS",
                "CSRF_TRUSTED_ORIGINS",
                "TRUSTED_PROXY_HOPS",
                "ORCID_BASE_URL",
            )},
            {
                "PYTHON_VERSION": "3.12.13",
                "DEBUG": "False",
                "DB_ENGINE": "postgresql",
                "DB_PORT": "5432",
                "DB_SSLMODE": "require",
                "ALLOWED_HOSTS": "",
                "CSRF_TRUSTED_ORIGINS": "",
                "TRUSTED_PROXY_HOPS": "1",
                "ORCID_BASE_URL": "https://orcid.org",
            },
        )
        self.assertEqual(
            env_vars["SECRET_KEY"],
            {"key": "SECRET_KEY", "generateValue": True},
        )
        for key in (
            "DB_NAME",
            "DB_USERNAME",
            "DB_PASS",
            "DB_HOST",
            "ORCID_CLIENT_ID",
            "ORCID_CLIENT_SECRET",
            "ORCID_REDIRECT_URI",
        ):
            self.assertEqual(env_vars[key], {"key": key, "sync": False})

    def test_render_start_command_passes_only_safe_access_log_atoms(self):
        """
        The executed start command omits request data from access logs
        """
        with self.render_yaml_path.open(encoding="utf-8") as handle:
            service = yaml.safe_load(handle)["services"][0]

        result, records = self._run_start_command_with_recorder(
            service["startCommand"]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(records), 1)
        arguments = records[0]["args"]
        self.assertEqual(arguments[:3], ["-m", "gunicorn", "config.wsgi:application"])
        self.assertIn("--access-logformat", arguments)
        format_index = arguments.index("--access-logformat") + 1
        access_log_format = arguments[format_index]
        atoms = re.findall(r"%\(([^)]+)\)s", access_log_format)

        self.assertEqual(atoms, ["m", "s", "L", "b"])
        self.assertTrue({"m", "s", "L", "b"}.issubset(atoms))
        self.assertTrue({"r", "U", "q", "f", "a"}.isdisjoint(atoms))
        self.assertFalse(
            any(
                atom.startswith("{") and atom.endswith(("}i", "}o", "}e"))
                for atom in atoms
            )
        )

    def test_build_script_has_valid_bash_syntax(self):
        """
        Build script is valid bash
        """
        result = subprocess.run(
            ["bash", "-n", str(self.build_script_path)],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_script_runs_only_install_collectstatic_and_migrate(self):
        """
        Build script runs the required steps without yarn or makemigrations
        """
        result, records = self._run_build_script_with_recorders()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            records,
            [
                {
                    "program": "python",
                    "args": ["-m", "pip", "install", "-r", "requirements.txt"],
                },
                {
                    "program": "python",
                    "args": ["manage.py", "collectstatic", "--no-input"],
                },
                {
                    "program": "python",
                    "args": ["manage.py", "migrate", "--noinput"],
                },
            ],
        )

    def _run_build_script_with_recorders(self):
        """
        Execute a build script copy with fake python and yarn commands
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_copy = temp_path / "build.sh"
            shutil.copy2(self.build_script_path, script_copy)

            log_path = temp_path / "build-log.jsonl"
            for program_name in ("python", "pip", "yarn"):
                self._write_command_recorder(
                    temp_path / program_name,
                    program_name,
                    log_path,
                )

            env = os.environ.copy()
            env["PATH"] = f"{temp_path}{os.pathsep}{env.get('PATH', '')}"
            result = subprocess.run(
                ["bash", str(script_copy)],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                env=env,
            )

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            return result, records

    def _run_start_command_with_recorder(self, start_command):
        """
        Execute the Render start command with a fake Python executable

        Parameters
        ----------
        start_command : str
            Shell command loaded from the Render blueprint.

        Returns
        -------
        tuple
            Completed process and recorded command invocations.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_path = temp_path / "start-log.jsonl"
            self._write_command_recorder(
                temp_path / "python",
                "python",
                log_path,
            )

            env = os.environ.copy()
            env["PATH"] = f"{temp_path}{os.pathsep}{env.get('PATH', '')}"
            env["PORT"] = "8765"
            result = subprocess.run(
                ["bash", "-c", start_command],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                env=env,
            )
            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            return result, records

    def _write_command_recorder(self, path, program_name, log_path):
        """
        Write one executable command recorder
        """
        path.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json
                import sys
                from pathlib import Path

                Path({str(log_path)!r}).open("a", encoding="utf-8").write(
                    json.dumps({{"program": {program_name!r}, "args": sys.argv[1:]}})
                    + "\\n"
                )
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
