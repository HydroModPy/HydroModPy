from __future__ import annotations

import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from hydromodpy.results.catalog import Catalog
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)


def _line_gdf(length_m: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (float(length_m), 0.0)])],
        crs="EPSG:2154",
    )


def _write_simulation_config(path: Path, workspace_root: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                f'root = "{workspace_root.as_posix()}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _register_completed_run(
    workspace_root: Path,
    *,
    reference_length_m: float | None,
    generated_length_m: float | None,
    reference_gdf: gpd.GeoDataFrame | None = None,
    accumulation_flux: list[np.ndarray] | None = None,
    release_flux: list[np.ndarray] | None = None,
    flow_regime: str = "transient",
) -> tuple[Path, str]:
    config_path = workspace_root.parent / f"run_{uuid.uuid4().hex[:8]}.toml"
    _write_simulation_config(config_path, workspace_root)

    catalog = Catalog(workspace_root)
    sim_id = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sim_id,
        project="demo_compare",
        solver="modflow6",
        name="network_demo",
        n_cells=3 if accumulation_flux is not None or release_flux is not None else 2,
        n_layers=1,
        n_timesteps=(
            len(accumulation_flux)
            if accumulation_flux is not None
            else len(release_flux)
            if release_flux is not None
            else None
        ),
        flow_regime=flow_regime,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    if accumulation_flux is not None or release_flux is not None:
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [3.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [3.0, 1.0, 0.0],
            ],
            dtype="float64",
        )
        face_node_connectivity = np.array(
            [
                [0, 1, 5, 4],
                [1, 2, 6, 5],
                [2, 3, 7, 6],
            ],
            dtype="int32",
        )
        catalog.write_mesh(
            sim_id,
            vertices,
            face_node_connectivity,
            np.array([10.0, 9.0, 8.0], dtype="float64"),
        )
        sz = catalog.open_zarr(sim_id)
        try:
            sz.root["mesh"].create_array(
                "topography",
                data=np.array([10.0, 9.0, 8.0], dtype="float64"),
                overwrite=True,
            )
        finally:
            sz.close()
        if accumulation_flux is not None:
            for timestep, values in enumerate(accumulation_flux):
                catalog.write_field(
                    sim_id,
                    "accumulation_flux",
                    timestep,
                    values,
                    n_timesteps=len(accumulation_flux) if timestep == 0 else None,
                    subgroup="derived",
                )
        if release_flux is not None:
            for timestep, values in enumerate(release_flux):
                catalog.write_field(
                    sim_id,
                    "release_flux",
                    timestep,
                    values,
                    n_timesteps=len(release_flux) if timestep == 0 else None,
                    subgroup="derived",
                )
    if reference_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            _line_gdf(reference_length_m),
        )
    if reference_gdf is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            reference_gdf,
        )
    if generated_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
            _line_gdf(generated_length_m),
        )
    catalog.finalize(sim_id, "completed", 1.0)
    catalog.close()
    return config_path, sim_id


def _register_completed_active_network_run(workspace_root: Path) -> tuple[Path, str]:
    config_path = workspace_root.parent / f"run_{uuid.uuid4().hex[:8]}.toml"
    _write_simulation_config(config_path, workspace_root)

    catalog = Catalog(workspace_root)
    sim_id = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sim_id,
        project="demo_compare",
        solver="modflow6",
        name="active_network_demo",
        n_cells=3,
        n_layers=1,
        n_timesteps=2,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
            [3.0, 1.0, 0.0],
        ],
        dtype="float64",
    )
    face_node_connectivity = np.array(
        [
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
        ],
        dtype="int32",
    )
    catalog.write_mesh(
        sim_id,
        vertices,
        face_node_connectivity,
        np.array([10.0, 9.0, 8.0], dtype="float64"),
    )
    sz = catalog.open_zarr(sim_id)
    try:
        sz.root["mesh"].create_array(
            "topography",
            data=np.array([10.0, 9.0, 8.0], dtype="float64"),
            overwrite=True,
        )
    finally:
        sz.close()
    catalog.write_field(
        sim_id,
        "accumulation_flux",
        0,
        np.array([0.0, 1.0, 0.0], dtype="float64"),
        n_timesteps=2,
        subgroup="derived",
    )
    catalog.write_field(
        sim_id,
        "accumulation_flux",
        1,
        np.array([0.0, 1.0, 0.0], dtype="float64"),
        subgroup="derived",
    )
    catalog.write_geographic_feature(
        sim_id,
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.25, 0.5), (1.75, 0.5)])],
            crs="EPSG:2154",
        ),
    )
    catalog.finalize(sim_id, "completed", 1.0)
    catalog.close()
    return config_path, sim_id
