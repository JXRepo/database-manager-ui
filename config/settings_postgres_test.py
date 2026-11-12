"""
Run database verification against an explicitly selected local PostgreSQL instance
"""

import os
import re

from django.core.exceptions import ImproperlyConfigured


_local_port = os.environ.get("LOCAL_POSTGRES_PORT", "")
_local_database = os.environ.get("LOCAL_POSTGRES_DB", "")
_local_user = os.environ.get("LOCAL_POSTGRES_USER", "")
if not re.fullmatch(r"[0-9]{1,5}", _local_port) or not 1 <= int(_local_port) <= 65535:
    raise ImproperlyConfigured("Set LOCAL_POSTGRES_PORT to the local test server's port.")
if not re.fullmatch(r"collection_test_[a-z0-9_]{1,38}", _local_database):
    raise ImproperlyConfigured("LOCAL_POSTGRES_DB must start with collection_test_ and use lowercase letters, digits or underscores.")
if not _local_user.strip():
    raise ImproperlyConfigured("Set LOCAL_POSTGRES_USER to a local role with permission to create test databases.")

os.environ["DEBUG"] = "True"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from .settings import *


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": _local_port,
        "NAME": _local_database,
        "USER": _local_user,
        "PASSWORD": os.environ.get("LOCAL_POSTGRES_PASSWORD", ""),
        "OPTIONS": {"sslmode": "disable"},
        "CONN_MAX_AGE": 0,
        "TEST": {"NAME": "test_" + _local_database},
    },
}
