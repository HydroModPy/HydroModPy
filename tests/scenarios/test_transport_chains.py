"""Transport chains, played through the real pipeline on the island.

Each scenario plays the three-month island of ``factory.py`` with a transport
process behind its flow: the GWT island of the references, MODFLOW-NWT with
MT3DMS, MODFLOW 6 with PRT, and MODFLOW-NWT with MODPATH. The fifth releases
the MODPATH particles from the seepage areas of the flow run. A scenario keeps
its solver files, so the files the flow leaves to its transport stay on disk:
the link file of MT3DMS, the head and budget files MODPATH reads, and the
seepage raster.

Each chain checks that the run closes, that the concentration or the particle
tracks reach the run store under a name the transport declares in ``writes``,
and that nothing a backend did not declare is stored beside them. The link
file of MT3DMS and the seepage raster are checked on their own scenario.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import numpy as np
import pytest
import rasterio
import zarr

from hydromodpy.results.derive.virtual_fields import seepage_mask_rows
from tests.scenarios.factory import (
    TRANSPORT_VARIANTS,
    island_files,
    transport_variant_files,
    tree_digest,
    write_project,
)
from tests.scenarios.launcher import Scenario, play
from tests.scenarios.test_backends_write_what_they_declare import (
    MF6_FILES,
    stored_arrays,
    undeclared_names,
)

SEEPAGE_VARIANT = "nwt_modpath_seepage_clip"

SOLVER_OF = {
    "nwt_mt3dms": "mt3dms",
    "mf6_prt": "modflow6_prt",
    "nwt_modpath": "modpath",
    SEEPAGE_VARIANT: "modpath",
}

# The transport output a chain must find in its run store, and the binary and
# library files its solvers need. The concentration is stored under the
# species its parameters name; the particle tracking stores the two track
# arrays and their dates.
TRANSPORT_OUTPUTS: dict[str, tuple[str, ...]] = {
    "gwt": ("concentration/NO3",),
    "nwt_mt3dms": ("concentration/NO3",),
    "mf6_prt": ("particles/x", "particles/y", "particles/z", "particles/time"),
    "nwt_modpath": ("particles/x", "particles/y", "particles/z", "particles/time"),
}

CHAIN_NEEDS: dict[str, tuple[str, ...]] = {
    "gwt": MF6_FILES,
    "nwt_mt3dms": (*MF6_FILES, "mfnwt", "mt3dusgs"),
    "mf6_prt": MF6_FILES,
    "nwt_modpath": (*MF6_FILES, "mfnwt", "mp6"),
    SEEPAGE_VARIANT: (*MF6_FILES, "mfnwt", "mp6"),
}


def _files_of(variant: str) -> dict[str, str]:
    """Return the project files of one transport chain, and its solver names."""
    if variant == "gwt":
        return island_files(variant)
    return transport_variant_files(variant)


def _runs(played) -> list[Path]:
    """Return the run folders a played scenario left, as absolute paths."""
    return [played.root / path for kind, path in played.targets if kind == "run"]


@pytest.mark.fast
def test_the_factory_writes_each_transport_variant_the_same_way_twice(tmp_path: Path) -> None:
    for variant in (*TRANSPORT_VARIANTS, SEEPAGE_VARIANT):
        first = write_project(tmp_path / "a" / variant, transport_variant_files(variant))
        second = write_project(tmp_path / "b" / variant, transport_variant_files(variant))
        assert tree_digest(first) == tree_digest(second)
    with pytest.raises(KeyError):
        transport_variant_files("lake")


@pytest.mark.fast
def test_each_transport_variant_declares_its_flow_family() -> None:
    for variant in (*TRANSPORT_VARIANTS, SEEPAGE_VARIANT):
        doc = tomllib.loads(transport_variant_files(variant)["project.toml"])
        processes = doc["simulation"]["process"]
        assert [process["kind"] for process in processes] == ["flow", "transport"]
        family = {"mt3dms": "modflow_nwt", "modflow6_prt": "modflow6", "modpath": "modflow_nwt"}
        (solver,) = processes[1]["solvers"]
        assert solver == SOLVER_OF[variant]
        assert processes[0]["solvers"] == [family[solver]]


@pytest.mark.parametrize("variant", sorted(TRANSPORT_OUTPUTS))
def test_a_transport_chain_stores_what_its_transport_declares(
    variant: str, tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    scenario = Scenario(
        name=variant,
        covers=f"the {variant} chain, a transport run behind the flow solver it requires",
        files=_files_of(variant),
        argv=("run", "project.toml"),
        needs=CHAIN_NEEDS[variant],
        expected_s=30.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert len(runs) == 1
    arrays = stored_arrays(runs[0] / "fields.zarr")
    for output in TRANSPORT_OUTPUTS[variant]:
        assert output in arrays, f"{arrays} holds no {output}"
    assert undeclared_names(runs[0]) == []


def test_the_mt3dms_chain_leaves_the_flow_link_file_in_the_flow_folder(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    scenario = Scenario(
        name="nwt_mt3dms",
        covers="the flow-transport link file MODFLOW-NWT writes for a transport that follows it",
        files=transport_variant_files("nwt_mt3dms"),
        argv=("run", "project.toml"),
        needs=CHAIN_NEEDS["nwt_mt3dms"],
        expected_s=30.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert len(runs) == 1
    links = sorted(runs[0].rglob("mt3d_link.ftl"))
    assert len(links) == 1, f"the flow run left {links} as its flow-transport link file"


def test_the_seepage_raster_matches_the_mask_the_store_derives(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    scenario = Scenario(
        name=SEEPAGE_VARIANT,
        covers=(
            "MODPATH particles released from the seepage areas, with a raster built "
            "from the heads of the flow run"
        ),
        files=transport_variant_files(SEEPAGE_VARIANT),
        argv=("run", "project.toml"),
        needs=CHAIN_NEEDS[SEEPAGE_VARIANT],
        expected_s=60.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert len(runs) == 1
    run_dir = runs[0]
    rasters = sorted(run_dir.rglob("seepage_areas_t(0).tif"))
    assert len(rasters) == 1, f"the flow run left {rasters} as its seepage raster"
    root = zarr.open(str(run_dir / "fields.zarr"), mode="r")
    stored = np.asarray(seepage_mask_rows(root, 0, 1)[0], dtype="float64")
    with rasterio.open(rasters[0]) as source:
        values = np.asarray(source.read(1), dtype="float64")
        if source.nodata is not None:
            values = np.where(values == source.nodata, np.nan, values)
    np.testing.assert_allclose(
        values, stored.reshape(values.shape), rtol=0.0, atol=0.0, equal_nan=True
    )
