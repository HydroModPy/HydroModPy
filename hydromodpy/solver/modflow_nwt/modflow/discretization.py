# -*- coding: utf-8 -*-
"""
Temporal and spatial discretization builders for MODFLOW-NWT.

Purpose
-------
Centralize discretization logic outside the main ``Modflow`` orchestration
class so this step is:

- explicit (one module, one responsibility),
- testable (pure builder-style functions returning typed results),
- reusable (same contracts for other solver entry points).

Design boundary
---------------
This module transforms validated runtime/config inputs into normalized
discretization payloads. It does not instantiate FLOPY packages and does not
own simulation orchestration.

Main outputs
------------
- ``TemporalDiscretizationResult`` for DIS time arguments
  (``itmuni``, ``nper``, ``perlen``, ``nstp``, ``steady``, ``start_datetime``).
- ``SolverGridContext`` for structured grid geometry and solver-aligned
  top/bottom support.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.spatial.surface import Surface
from hydromodpy.solver.modflow_common import GridReference, SolverGridContext, SolverMesh
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import (
    PlanarGridConfig,
    SolverSGridConfig,
    VerticalGridConfig,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.solver.utils.temporal.tmesh_generation import TMesh_Generation
from hydromodpy.support.units import to_modflow_itmuni


@dataclass(slots=True)
class TemporalDiscretizationResult:
    """
    Typed temporal discretization container.

    Notes
    -----
    - ``perlen`` / ``nstp`` / ``steady`` are period-aligned vectors.
    - ``nper`` is derived from ``perlen`` size and must be > 0.
    - This container is solver-facing and ready to be converted to DIS kwargs.

    Attributes
    ----------
    itmuni : int
        MODFLOW DIS time-unit code used by FLOPY (for example 4=days).
    nper : int
        Number of stress periods. Must match ``perlen.size``.
    perlen : np.ndarray
        1D float array of stress-period lengths in ``itmuni`` units.
    nstp : np.ndarray
        1D int array of time-step counts for each stress period.
    steady : np.ndarray
        1D boolean array indicating steady-state (True) or transient (False)
        behavior per stress period.
    start_datetime : object | None
        Optional absolute simulation start datetime forwarded to DIS metadata.
        Does not change numerical period lengths.
    """

    itmuni: int
    nper: int
    perlen: np.ndarray
    nstp: np.ndarray
    steady: np.ndarray
    start_datetime: object | None

    def as_dis_kwargs(self) -> dict[str, object]:
        """
        Return the exact key/value mapping consumed by FLOPY ``ModflowDis``.

        Keeping this conversion here avoids scattering DIS key conventions
        across orchestration code.
        """
        return {
            "itmuni": self.itmuni,
            "nper": self.nper,
            "perlen": self.perlen,
            "nstp": self.nstp,
            "steady": self.steady,
            "start_datetime": self.start_datetime,
        }


def _coerce_itmuni(value: object, default_itmuni: int) -> int:
    """Convert temporal unit payload to MODFLOW ITMUNI integer code.

    Supported inputs
    ----------------
    - integer-like values (already ITMUNI codes),
    - textual labels: seconds/minutes/hours/days/years (and short aliases).
    """
    if value is None:
        return int(default_itmuni)
    text = str(value).strip()
    if text == "":
        return int(default_itmuni)
    try:
        return int(to_modflow_itmuni(value))
    except ValueError as exc:
        raise ValueError(
            f"Unsupported time_units value {value!r}. "
            "Expected ITMUNI code or unit label (seconds/minutes/hours/days/years)."
        ) from exc


def build_temporal_discretization_from_time_grid(
    *,
    time_grid: object,
    flow_regime: str,
    firstpersteady: bool,
) -> TemporalDiscretizationResult:
    """Build solver temporal arrays directly from canonical launcher time-grid."""
    if time_grid is None:
        raise ValueError(
            "preprocess_options.time_grid derived from [simulation.time] is required "
            "for launcher flow preprocessing."
        )

    perlen = np.asarray(getattr(time_grid, "period_lengths_seconds", ()), dtype=float)
    nper = int(perlen.size)
    if nper == 0:
        raise ValueError("simulation.time grid produced an empty perlen vector.")

    nstp = np.ones((nper,), dtype=int)
    flow_regime_text = str(flow_regime).strip().lower()
    if flow_regime_text == "steady":
        steady = np.ones((nper,), dtype=bool)
    else:
        steady = np.zeros((nper,), dtype=bool)
        if firstpersteady:
            steady[0] = True

    window = getattr(time_grid, "window", None)
    start_datetime = getattr(window, "start", None)
    if start_datetime is not None and hasattr(start_datetime, "to_pydatetime"):
        start_datetime = start_datetime.to_pydatetime()

    return TemporalDiscretizationResult(
        itmuni=1,  # seconds
        nper=nper,
        perlen=perlen,
        nstp=nstp,
        steady=steady,
        start_datetime=start_datetime,
    )


def resolve_domain_surfaces(
    *,
    domain: object,
) -> tuple[Surface, Surface]:
    """
    Validate and return top/substratum surfaces used by spatial gridding.

    Validation policy
    -----------------
    - both ``surface_topo`` and ``substratum`` must exist,
    - both must be ``Surface`` instances,
    - both arrays must share the same shape.
    """
    if domain is None:
        raise ValueError("Modflow spatial geometry is domain-only: a Domain object is required.")

    # Resolve required surfaces from the runtime domain contract.
    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None or substratum is None:
        raise ValueError(
            "Modflow spatial geometry is domain-only: domain.surface_topo "
            "and domain.substratum are required."
        )
    if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
        raise TypeError("Domain surfaces must be Surface instances.")

    # Validate geometry compatibility before grid construction.
    top = np.asarray(surface_topo.as_array(), dtype=float)
    bot = np.asarray(substratum.as_array(), dtype=float)
    if top.shape != bot.shape:
        raise ValueError(f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}.")

    # Ensure both surfaces are defined on the same geographic support.
    surface_topo.assert_same_geographic_domain(substratum)
    return surface_topo, substratum


def project_surfaces_to_planar_grid(
    *,
    top_surface: Surface,
    bottom_surface: Surface,
    planar_config: PlanarGridConfig | None,
    nodata: float,
) -> tuple[Surface, Surface]:
    """Project domain surfaces to the target solver planar grid when requested."""
    if planar_config is None or planar_config.mode == "keep_native":
        return top_surface, bottom_surface

    resampled_top = top_surface.resample_to_shape(
        int(planar_config.ny),
        int(planar_config.nx),
        resampling=str(planar_config.resampling),
        nodata=float(nodata),
        name=top_surface.name,
    )
    resampled_bottom = bottom_surface.resample_to_shape(
        int(planar_config.ny),
        int(planar_config.nx),
        resampling=str(planar_config.resampling),
        nodata=float(nodata),
        name=bottom_surface.name,
    )
    resampled_top.assert_same_geographic_domain(resampled_bottom)
    return resampled_top, resampled_bottom


def build_temporal_discretization(
    *,
    tgrid_config: object,
    flow_regime: str,
    default_itmuni: int,
) -> TemporalDiscretizationResult:
    """
    Build normalized temporal discretization from typed ``tgrid`` config.

    Parameters
    ----------
    tgrid_config : object
        Typed config exposing ``to_builder_kwargs()``.
    flow_regime : str
        Process regime selector (steady/transient) injected into builder args.
    default_itmuni : int
        Fallback time unit if builder result does not provide one.
    """
    # Bridge typed config -> runtime builder:
    # - `to_builder_kwargs()` exports validated config values as plain Python kwargs
    #   expected by `TMesh_Generation`.
    # - We then inject `flow_regime` here because it is runtime context owned by
    #   the process, not by the static tgrid configuration itself.
    # Example (synthetic_regular, simplified):
    # {"genmtd": "synthetic_regular", "nper": 12, "lenper": 1.0, "ntsp": 1, "tsmult": 1.0}
    # (`None` values are omitted by `to_builder_kwargs()`.)
    builder_kwargs = tgrid_config.to_builder_kwargs()
    builder_kwargs["flow_regime"] = flow_regime

    # Single construction point for temporal discretization generation.
    builder = TMesh_Generation(**builder_kwargs)
    tgrid = builder.run()

    # Normalize builder output to strict numpy-backed solver payloads.
    dis_itmuni = _coerce_itmuni(
        getattr(tgrid, "time_units", default_itmuni),
        default_itmuni,
    )
    dis_perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
    dis_nper = int(dis_perlen.size)
    dis_nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
    dis_steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
    dis_start_datetime = getattr(tgrid, "start_datetime", None)

    # Empty period vectors are invalid for MODFLOW DIS setup.
    if dis_nper == 0:
        raise ValueError("modflownwt.tgrid produced an empty perlen vector.")

    return TemporalDiscretizationResult(
        itmuni=dis_itmuni,
        nper=dis_nper,
        perlen=dis_perlen,
        nstp=dis_nstp,
        steady=dis_steady,
        start_datetime=dis_start_datetime,
    )


def build_spatial_discretization(
    *,
    domain: object,
    sgrid_config: SolverSGridConfig | None,
) -> SolverGridContext:
    """
    Build normalized structured spatial discretization from domain surfaces.

    Parameters
    ----------
    domain : object
        Runtime domain object exposing top/substratum surfaces.
    sgrid_config : SolverSGridConfig | None
        Solver-facing grid configuration split into planar and vertical
        discretization.
    """
    vertical_config: VerticalGridConfig | None = None
    planar_config: PlanarGridConfig | None = None
    if sgrid_config is not None:
        vertical_config = sgrid_config.vertical
        planar_config = sgrid_config.planar

    nodata = float(
        vertical_config.nodata
        if vertical_config is not None
        else -9999.0
    )

    # Validate and retrieve surfaces before invoking grid builder.
    top_surface, bottom_surface = resolve_domain_surfaces(
        domain=domain,
    )
    top_surface, bottom_surface = project_surfaces_to_planar_grid(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        planar_config=planar_config,
        nodata=nodata,
    )
    top = np.asarray(top_surface.as_array(), dtype=float)
    bottom = np.asarray(bottom_surface.as_array(), dtype=float)

    # Build full structured grid (top, botm, dimensions, spacing, offsets).
    sgrid = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=vertical_config,
    )
    zbot = np.asarray(sgrid.botm, dtype=float)
    inactive_mask = (
        ~np.isfinite(top)
        | ~np.isfinite(bottom)
        | (top <= nodata)
        | (bottom <= nodata)
    )

    solver_mesh = SolverMesh.from_sgrid(
        sgrid,
        zbot=zbot,
        inactive_mask=np.asarray(inactive_mask, dtype=bool),
    )
    return SolverGridContext(
        grid=GridReference.from_solver_mesh(
            solver_mesh,
            crs=None if top_surface.support is None else getattr(top_surface.support, "crs", None),
            nodata=nodata,
        ),
        solver_mesh=solver_mesh,
        top_surface=top_surface,
        bottom_surface=bottom_surface,
    )
