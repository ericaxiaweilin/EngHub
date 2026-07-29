#!/bin/sh
set -eu

python /app/scripts/schema_migrate.py
exec "$@"
