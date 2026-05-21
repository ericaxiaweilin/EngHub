# Legacy App Directory

This directory is legacy code and is not part of the active backend boot path.

## Current status

- `main.py` does not import from `app/`.
- The active backend uses the root-level `api/`, `core/`, and `database/` packages.
- The original HRM prototype files were removed because they were not wired into the active backend and depended on missing modules.

## Guidance

- Do not add new production code under `app/`.
- Place all new backend work under the root application layout.
- If this directory is needed again, it should be migrated deliberately instead of extended in place.
