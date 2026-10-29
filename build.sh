#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Download GeoIP database (DB-IP Lite) with fault tolerance
python manage.py descargar_geoip || true

# Collect static files with WhiteNoise
python manage.py collectstatic --noinput

# Apply database migrations
python manage.py migrate
