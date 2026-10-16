"""What a comparison of sealed runs reads: the runs, the observables, the raster.

:class:`ComparisonSpec` is built by ``hmp report compare`` from N run
directories (:mod:`hydromodpy.analysis.comparison.runs`). It is never written
by a user and never read from a TOML: the runs say what they are in their
``manifest.json``, the observables come from the ``--variables`` of the command.
The analysis modules (``runtime/``, ``visuals*``, ``exports/``) take it as
their single description of the comparison.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    IdentifierStr,
    NonEmptyStr,
    NonNegativeInt,
    OptionalText,
    PositiveFloat,
)
from hydromodpy.core.config_kit.validators import validate_optional_identifier

MeshMode = Literal["triangle", "voronoi", "sgrid", "structured", "unstructured", "unknown"]
"""Mesh kind of a compared run, read from ``geometry.mesh_topology`` of its manifest."""


def _normalize_optional_mesh_label(value: object) -> str | None:
    text = validate_optional_identifier(value)
    if text is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not normalized:
        return None
    if not normalized[0].isalpha():
        normalized = f"mesh_{normalized}"
    return normalized


class ComparisonSimulation(HydroModelBase):
    """One sealed run of a comparison."""

    id: str = Field(description="Name of the run directory, with its .vN.")
    label: str | None = Field(default=None, description="Label used in plots and reports.")
    run_dir: Path = Field(description="Absolute path of the sealed run directory.")
    solver: str | None = Field(default=None, description="Solver of the run, from its manifest.")
    mesh_label: str | None = Field(
        default=None, description="Mesh hash of the run, used to group runs on one mesh."
    )
    mesh_mode: MeshMode = Field(
        default="unknown", description="Mesh kind, used by the map renderers."
    )

    _normalize_mesh_label = field_validator("mesh_label", mode="before")(
        _normalize_optional_mesh_label
    )


class ComparisonObservable(HydroModelBase):
    """One quantity of interest extracted from each compared run."""

    name: Annotated[IdentifierStr, Profile.USER] = Field(
        description="Unique identifier of this observable inside the comparison.",
        examples=["outlet_q"],
    )
    variable: Annotated[NonEmptyStr, Profile.USER] = Field(
        description="Name of the simulated variable to extract (e.g. head, discharge).",
        examples=["discharge"],
    )
    source: Annotated[Literal["disk"], Profile.USER] = Field(
        default="disk",
        description="Backing store for the extracted values; currently only disk outputs.",
    )
    simulations: Annotated[list[IdentifierStr] | None, Profile.USER] = Field(
        default=None,
        description="Subset of simulation ids this observable applies to; null means all.",
    )
    support: Annotated[Literal["point", "outlet", "boundary", "cell_mask", "map"], Profile.USER] = (
        Field(
            default="point",
            description="Spatial support of the observable (point, outlet, boundary, mask, map).",
            json_schema_extra={
                "value_docs": {
                    "point": "Reads a single cell picked by x/y or cell_index.",
                    "outlet": "Reads the outlet cell given by cell_index or x/y, then sums it.",
                    "boundary": "Sums the cells listed in cell_indices, or the whole "
                    "domain when none are listed.",
                    "cell_mask": "Same extraction as boundary: sums the cells listed "
                    "in cell_indices.",
                    "map": "Keeps the full spatial field with no reduction.",
                }
            },
        )
    )
    x: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Easting in meters, in the CRS of the runs.",
        json_schema_extra={"unit": "m"},
    )
    y: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Northing in meters, in the CRS of the runs.",
        json_schema_extra={"unit": "m"},
    )
    cell_index: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Zero-based mesh cell index for point or outlet support.",
        json_schema_extra={"unit": "-"},
    )
    cell_indices: Annotated[list[NonNegativeInt] | None, Profile.USER] = Field(
        default=None,
        min_length=1,
        description="List of zero-based mesh cell indices used for cell_mask support.",
    )
    boundary_id: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description="Identifier of the boundary group selected for boundary support.",
    )
    allow_domain_proxy: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Allow whole-domain reduction as outlet fallback when no location is set.",
    )
    time: Annotated[str | int | None, Profile.USER] = Field(
        default="all",
        description="Timestep selector (timestamp, integer index, or 'all').",
    )
    time_window: Annotated[tuple[str, str] | tuple[float, float] | None, Profile.USER] = Field(
        default=None,
        description="Optional inclusive time window as a (start, end) pair, mutually exclusive with time.",
    )
    reducer: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Spatial reducer applied over the support (e.g. nearest_cell, sum, max).",
    )
    time_reducer: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Temporal reducer applied over the selected timesteps (e.g. mean, sum).",
    )
    unit: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Optional unit label attached to the extracted values for display.",
    )

    _normalize_boundary_id = field_validator("boundary_id")(validate_optional_identifier)

    @field_validator("simulations")
    @classmethod
    def _validate_simulations(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("observable.simulations must be a non-empty list")
        cleaned = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("observable.simulations cannot contain empty ids")
            cleaned.append(text)
        return cleaned

    @model_validator(mode="before")
    @classmethod
    def _default_reducer(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_reducer = payload.get("reducer")
        if raw_reducer is not None and str(raw_reducer).strip():
            return payload
        support = str(payload.get("support", "point")).strip()
        if support == "point":
            payload["reducer"] = "nearest_cell"
        elif support == "outlet":
            variable_key = str(payload.get("variable", "")).strip().lower()
            payload["reducer"] = "max" if "accumulation" in variable_key else "sum"
        elif support in {"boundary", "cell_mask"}:
            payload["reducer"] = "sum"
        elif support == "map":
            payload["reducer"] = "identity"
        return payload

    @model_validator(mode="after")
    def _validate_support_specific_fields(self) -> ComparisonObservable:
        if self.time is not None and self.time_window is not None:
            raise ValueError("an observable cannot declare both time and time_window")
        has_coordinates = self.x is not None and self.y is not None
        if self.support == "point":
            if not has_coordinates and self.cell_index is None:
                raise ValueError("point observables require x/y coordinates or cell_index")
        elif self.support == "outlet":
            if self.cell_index is None and not has_coordinates and not self.allow_domain_proxy:
                raise ValueError(
                    "outlet observables require cell_index or x/y coordinates. "
                    "Set allow_domain_proxy=true only for exploratory whole-domain "
                    "reducer comparisons."
                )
        elif self.support == "boundary":
            if self.boundary_id is None and not self.cell_indices:
                raise ValueError("boundary observables require boundary_id or cell_indices")
        return self


class ComparisonFineRaster(HydroModelBase):
    """Optional common regular-grid rasterization for map comparisons."""

    enabled: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="Enable the shared fine raster for map comparisons.",
    )
    resolution: Annotated[PositiveFloat | None, Profile.EXPERT] = Field(
        default=None,
        description="Target raster cell size in meters, in the CRS of the runs.",
    )
    extent_mode: Annotated[Literal["intersection", "union", "reference"], Profile.EXPERT] = Field(
        default="intersection",
        description="Strategy used to derive the common raster extent across simulations.",
    )
    interpolation: Annotated[Literal["linear", "nearest"], Profile.EXPERT] = Field(
        default="linear",
        description="Regridding method used to project each map onto the shared fine raster.",
    )
    write_geotiff: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description="Write the regridded maps as GeoTIFF files alongside the comparison figures.",
    )

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> ComparisonFineRaster:
        if self.enabled and self.resolution is None:
            raise ValueError("fine_raster.resolution is required when fine_raster.enabled=true")
        return self


class ComparisonSpec(HydroModelBase):
    """One comparison of sealed runs: the runs, the observables, where it writes."""

    comparison_id: str = Field(description="Name of the comparison, also its folder name.")
    comparison_root: Path = Field(description="Folder the comparison writes into.")
    reference_simulation: str | None = Field(
        default=None, description="Run used as the reference for differences and grids."
    )
    fine_raster: ComparisonFineRaster | None = Field(
        default=None, description="Shared raster used to compare maps cell for cell."
    )
    simulation: list[ComparisonSimulation] = Field(
        min_length=1, description="The compared runs, reference first."
    )
    observable: list[ComparisonObservable] = Field(
        min_length=1, description="The observables read from every run."
    )

    @model_validator(mode="after")
    def _validate_ids(self) -> ComparisonSpec:
        ids = [simulation.id for simulation in self.simulation]
        if len(set(ids)) != len(ids):
            raise ValueError(f"the compared runs must be distinct, got {ids}")
        names = [observable.name for observable in self.observable]
        if len(set(names)) != len(names):
            raise ValueError(f"observable names must be unique, got {names}")
        if self.reference_simulation is not None and self.reference_simulation not in ids:
            raise ValueError(
                f"reference_simulation {self.reference_simulation!r} is not one of {ids}"
            )
        return self

    def simulation_by_id(self, simulation_id: str) -> ComparisonSimulation | None:
        """Return the compared run named *simulation_id*, or None."""
        return next((item for item in self.simulation if item.id == simulation_id), None)


__all__ = (
    "ComparisonFineRaster",
    "ComparisonObservable",
    "ComparisonSimulation",
    "ComparisonSpec",
    "MeshMode",
)
