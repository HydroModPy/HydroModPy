"""Matching-stream diagnostics for flow postprocess."""

from __future__ import annotations

import os

import whitebox

from hydromodpy.tools import toolbox
from hydromodpy.watershed import Geographic, Hydrography, Workspace

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


class MatchingStreams:
    """Compute observed/simulated stream matching diagnostics."""

    def __init__(
        self,
        geographic: Geographic,
        hydrography: Hydrography,
        initializing: Workspace,
        iteration_label=None,
        from_calib: bool = True,
    ):
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

        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()

    def prepare_files(self):
        """Prepare working rasters and point layers used by WhiteboxTools."""

        self.results_folder = os.path.join(
            self.calibration_folder, self.iteration_label, "_postprocess"
        )
        toolbox.create_folder(self.results_folder)
        self.dichotomy_folder = os.path.join(
            self.calibration_folder, self.iteration_label, "_matchingstreams"
        )
        toolbox.create_folder(self.dichotomy_folder)

        self.buff_tif_obs = self.hydrography.tif_streams
        self.tif_obs = os.path.join(self.dichotomy_folder, "obs.tif")
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)

        self.pt_obs = os.path.join(self.dichotomy_folder, "obs_pt.shp")
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, "obs_ptf.shp")
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        self.obs_flow = os.path.join(self.dichotomy_folder, "obsflow.tif")
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)

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
        """Project simulated seepage streams onto observed stream distances."""

        self.pt_sim_flow = os.path.join(self.dichotomy_folder, "simflow.shp")
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, "simflowf.shp")
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)

        self.dist_dem_obs = os.path.join(self.dichotomy_folder, "dist_dem_obs.tif")
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)

        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, "dist_dem_obsflow.tif")
        wbt.downslope_distance_to_stream(
            self.watershed_fill, self.obs_flow, self.dist_dem_obsflow
        )

        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)

        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        """Project observed streams onto simulated stream distances."""

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
    """Run matching-stream diagnostics on one flow model output."""

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
