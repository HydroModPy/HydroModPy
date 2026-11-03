"""``workspace.toml`` template generator and Pydantic validator.

The workspace-level metadata file ``workspace.toml`` lives at the root of every
HydroModPy workspace. It carries the research-thematic identity of the
collection of projects below it: contact, geographic scope, team, license. The
contents are intentionally minimal (~20 lines) and meant to be edited by the
user once at workspace creation time.

A Pydantic v2 model validates the file at load time so a hand-edited
``workspace.toml`` that breaks the contract surfaces a clear error before
producing crashes later in the pipeline. The file is written by hand, so the
model stays ``extra="forbid"``.

``hydromodpy_version_min`` is the oldest HydroModPy the workspace accepts, and
reading the file refuses an older one. A pre-release counts as its release:
2.0.0a5 opens a workspace that asks for 2.0.0.

Specification: ``reports_db/99_master.md §5.4``.
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.paths import WORKSPACE_TOML_FILENAME
from hydromodpy.core.units.types import LengthMeters
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION

NEAR_SITE_M_DEFAULT: float = 500.0
"""Default of ``[sites] near_site_m``, in meters."""

WORKSPACE_VERSION_MIN: str = "2.0.0"
"""What a new workspace asks of HydroModPy: the first release of the 2 line."""

DEFAULT_WORKSPACE_TOML_TEMPLATE: str = """\
[workspace]
name = "{project_name}"
description = ""
contact = "{creator_email}"
creator_name = "{creator_name}"
creator_institution = ""
created_at = "{created_at}"
# license = ""  # SPDX id you publish your own outputs under; nobody chose one yet
hydromodpy_version_min = "{hydromodpy_version_min}"

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
    creator_name: str = Field(
        "", description="Who produced the runs, stamped as ACDD creator_name at seal"
    )
    creator_institution: str = Field(
        "", description="Institution of the creator, stamped as ACDD creator_institution"
    )
    created_at: str = Field(..., description="ISO-8601 UTC creation timestamp")
    license: str = Field(
        "",
        description=(
            "SPDX-style license slug the user chooses to publish their own "
            "outputs under. Empty means undeclared; a run's own license is "
            "derived from its inputs, never from this field."
        ),
    )
    hydromodpy_version_min: str = Field(
        WORKSPACE_VERSION_MIN,
        description="Oldest HydroModPy that opens this workspace; an older one refuses it",
    )
    geographic_scope: GeographicScopeMetadata = GeographicScopeMetadata()
    team: TeamMetadata = TeamMetadata()
    tags: TagsMetadata = TagsMetadata()

    @field_validator("hydromodpy_version_min")
    @classmethod
    def _is_a_version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as exc:
            raise ValueError(f"{value!r} is not a version: write it as 2.0.0") from exc
        return value


class SitesMetadata(BaseModel):
    """``[sites]`` block: how the site catalog of the workspace tells two sites apart."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    near_site_m: LengthMeters = Field(
        NEAR_SITE_M_DEFAULT,
        gt=0.0,
        description=(
            "Distance in metres under which two outlets are taken for one catchment. "
            "hmp site add and hmp site import refuse an outlet closer than this to a "
            "site declared under another name, unless --force is passed. Accepts a "
            'length such as "500 m" or "1 km".'
        ),
    )


class ConventionsMetadata(BaseModel):
    """``[conventions]`` top-level block."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cf: str = "CF-1.11"
    acdd: str = "ACDD-1.3"


class WorkspaceToml(BaseModel):
    """Top-level parsed representation of ``workspace.toml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: WorkspaceMetadata
    sites: SitesMetadata = SitesMetadata()
    conventions: ConventionsMetadata = ConventionsMetadata()


def _toml_escape(value: str) -> str:
    """Escape *value* for a TOML basic string, so a quote cannot break the file."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_workspace_toml(
    *,
    project_name: str,
    creator_name: str,
    creator_email: str,
    created_at: str | None = None,
) -> str:
    """Return the rendered ``workspace.toml`` content as a string."""
    timestamp = created_at if created_at is not None else datetime.now(UTC).isoformat()
    escaped_name = _toml_escape(creator_name)
    creator_name_quoted = f'"{escaped_name}"' if creator_name else ""
    return DEFAULT_WORKSPACE_TOML_TEMPLATE.format(
        project_name=project_name,
        creator_email=creator_email,
        created_at=timestamp,
        creator_name=escaped_name,
        creator_name_quoted=creator_name_quoted,
        hydromodpy_version_min=WORKSPACE_VERSION_MIN,
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
    ``tomllib.TOMLDecodeError`` if the file is not valid TOML,
    ``pydantic.ValidationError`` if any field is missing, mistyped, or
    unknown (the model is ``extra="forbid"``), and
    :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError` if the
    file asks for a newer HydroModPy than the one installed.
    """
    ws = Path(workspace).expanduser().resolve()
    toml_path = ws / WORKSPACE_TOML_FILENAME
    if not toml_path.is_file():
        raise FileNotFoundError(
            f"No {WORKSPACE_TOML_FILENAME} at {toml_path}. "
            "Run `hmp workspace init` to scaffold the workspace."
        )
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    parsed = WorkspaceToml.model_validate(data)
    _refuse_a_newer_minimum(parsed.workspace.hydromodpy_version_min, toml_path)
    return parsed


def refuse_a_newer_workspace(root: Path) -> None:
    """Refuse when ``<root>/workspace.toml`` asks for more than the installed HydroModPy.

    Every run and every command on a workspace passes here, before any work. It
    reads that one key: a mistake elsewhere in the file is said by
    :func:`load_workspace_toml`, where the file is needed.
    """
    toml_path = Path(root) / WORKSPACE_TOML_FILENAME
    try:
        document = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        minimum = document["workspace"]["hydromodpy_version_min"]
        _refuse_a_newer_minimum(str(minimum), toml_path)
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError, InvalidVersion):
        # No file, no key, or a file that does not parse: nothing asks for a version here.
        return


def _refuse_a_newer_minimum(minimum: str, toml_path: Path) -> None:
    """Refuse a workspace that asks for more than the installed HydroModPy."""
    asked, installed = Version(minimum), Version(HYDROMODPY_VERSION)
    if Version(installed.base_version) >= Version(asked.base_version):
        return
    raise SchemaVersionMismatchError(
        f"{toml_path} asks for hydromodpy_version_min = {minimum!r}, and HydroModPy "
        f"{HYDROMODPY_VERSION} is installed. Upgrade HydroModPy to open this workspace.",
        document=str(toml_path),
        found=minimum,
        expected=HYDROMODPY_VERSION,
    )


def near_site_m(workspace: Path) -> float:
    """Return ``[sites] near_site_m`` of a workspace, the default when it has no file."""
    if not (Path(workspace).expanduser() / WORKSPACE_TOML_FILENAME).is_file():
        return NEAR_SITE_M_DEFAULT
    return load_workspace_toml(workspace).sites.near_site_m


__all__ = [
    "DEFAULT_WORKSPACE_TOML_TEMPLATE",
    "NEAR_SITE_M_DEFAULT",
    "WORKSPACE_VERSION_MIN",
    "SitesMetadata",
    "ConventionsMetadata",
    "GeographicScopeMetadata",
    "TagsMetadata",
    "TeamMetadata",
    "WorkspaceMetadata",
    "WorkspaceToml",
    "load_workspace_toml",
    "near_site_m",
    "refuse_a_newer_workspace",
    "render_workspace_toml",
    "write_workspace_toml",
]
