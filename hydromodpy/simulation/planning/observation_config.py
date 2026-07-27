"""Pydantic configuration models for the ``[observation]`` section.

Declares the points a run must sample while it still holds its own outputs:
piezometers, a probe on a lake shore, any location whose series is wanted
every time. Sampling them at run time turns a later interrogation into a plain
table read, and the declaration is persisted with the run
(``tables.parquet/observation_points.parquet``) so rebuilding the index does
not lose it.

This is not ``[data.piezometry]``: that section loads *measured* series from a
data source, this one declares *where the model is read*.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

DEFAULT_OBSERVATION_VARIABLES: tuple[str, ...] = ("head",)
"""Variables sampled at a declared point when the section names none."""


class ObservationPointConfig(HydroModelBase):
    """One declared observation point, in the coordinates of the project."""

    id: Annotated[str, Profile.USER] = Field(
        description="Station id of the point. Unique within the section.",
    )
    x: Annotated[float, Profile.USER] = Field(
        description="Easting in the project CRS (same units as the mesh).",
    )
    y: Annotated[float, Profile.USER] = Field(
        description="Northing in the project CRS (same units as the mesh).",
    )
    layer: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Zero-based layer index to read. Mutually exclusive with 'depth'.",
    )
    depth: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0.0,
        description=(
            "Depth in metres below the local model top; picks the layer from the "
            "mesh layer thicknesses. Mutually exclusive with 'layer'."
        ),
    )
    variables: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Variables sampled at this point. Defaults to the section-level 'variables' list."
        ),
    )

    @model_validator(mode="after")
    def _check_vertical_selector(self) -> ObservationPointConfig:
        if self.layer is not None and self.depth is not None:
            raise ValueError(
                f"Observation point '{self.id}' declares both 'layer' and 'depth'; keep one."
            )
        return self


class ObservationConfig(HydroModelBase):
    """Configuration for ``[observation]``: points sampled during the run.

    Example
    -------
    .. code-block:: toml

        [observation]
        variables = ["head", "watertable_depth"]

        [[observation.points]]
        id = "piezo_amont"
        x = 395100.0
        y = 6824925.0
        depth = 12.5
    """

    points: Annotated[list[ObservationPointConfig], Profile.USER] = Field(
        default_factory=list,
        description="Observation points sampled once the run has produced its fields.",
    )
    variables: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: list(DEFAULT_OBSERVATION_VARIABLES),
        description=(
            "Variables sampled at every point that does not name its own. "
            "Virtual fields (watertable_depth, seepage_mask ...) are accepted."
        ),
    )

    @model_validator(mode="after")
    def _check_unique_ids(self) -> ObservationConfig:
        seen: set[str] = set()
        for point in self.points:
            if point.id in seen:
                raise ValueError(f"Duplicate observation point id '{point.id}'.")
            seen.add(point.id)
        return self

    def declarations(self) -> list[dict[str, object]]:
        """Return the points as plain dicts, variables already resolved.

        The transport format between the configuration and the result store:
        no Pydantic type crosses that boundary.
        """
        return [
            {
                "id": point.id,
                "x": float(point.x),
                "y": float(point.y),
                "layer": point.layer,
                "depth": point.depth,
                "variables": list(point.variables or self.variables),
            }
            for point in self.points
        ]


__all__ = [
    "DEFAULT_OBSERVATION_VARIABLES",
    "ObservationConfig",
    "ObservationPointConfig",
]
