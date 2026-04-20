"""Observed/simulated stream-network matching diagnostics.

This module builds bidirectional distance diagnostics between:

- observed stream evidence (hydrography raster),
- simulated seepage areas (flow postprocess raster).

The workflow relies on WhiteboxTools raster/hydrology primitives:

1. clip observed and simulated stream rasters to watershed extent,
2. convert stream pixels to points,
3. trace downslope flowpaths from those points on flow-direction raster,
4. compute downslope distance rasters to each stream family,
5. sample those distances at observed/simulated point supports.

Produced artifacts are written in one `_matchingstreams` working folder.
"""

from __future__ import annotations

import os

import numpy as np
import rasterio

from hydromodpy.spatial.delineation import get_whitebox_backend
from hydromodpy.core.tools import get_logger
from hydromodpy.core.tools.filesystem import create_folder
from hydromodpy.core.tools.raster_io import load_to_numpy, clip_tif
from hydromodpy.core.workspace import Workspace
from hydromodpy.spatial.geographic.geographic import Geographic
from hydromodpy.data.variables.hydrography.result import HydrographyResult


logger = get_logger(__name__)


def _raster_has_active_support(raster_path: str) -> bool:
    """Return ``True`` when a raster contains at least one non-zero valid cell."""

    with rasterio.open(raster_path) as src:
        data = np.ma.masked_invalid(src.read(1, masked=True))
    return bool(np.any(data.filled(0.0) != 0.0))


