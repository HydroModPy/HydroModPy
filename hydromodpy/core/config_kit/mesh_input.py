"""Schema contract for the optional ``[mesh_input]`` section.

The ``[mesh_input]`` section declares a pre-existing mesh that the simulation
or comparison workflow should consume instead of running the embedded
mesh-catchment workflow. At least one of ``mesh_path`` or ``bundle_dir`` must
be set; both may be set when the external mesh ships with a solver-exchange
bundle.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class MeshInputConfig(HydroModelBase):
    """External pre-existing mesh declared in ``[mesh_input]``.

    Either ``mesh_path`` or ``bundle_dir`` must be provided. Paths are stored
    as ``Path`` instances; relative paths are resolved by the call site (the
    simulation launcher resolves them against the TOML directory).
    """

    mesh_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Path to the external planar mesh file (typically a ``.msh``). "
            "Required when ``bundle_dir`` is not provided. "
            "Relative paths are resolved against the TOML directory."
        ),
    )
    bundle_dir: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Path to the solver-exchange mesh bundle directory associated with "
            "the external mesh. Required when ``mesh_path`` is not provided. "
            "Relative paths are resolved against the TOML directory."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_path(self) -> MeshInputConfig:
        if self.mesh_path is None and self.bundle_dir is None:
            raise ValueError("[mesh_input] requires at least one of 'mesh_path' or 'bundle_dir'.")
        return self


def parse_mesh_input_config_data(config_data: Mapping[str, Any]) -> MeshInputConfig:
    """Validate one ``[mesh_input]`` section and return the typed model."""
    if not isinstance(config_data, Mapping):
        raise ValueError("[mesh_input] configuration must be a mapping when provided.")
    try:
        return MeshInputConfig.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


__all__ = [
    "MeshInputConfig",
    "parse_mesh_input_config_data",
]
