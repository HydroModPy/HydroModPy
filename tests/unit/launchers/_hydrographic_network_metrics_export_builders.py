"""Sealed, indexed runs whose Run view the network exports of a comparison read.

The network metrics read a run through ``Run``, which the comparison opens
from the index of the project holding the run
(:func:`hydromodpy.analysis.comparison.runtime.run_source.open_indexed_run`,
from the ``run_dir`` of a simulation summary). Each builder writes its run the
way the pipeline does, through the store of a claimed run directory, seals it
and indexes the project. :func:`serve_indexed_runs` lets the summaries of the
tests name their run by ``config_path``: it hands the real opener the run
directory the builder wrote.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.analysis.comparison.runtime import run_source
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import index_new_runs
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)
from tests._helpers.run_stores import open_run_store

_RUN_DIRS: dict[str, Path] = {}

_VERTICES = np.array(
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
_FACES = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype="int32")
_TOPOGRAPHY = np.array([10.0, 9.0, 8.0], dtype="float64")


def serve_indexed_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the Run view of each summary through the real opener, by its run directory."""
    opener = run_source.open_indexed_run

    def open_indexed_run(summary: Mapping[str, Any]) -> tuple[Catalog | None, str | None]:
        run_dir = _RUN_DIRS.get(str(summary.get("config_path", "")))
        if run_dir is None:
            return None, None
        return opener({**summary, "run_dir": str(run_dir)})

    monkeypatch.setattr(run_source, "open_indexed_run", open_indexed_run)


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


def _write_mesh(store: RunStore) -> None:
    """Write the three-cell strip and its topography, in the frame of the network features."""
    sim_id = store.sim_id
    store.write_mesh(sim_id, _VERTICES, _FACES, _TOPOGRAPHY)
    # Network metrics overlay the mesh and the features and refuse to guess the frame.
    store.write_geographic_metadata(sim_id, {"crs_proj": "EPSG:2154"})
    sz = store.open_zarr(sim_id)
    try:
        sz.root["mesh"].create_array("topography", data=_TOPOGRAPHY, overwrite=True)
    finally:
        sz.close()


def _write_stack(store: RunStore, variable: str, stack: list[np.ndarray]) -> None:
    for timestep, values in enumerate(stack):
        store.write_field(
            store.sim_id,
            variable,
            timestep,
            values,
            n_timesteps=len(stack) if timestep == 0 else None,
            subgroup="derived",
        )


def _seal_and_index(store: RunStore, workspace_root: Path) -> tuple[Path, str]:
    """Seal the run, index the project; return the config the summary names and the run id."""
    config_path = workspace_root.parent / f"run_{uuid.uuid4().hex[:8]}.toml"
    _write_simulation_config(config_path, workspace_root)
    sim_id, run_dir = store.sim_id, store.run_dir
    seal_completed(store)
    index_new_runs(workspace_root)
    _RUN_DIRS[str(config_path)] = run_dir
    return config_path, sim_id


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
    stack = accumulation_flux if accumulation_flux is not None else release_flux
    store = open_run_store(
        workspace_root,
        f"network_demo_{uuid.uuid4().hex[:8]}",
        n_cells=3 if stack is not None else 2,
        n_layers=1,
        n_timesteps=None if stack is None else len(stack),
        flow_regime=flow_regime,
    )
    sim_id = store.sim_id
    if stack is not None:
        _write_mesh(store)
    if accumulation_flux is not None:
        _write_stack(store, "accumulation_flux", accumulation_flux)
    if release_flux is not None:
        _write_stack(store, "release_flux", release_flux)
    if reference_length_m is not None:
        store.write_geographic_feature(
            sim_id, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, _line_gdf(reference_length_m)
        )
    if reference_gdf is not None:
        store.write_geographic_feature(
            sim_id, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference_gdf
        )
    if generated_length_m is not None:
        store.write_geographic_feature(
            sim_id, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, _line_gdf(generated_length_m)
        )
    return _seal_and_index(store, workspace_root)


def _register_completed_active_network_run(workspace_root: Path) -> tuple[Path, str]:
    store = open_run_store(
        workspace_root,
        f"active_network_demo_{uuid.uuid4().hex[:8]}",
        n_cells=3,
        n_layers=1,
        n_timesteps=2,
    )
    _write_mesh(store)
    _write_stack(
        store,
        "accumulation_flux",
        [np.array([0.0, 1.0, 0.0], dtype="float64"), np.array([0.0, 1.0, 0.0], dtype="float64")],
    )
    store.write_geographic_feature(
        store.sim_id,
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.25, 0.5), (1.75, 0.5)])],
            crs="EPSG:2154",
        ),
    )
    return _seal_and_index(store, workspace_root)
