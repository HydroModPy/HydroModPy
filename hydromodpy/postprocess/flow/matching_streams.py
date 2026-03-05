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

import whitebox

from hydromodpy.tools import toolbox
from hydromodpy.simulation.workspace import Workspace
from hydromodpy.geographic.geographic import Geographic
from hydromodpy.watershed import Hydrography

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


class MatchingStreams:
    """Compute bidirectional stream-distance diagnostics.

    Parameters
    ----------
    geographic : Geographic
        Watershed spatial context (`watershed_shp`, `watershed_fill`,
        `watershed_direc` must be available).
    hydrography : Hydrography
        Hydrography context containing observed stream raster (`tif_streams`).
    initializing : Workspace
        Workspace-like object exposing `calibration_folder` and
        `simulations_folder`.
    iteration_label : str | None
        Simulation/calibration run folder name.
    from_calib : bool, default=True
        If True, read/write under calibration outputs; otherwise under
        simulation outputs.

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
        from_calib=False,
    )
    ```
    """

    def __init__(
        self,
        geographic: Geographic,
        hydrography: Hydrography,
        initializing: Workspace,
        iteration_label=None,
        from_calib: bool = True,
    ):
        """Run stream-matching diagnostics for one simulation iteration."""
        self.geographic = geographic
        self.hydrography = hydrography
        if from_calib is True:
            self.calibration_folder = initializing.calibration_folder
        else:
            self.calibration_folder = initializing.simulations_folder
        self.iteration_label = iteration_label

        self.watershed_shp = geographic.watershed_shp
        self.watershed_fill = geographic.watershed_fill
        self.watershed_direc = geographic.watershed_direc

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
            self.calibration_folder, self.iteration_label, "_postprocess"
        )
        toolbox.create_folder(self.results_folder)
        self.dichotomy_folder = os.path.join(
            self.calibration_folder, self.iteration_label, "_matchingstreams"
        )
        toolbox.create_folder(self.dichotomy_folder)

        # Observed stream support: hydrography raster -> watershed-clipped raster.
        self.buff_tif_obs = self.hydrography.tif_streams
        self.tif_obs = os.path.join(self.dichotomy_folder, "obs.tif")
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)

        # Convert observed stream pixels to points and trace their downslope paths.
        self.pt_obs = os.path.join(self.dichotomy_folder, "obs_pt.shp")
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, "obs_ptf.shp")
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        self.obs_flow = os.path.join(self.dichotomy_folder, "obsflow.tif")
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)

        # Simulated stream support comes from seepage raster at t(0).
        tif_sim = os.path.join(self.results_folder, "_rasters", "seepage_areas_t(0).tif")
        self.tif_sim = os.path.join(self.dichotomy_folder, "sim.tif")
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        self.pt_sim = os.path.join(self.dichotomy_folder, "sim_pt.shp")
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, "sim_ptf.shp")
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        self.sim_flow = os.path.join(self.dichotomy_folder, "simflow.tif")
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)

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

        self.pt_sim_flow = os.path.join(self.dichotomy_folder, "simflow.shp")
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, "simflowf.shp")
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)

        # Distance-to-observed-stream maps on filled DEM support.
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, "dist_dem_obs.tif")
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)

        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, "dist_dem_obsflow.tif")
        wbt.downslope_distance_to_stream(
            self.watershed_fill, self.obs_flow, self.dist_dem_obsflow
        )

        # Sample observed-distance rasters at simulated points and flowpath points.
        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)

        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        """Measure observed support against simulated-network distances.

        This is the reverse direction of :meth:`sim_to_obs` and helps diagnose
        asymmetry, e.g. "simulation misses observed channels" vs
        "simulation produces extra channels".
        """

        self.pt_obs_flow = os.path.join(self.dichotomy_folder, "obsflow.shp")
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, "obsflowf.shp")
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)

        self.dist_dem_sim = os.path.join(self.dichotomy_folder, "dist_dem_sim.tif")
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, "dist_dem_simflow.tif")
        wbt.downslope_distance_to_stream(
            self.watershed_fill, self.sim_flow, self.dist_dem_simflow
        )

        wbt.add_point_coordinates_to_table(self.pt_obs)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        wbt.add_point_coordinates_to_table(self.pt_obsf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)

        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)


def run_matching_streams(
    *,
    geographic,
    hydrography,
    workspace,
    iteration_label: str,
    from_calib: bool = False,
) -> None:
    """Run matching-stream diagnostics on one flow model output.

    Example
    -------
    ```python
    run_matching_streams(
        geographic=state.setup.geographic,
        hydrography=state.data.hydrography,
        workspace=state.setup.workspace,
        iteration_label="flow_main_modflownwt",
        from_calib=False,
    )
    ```
    """

    MatchingStreams(
        geographic,
        hydrography,
        workspace,
        iteration_label=iteration_label,
        from_calib=from_calib,
    )


__all__ = [
    "MatchingStreams",
    "run_matching_streams",
]
