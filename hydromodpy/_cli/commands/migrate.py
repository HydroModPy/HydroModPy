"""Placeholder for a future ``hmp migrate`` subcommand.

Reserved slot. The previous content (a two-phase migrator that moved
pre-v0.6 DuckDB tables to per-sim Parquet, then renamed UUID-style
folders to readable basenames) has been removed because the project
does not yet ship to outside users with legacy workspaces. New
schema-evolving changes simply break old workspaces; users regenerate.

If a future change needs a stable upgrade path, a real migration
command can be added here and re-registered in
``hydromodpy/_cli/commands/__init__.py``.
"""

from __future__ import annotations
