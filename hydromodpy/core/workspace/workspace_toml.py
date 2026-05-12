"""``workspace.toml`` template generator.

The workspace-level metadata file ``workspace.toml`` lives at the root of every
HydroModPy workspace. It carries the research-thematic identity of the
collection of projects below it: contact, geographic scope, team, license. The
contents are intentionally minimal (~20 lines) and meant to be edited by the
user once at workspace creation time.

Specification: ``reports_db/99_master.md §5.4``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.core.state.paths import WORKSPACE_TOML_FILENAME

DEFAULT_WORKSPACE_TOML_TEMPLATE: str = """\
[workspace]
name = "{project_name}"
description = ""
contact = "{creator_email}"
created_at = "{created_at}"
license = "etalab-2.0"
hydromodpy_version_min = "2.0.0"

[workspace.geographic_scope]
region = ""
bbox_wgs84 = [-180.0, -90.0, 180.0, 90.0]

[workspace.team]
members = [{creator_name_quoted}]

[workspace.tags]
themes = []

[conventions]
cf = "CF-1.11"
acdd = "ACDD-1.3"
"""


def render_workspace_toml(
    *,
    project_name: str,
    creator_name: str,
    creator_email: str,
    created_at: str | None = None,
) -> str:
    """Return the rendered ``workspace.toml`` content as a string."""
    timestamp = created_at if created_at is not None else datetime.now(UTC).isoformat()
    creator_name_quoted = f'"{creator_name}"' if creator_name else ""
    return DEFAULT_WORKSPACE_TOML_TEMPLATE.format(
        project_name=project_name,
        creator_email=creator_email,
        created_at=timestamp,
        creator_name_quoted=creator_name_quoted,
    )


def write_workspace_toml(
    workspace: Path,
    *,
    project_name: str,
    creator_name: str,
    creator_email: str,
    force: bool = False,
    created_at: str | None = None,
) -> Path:
    """Write the workspace metadata TOML at ``<workspace>/workspace.toml``.

    Idempotent: when the file exists and ``force`` is False the existing
    content is preserved untouched. ``force=True`` overwrites it.
    """
    ws = Path(workspace).expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / WORKSPACE_TOML_FILENAME
    if target.exists() and not force:
        return target
    content = render_workspace_toml(
        project_name=project_name,
        creator_name=creator_name,
        creator_email=creator_email,
        created_at=created_at,
    )
    target.write_text(content, encoding="utf-8")
    return target


__all__ = [
    "DEFAULT_WORKSPACE_TOML_TEMPLATE",
    "render_workspace_toml",
    "write_workspace_toml",
]
