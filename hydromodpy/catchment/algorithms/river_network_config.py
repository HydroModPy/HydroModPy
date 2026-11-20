"""The ``[geographic.river_network]`` table, the river network extracted from the DEM."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.units.types import LengthMeters

__all__ = [
    "RiverNetworkConfig",
    "river_network_for_the_mesh",
]


class RiverNetworkConfig(HydroModelBase):
    """Optional DEM-based river network extraction settings.

    Enable this block when geographic preprocessing must derive streams from
    flow accumulation. Thresholds can be expressed as contributing area
    (``area_km2``) or contributing cell count (``cells``), with optional
    pruning and Strahler/link rasters for downstream diagnostics.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Enable DEM-based river-network extraction from flow accumulation "
            "during geographic preprocessing."
        ),
    )
    threshold_mode: Annotated[Literal["area_km2", "cells"], Profile.USER] = Field(
        default="area_km2",
        description=(
            "Stream-initiation threshold selector. "
            "'area_km2' uses contributing area in km^2. "
            "'cells' uses contributing-cell count directly."
        ),
    )
    threshold_area_km2: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "area_km2"),
    ] = Field(
        default=None,
        description=(
            "Contributing area threshold (km^2), required when threshold_mode='area_km2'."
        ),
    )
    threshold_cells: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "cells"),
    ] = Field(
        default=None,
        description=(
            "Number of upstream cells a cell must drain to start a stream. A count of DEM cells."
        ),
        json_schema_extra={"unit": "-"},
    )
    prune_short_streams: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="If true, remove short stream segments after extraction.",
    )
    min_stream_length_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum stream length (metres) used by short-segment pruning. "
            "Accepts inline units (e.g. 0, 250, '250 m', '0.5 km')."
        ),
    )
    compute_strahler_order: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute Strahler order raster from extracted streams.",
    )
    compute_stream_links: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute stream-link identifier raster from extracted streams.",
    )
    all_vertices: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Forwarded to Whitebox raster_streams_to_vector. False keeps a lighter vector geometry."
        ),
    )

    @model_validator(mode="after")
    def _validate_threshold_payload(self) -> RiverNetworkConfig:
        if not bool(self.enabled):
            return self

        mode = str(self.threshold_mode)
        if mode == "area_km2":
            if self.threshold_area_km2 is None:
                raise ValueError(
                    "geographic.river_network.threshold_mode='area_km2' requires "
                    "geographic.river_network.threshold_area_km2."
                )
            if float(self.threshold_area_km2) <= 0.0:
                raise ValueError("geographic.river_network.threshold_area_km2 must be > 0.")
            if self.threshold_cells is not None:
                raise ValueError(
                    "geographic.river_network.threshold_cells must be omitted when "
                    "threshold_mode='area_km2'."
                )
            return self

        if self.threshold_cells is None:
            raise ValueError(
                "geographic.river_network.threshold_mode='cells' requires "
                "geographic.river_network.threshold_cells."
            )
        if float(self.threshold_cells) <= 0.0:
            raise ValueError("geographic.river_network.threshold_cells must be > 0.")
        if self.threshold_area_km2 is not None:
            raise ValueError(
                "geographic.river_network.threshold_area_km2 must be omitted when "
                "threshold_mode='cells'."
            )
        return self

    def missing_threshold_refusal(self, *, needed_by: str) -> str | None:
        """Return why a network that *needed_by* switches on has no threshold, or None.

        A mesh that follows the rivers switches the extraction on by itself.
        The threshold check of an enabled network then never ran, and the
        extraction stopped later on a bare ``threshold_area_km2 must be > 0``.
        """
        mode = str(self.threshold_mode)
        key = "threshold_area_km2" if mode == "area_km2" else "threshold_cells"
        value = getattr(self, key)
        if value is not None and float(value) > 0.0:
            return None
        return (
            f"{needed_by} needs the river network drawn from the DEM, and "
            f"[geographic.river_network] gives no {key} for threshold_mode = {mode!r}. "
            f"Set {key} under [geographic.river_network], for example "
            + (
                "threshold_area_km2 = 0.5."
                if key == "threshold_area_km2"
                else "threshold_cells = 500."
            )
        )


def river_network_for_the_mesh(cfg: Any) -> Any:
    """Return ``cfg.geographic`` with ``[geographic.river_network]`` on when the mesh needs it.

    The rule is :meth:`MeshConfig.requires_river_trace`. The config refused a
    mesh that needs the network without its threshold when it loaded, so the
    network can be switched on as it is. A project and a calibration trial both
    read the geographic through here, so a file that runs also calibrates.
    """
    geographic = cfg.geographic
    network = geographic.river_network
    if network.enabled or cfg.mesh is None:
        return geographic
    active_bc = {str(bc).strip().lower() for bc in cfg.flow.active_bc}
    if not cfg.mesh.requires_river_trace(
        active_bc=active_bc, synthetic=geographic.uses_synthetic_geographic()
    ):
        return geographic
    return geographic.model_copy(
        update={"river_network": network.model_copy(update={"enabled": True})}, deep=True
    )
