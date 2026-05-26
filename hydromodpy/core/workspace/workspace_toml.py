"""``workspace.toml`` template generator and Pydantic validator.

The workspace-level metadata file ``workspace.toml`` lives at the root of every
HydroModPy workspace. It carries the research-thematic identity of the
collection of projects below it: contact, geographic scope, team, license. The
contents are intentionally minimal (~20 lines) and meant to be edited by the
user once at workspace creation time.

A Pydantic v2 model validates the file at load time so a hand-edited
``workspace.toml`` that breaks the contract surfaces a clear error before
producing crashes later in the pipeline.

Specification: ``reports_db/99_master.md §5.4``.
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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


class GeographicScopeMetadata(BaseModel):
    """``[workspace.geographic_scope]`` block."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    region: str = ""
    bbox_wgs84: tuple[float, float, float, float] = (-180.0, -90.0, 180.0, 90.0)


class TeamMetadata(BaseModel):
    """``[workspace.team]`` block."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    members: tuple[str, ...] = ()


class TagsMetadata(BaseModel):
    """``[workspace.tags]`` block."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    themes: tuple[str, ...] = ()


class WorkspaceMetadata(BaseModel):
    """``[workspace]`` block, with nested sub-tables."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(..., min_length=1, description="Workspace name")
    description: str = ""
    contact: str = Field(..., description="Workspace contact email")
    created_at: str = Field(..., description="ISO-8601 UTC creation timestamp")
    license: str = Field("etalab-2.0", description="SPDX-style license slug")
    hydromodpy_version_min: str = Field(
        "2.0.0", description="Minimum compatible HydroModPy version"
    )
    geographic_scope: GeographicScopeMetadata = GeographicScopeMetadata()
    team: TeamMetadata = TeamMetadata()
    tags: TagsMetadata = TagsMetadata()


class ConventionsMetadata(BaseModel):
    """``[conventions]`` top-level block."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cf: str = "CF-1.11"
    acdd: str = "ACDD-1.3"


class WorkspaceToml(BaseModel):
    """Top-level parsed representation of ``workspace.toml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: WorkspaceMetadata
    conventions: ConventionsMetadata = ConventionsMetadata()


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


def load_workspace_toml(workspace: Path) -> WorkspaceToml:
    """Load and validate ``<workspace>/workspace.toml`` via Pydantic.

    Raises ``FileNotFoundError`` if the file is missing,
    ``tomllib.TOMLDecodeError`` if the file is not valid TOML, and
    ``pydantic.ValidationError`` if any field is missing, mistyped, or
    unknown (the model is ``extra="forbid"``).
    """
    ws = Path(workspace).expanduser().resolve()
    toml_path = ws / WORKSPACE_TOML_FILENAME
    if not toml_path.is_file():
        raise FileNotFoundError(
            f"No {WORKSPACE_TOML_FILENAME} at {toml_path}. "
            "Run `hmp workspace init` to scaffold the workspace."
        )
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    return WorkspaceToml.model_validate(data)


__all__ = [
    "DEFAULT_WORKSPACE_TOML_TEMPLATE",
    "ConventionsMetadata",
    "GeographicScopeMetadata",
    "TagsMetadata",
    "TeamMetadata",
    "WorkspaceMetadata",
    "WorkspaceToml",
    "load_workspace_toml",
    "render_workspace_toml",
    "write_workspace_toml",
]
