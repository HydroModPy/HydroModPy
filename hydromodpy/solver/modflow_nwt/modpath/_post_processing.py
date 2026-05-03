"""Post-processing helpers writing MODPATH shapefile outputs."""

from __future__ import annotations

import io
import json
import os
import random
import warnings
from contextlib import redirect_stdout
from typing import Any

import flopy
import geopandas as gpd

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger

from ._resolvers import crs_for_write_from_proj

logger = get_logger(__name__)


def write_shapefiles(
    *,
    model_modpath: Any,
    starting_point: bool,
    ending_point: bool,
    pathlines_shp: bool,
    particles_shp: bool,
    random_id: int | None,
) -> tuple[str, str]:
    """Write MODPATH shapefile outputs and return ``(full_path, particles_file)``."""
    full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)
    particles_file = os.path.join(full_path, "_postprocess", "_particles")
    create_folder(particles_file)

    grid_model = model_modpath.mf.modelgrid
    crs = model_modpath._get_crs_proj()
    crs_for_write, _ = crs_for_write_from_proj(crs)

    path_mpend = os.path.join(
        model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name
    )
    endobj = flopy.utils.EndpointFile(path_mpend + ".mpend")
    e = endobj.get_alldata()

    if ending_point:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
            endobj.write_shapefile(
                endpoint_data=e,
                shpname=os.path.join(particles_file, "ending.shp"),
                direction="ending",
                mg=grid_model,
                crs=crs_for_write,
            )

    if starting_point:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
            endobj.write_shapefile(
                endpoint_data=e,
                shpname=os.path.join(particles_file, "starting.shp"),
                direction="starting",
                mg=grid_model,
                crs=crs_for_write,
            )

    if pathlines_shp or particles_shp:
        path_mppth = os.path.join(
            model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name
        )
        pthobj = flopy.utils.PathlineFile(path_mppth + ".mppth")
        pth_data = pthobj.get_alldata()
        pth_data_save = _maybe_subsample_pathlines(
            pth_data,
            particles_file=particles_file,
            random_id=random_id,
        )

        if pathlines_shp:
            with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
                warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                pthobj.write_shapefile(
                    pathline_data=pth_data_save,
                    shpname=os.path.join(particles_file, "pathlines.shp"),
                    one_per_particle=True,
                    direction="ending",
                    mg=grid_model,
                    crs=crs_for_write,
                    verbose=False,
                )

        if particles_shp:
            with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
                warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                pthobj.write_shapefile(
                    pathline_data=pth_data_save,
                    shpname=os.path.join(particles_file, "particles.shp"),
                    one_per_particle=False,
                    direction="ending",
                    mg=grid_model,
                    crs=crs_for_write,
                    verbose=False,
                )

    return full_path, particles_file


def _maybe_subsample_pathlines(
    pth_data,
    *,
    particles_file: str,
    random_id: int | None,
):
    """Subset pathlines to a random sample of particle ids when requested."""
    if random_id is None:
        return pth_data

    shp_endpoint = gpd.read_file(os.path.join(particles_file, "ending.shp"))
    keep_id = shp_endpoint.particleid.tolist()
    id_random_particles = random.sample(keep_id[:-1], random_id)
    with open(particles_file + "/_random_id.json", "w") as f:
        json.dump([int(x) for x in id_random_particles], f)

    pth_data_save = []
    for index, particle_id in enumerate(id_random_particles):
        logger.debug(
            "Processing random particle %d/%d (id: %s)",
            index,
            len(id_random_particles),
            particle_id,
        )
        for pth in pth_data:
            if particle_id == pth.particleid[0]:
                pth_data_save.append(pth)
    return pth_data_save