class MatchingStreams:
    """Compute bidirectional stream-distance diagnostics.

    Parameters
    ----------
    geographic : Geographic
        Watershed spatial context (`watershed_shp`, `watershed_fill`,
        `watershed_direc` must be available).
    hydrography : HydrographyResult
        HydrographyResult context containing observed stream raster (`tif_streams`).
    initializing : Workspace
        Workspace-like object exposing `calibration_folder` and
        `simulations_folder`.
    model_modflow : object | None
        Optional prepared flow model. When provided, routing rasters and the
        raster support come from the solver grid instead of the geographic DEM.
    iteration_label : str | None
        Simulation/calibration run folder name.

    Notes
    -----
    The constructor executes the full workflow immediately:
    `prepare_files() -> sim_to_obs() -> obs_to_sim()`.

    Example
    -------
    ```python
    MatchingStreams(
        geographic=geo,
        hydrography=hydro,
        initializing=workspace,
        iteration_label="flow_main_modflownwt",
    )
    ```
    """

    def __init__(
        self,
        geographic: Geographic,
        hydrography: HydrographyResult,
        initializing: Workspace,
        model_modflow: object | None = None,
        iteration_label=None,
    ):
        """Run stream-matching diagnostics for one simulation iteration."""
        self.geographic = geographic
        self.hydrography = hydrography
        self.model_modflow = model_modflow
        self.output_folder = str(
            getattr(initializing, "solver_scratch_folder", None)
            or initializing.project_root
        )
        self.iteration_label = iteration_label

        self.watershed_shp = geographic.watershed_shp
        self.base_dem = getattr(geographic, "watershed_dem", None)
        self.watershed_fill = getattr(geographic, "watershed_fill", None)
        self.watershed_direc = getattr(geographic, "watershed_direc", None)
        if self.model_modflow is not None:
            self.base_dem = getattr(self.model_modflow, "dem_watershed_path", self.base_dem)
            if hasattr(self.model_modflow, "_ensure_solver_routing_context"):
                routing_ctx = self.model_modflow._ensure_solver_routing_context()
                self.watershed_fill = routing_ctx.correc_path
                self.watershed_direc = routing_ctx.direc_path
        if self.base_dem is None or self.watershed_fill is None or self.watershed_direc is None:
            raise ValueError(
                "MatchingStreams requires base DEM, routing fill, and routing "
                "direction rasters."
            )
        self._backend = get_whitebox_backend()
        self.has_observed_support = False
        self.has_simulated_support = False

        # Full execution pipeline (kept eager for backward compatibility).
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()

    def prepare_files(self):
        """Prepare clipped rasters and seed point layers.

        Outputs created in `<...>/_matchingstreams/` include:
        - `obs.tif`, `sim.tif`: clipped observed/simulated stream rasters,
        - `obs_pt*.shp`, `sim_pt*.shp`: point seeds from stream pixels,
        - `obsflow.tif`, `simflow.tif`: traced downslope flowpaths.

        Example output layout (for `iteration_label="run_01"`):
        `<calibration_folder>/run_01/_matchingstreams/obs.tif`
        """

        self.results_folder = os.path.join(
            self.output_folder, self.iteration_label, "_postprocess"
        )
        create_folder(self.results_folder)
        self.dichotomy_folder = os.path.join(
            self.output_folder, self.iteration_label, "_matchingstreams"
        )
        create_folder(self.dichotomy_folder)

        # Observed stream support: hydrography raster -> watershed-clipped raster.
        self.buff_tif_obs = self.hydrography.tif_streams
        self.tif_obs = os.path.join(self.dichotomy_folder, "obs.tif")
        if self.model_modflow is not None:
            obs_aligned = os.path.join(self.dichotomy_folder, "_obs_base.tif")
            load_to_numpy(
                self.buff_tif_obs,
                base_path=self.base_dem,
                out_path=obs_aligned,
            )
            clip_tif(obs_aligned, self.watershed_shp, self.tif_obs, True)
        else:
            clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)

        # Convert observed stream pixels to points and trace their downslope paths.
        self.pt_obs = os.path.join(self.dichotomy_folder, "obs_pt.shp")
        self.pt_obsf = os.path.join(self.dichotomy_folder, "obs_ptf.shp")
        self.obs_flow = os.path.join(self.dichotomy_folder, "obsflow.tif")
        self.has_observed_support = _raster_has_active_support(self.tif_obs)
        if self.has_observed_support:
            self._backend.raster_to_vector_points(self.tif_obs, self.pt_obs)
            self._backend.raster_to_vector_points(self.tif_obs, self.pt_obsf)
            self._backend.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        else:
            logger.warning(
                "MatchingStreams found no observed stream pixels after clipping; "
                "diagnostics using observed support will be skipped."
            )

        # Simulated stream support comes from seepage raster at t(0).
        tif_sim = os.path.join(self.results_folder, "_rasters", "seepage_areas_t(0).tif")
        self.tif_sim = os.path.join(self.dichotomy_folder, "sim.tif")
        self.pt_sim = os.path.join(self.dichotomy_folder, "sim_pt.shp")
        self.pt_simf = os.path.join(self.dichotomy_folder, "sim_ptf.shp")
        self.sim_flow = os.path.join(self.dichotomy_folder, "simflow.tif")
        if not os.path.isfile(tif_sim):
            logger.warning(
                "Seepage raster %s not found — simulated support unavailable. "
                "Matching-stream diagnostics will be partial.",
                tif_sim,
            )
            self.has_simulated_support = False
        else:
            clip_tif(
                tif_sim,
                self.watershed_shp,
                self.tif_sim,
                bool(self.model_modflow is not None),
            )
            self.has_simulated_support = _raster_has_active_support(self.tif_sim)
        if self.has_simulated_support:
            self._backend.raster_to_vector_points(self.tif_sim, self.pt_sim)
            self._backend.raster_to_vector_points(self.tif_sim, self.pt_simf)
            self._backend.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
        else:
            logger.warning(
                "MatchingStreams found no simulated stream pixels after clipping; "
                "diagnostics using simulated support will be skipped."
            )

    def sim_to_obs(self):
        """Measure simulated support against observed-network distances.

        Conceptually:
        - build distance-to-observed rasters (`dist_dem_obs*`),
        - sample those rasters at simulated points (`sim_pt*`, `simflow*`).

        Illustration
        ------------
        If a sampled value is `0`, the simulated point is already on observed
        network support. Larger values indicate farther downslope mismatch.
        """
        if not self.has_simulated_support:
            logger.warning(
                "Skipping MatchingStreams simulated-to-observed diagnostics "
                "because simulated support is empty."
            )
            return
        if not self.has_observed_support:
            logger.warning(
                "Skipping MatchingStreams simulated-to-observed diagnostics "
                "because observed support is empty."
            )
            return

        self.pt_sim_flow = os.path.join(self.dichotomy_folder, "simflow.shp")
        self._backend.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, "simflowf.shp")
        self._backend.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)

        # Distance-to-observed-stream maps on filled DEM support.
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, "dist_dem_obs.tif")
        self._backend.downslope_distance_to_stream(
            self.watershed_fill,
            self.tif_obs,
            self.dist_dem_obs,
        )

        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, "dist_dem_obsflow.tif")
        self._backend.downslope_distance_to_stream(
            self.watershed_fill, self.obs_flow, self.dist_dem_obsflow
        )

        # Sample observed-distance rasters at simulated points and flowpath points.
        self._backend.add_point_coordinates_to_table(self.pt_sim)
        self._backend.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        self._backend.add_point_coordinates_to_table(self.pt_simf)
        self._backend.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)

        self._backend.add_point_coordinates_to_table(self.pt_sim_flow)
        self._backend.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        self._backend.add_point_coordinates_to_table(self.pt_sim_flowf)
        self._backend.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        """Measure observed support against simulated-network distances.

        This is the reverse direction of :meth:`sim_to_obs` and helps diagnose
        asymmetry, e.g. "simulation misses observed channels" vs
        "simulation produces extra channels".
        """
        if not self.has_observed_support:
            logger.warning(
                "Skipping MatchingStreams observed-to-simulated diagnostics "
                "because observed support is empty."
            )
            return
        if not self.has_simulated_support:
            logger.warning(
                "Skipping MatchingStreams observed-to-simulated diagnostics "
                "because simulated support is empty."
            )
            return

        self.pt_obs_flow = os.path.join(self.dichotomy_folder, "obsflow.shp")
        self._backend.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, "obsflowf.shp")
        self._backend.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)

        self.dist_dem_sim = os.path.join(self.dichotomy_folder, "dist_dem_sim.tif")
        self._backend.downslope_distance_to_stream(
            self.watershed_fill,
            self.tif_sim,
            self.dist_dem_sim,
        )
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, "dist_dem_simflow.tif")
        self._backend.downslope_distance_to_stream(
            self.watershed_fill, self.sim_flow, self.dist_dem_simflow
        )

        self._backend.add_point_coordinates_to_table(self.pt_obs)
        self._backend.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        self._backend.add_point_coordinates_to_table(self.pt_obsf)
        self._backend.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)

        self._backend.add_point_coordinates_to_table(self.pt_obs_flow)
        self._backend.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        self._backend.add_point_coordinates_to_table(self.pt_obs_flowf)
        self._backend.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)


def run_matching_streams(
    *,
    geographic,
    hydrography,
    workspace,
    model_modflow: object | None = None,
    iteration_label: str,
) -> None:
    """Run matching-stream diagnostics on one flow model output."""

    MatchingStreams(
        geographic,
        hydrography,
        workspace,
        model_modflow=model_modflow,
        iteration_label=iteration_label,
    )


__all__ = [
    "MatchingStreams",
    "run_matching_streams",
]
