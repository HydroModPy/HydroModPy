"""Pydantic configuration of the solver top sampling, the ``sgrid`` table of a MODFLOW backend.

The planar grid is the mesh of ``[mesh]`` and the layering is ``[domain.layers]``. The
``sgrid`` table only says how the top of the solver grid is sampled from the DEM.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.model.domain.top_sampling_config import TopSamplingConfig
from hydromodpy.schema.changes import prerelease_refusal

_RETIRED_SGRID_KEYS = {
    "planar": (
        "[mesh]: write cell_size for a regular grid coarser than the DEM pixel, "
        "or [mesh.regular] shape = [nrow, ncol] for a fixed shape, and remove the key "
        "to keep the DEM pixels"
    ),
    "grid_dual": (
        '[mesh] engine: write engine = "voronoi" for the dual cells or '
        'engine = "triangle" for the triangulation cells'
    ),
    "vertical": (
        "[domain.layers]: the layering describes the aquifer, so one table serves every "
        "solver. Move the table there"
    ),
}


class SolverSGridConfig(HydroModelBase):
    """Solver-facing grid configuration: how the top of the grid is sampled.

    The planar grid is the mesh of ``[mesh]`` and the layering is ``[domain.layers]``,
    neither a key of this table.
    """

    top_sampling: Annotated[TopSamplingConfig, Profile.USER] = Field(
        default_factory=TopSamplingConfig,
        description="How the top of the solver grid is sampled from the DEM.",
    )

    @model_validator(mode="before")
    @classmethod
    def _name_the_mesh_section_of_a_retired_key(cls, data: Any) -> Any:
        """Refuse ``planar``, ``grid_dual`` and ``vertical`` and name the table that replaces them."""
        if isinstance(data, Mapping):
            for key, replacement in _RETIRED_SGRID_KEYS.items():
                if key in data:
                    raise ValueError(
                        f"sgrid.{key} is replaced by {replacement}. "
                        + prerelease_refusal("This table", [key])
                    )
        return data

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        payload = dict(config_data.get("sgrid", config_data))
        return cls.model_validate(payload)
