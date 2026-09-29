#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt
python manage.py prepare_assistant_model
python manage.py collectstatic --no-input
python manage.py migrate --noinput
