"""Each backend declares in ``writes`` what its run leaves in the store.

The island is played under MODFLOW 6 on a regular and on a Voronoi mesh, under
MODFLOW-NWT and Boussinesq, and under MODFLOW 6 with a GWT transport. Each run
store is then opened, and every array of ``fields.zarr`` and every table of
``tables.parquet`` that the pipeline does not write itself must match a name or
a pattern of ``writes`` of a backend of the run.

The extract step already refuses a name a backend adds outside its ``writes``
(``hydromodpy/results/storage/declared.py``, which also holds the names the
pipeline writes itself), so a run that ends with code 0 kept its declaration.
This file holds the whole store against the backends of the run, and holds that
each flow backend writes ``head``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, TABLES_DIRNAME
from hydromodpy.results.storage.declared import (
    PIPELINE_ARRAYS,
    PIPELINE_PREFIXES,
    PIPELINE_TABLE_PREFIXES,
    PIPELINE_TABLES,
    pattern_regex,
    stored_arrays,
    stored_tables,
)
from hydromodpy.solver.base.registry import solvers
from tests.scenarios.factory import (
    TRANSPORT_PARAMETERS,
    TRANSPORT_PROCESS,
    TRIANGLE_MESH,
    basin_files,
    transient_island,
)
from tests.scenarios.launcher import Scenario, play

MF6_FILES = ("mf6", "libmf6.so")

VORONOI_MESH = """
[mesh]
engine = "voronoi"
cell_size = 30.0
"""

ISLANDS = {
    "writes_modflow6": (transient_island("writes_modflow6", "modflow6"), MF6_FILES),
    "writes_voronoi": (
        transient_island("writes_voronoi", "modflow6", mesh=VORONOI_MESH),
        MF6_FILES,
    ),
    "writes_nwt": (transient_island("writes_nwt", "modflow_nwt"), (*MF6_FILES, "mfnwt")),
    "writes_boussinesq": (
        transient_island("writes_boussinesq", "boussinesq", mesh=TRIANGLE_MESH),
        MF6_FILES,
    ),
    "writes_gwt": (
        transient_island(
            "writes_gwt", "modflow6", process=TRANSPORT_PROCESS, tail=TRANSPORT_PARAMETERS
        ),
        MF6_FILES,
    ),
}


def run_backends(run_dir: Path) -> list[tuple[str, str]]:
    """Return the ``(process_type, name)`` pairs of the processes a run played."""
    config = tomllib.loads((run_dir / "config.resolved.toml").read_text(encoding="utf-8"))
    return [
        (process["kind"], solver)
        for process in config["simulation"]["process"]
        for solver in process["solvers"]
    ]


def undeclared_names(run_dir: Path, *, hold_a_head: bool = True) -> list[str]:
    """Return what a run stored outside the pipeline and outside ``writes`` of its backends."""
    backends = run_backends(run_dir)
    patterns = [
        pattern_regex(pattern) for pair in backends for pattern in solvers.get(*pair).writes
    ]
    arrays = [
        name
        for name in stored_arrays(run_dir / FIELDS_STORE_NAME)
        if not name.startswith(PIPELINE_PREFIXES) and name not in PIPELINE_ARRAYS
    ]
    tables = [
        name
        for name in stored_tables(run_dir / TABLES_DIRNAME)
        if name not in PIPELINE_TABLES and not name.startswith(PIPELINE_TABLE_PREFIXES)
    ]
    faults = [
        f"{kind} {name} is in no writes of {backends}"
        for kind, names in (("array", arrays), ("table", tables))
        for name in names
        if not any(regex.match(name) for regex in patterns)
    ]
    if hold_a_head and any(kind == "flow" for kind, _ in backends) and "head" not in arrays:
        faults.append(f"the flow of {backends} left no head array")
    return faults


@pytest.mark.parametrize("variant", sorted(ISLANDS))
def test_a_run_stores_only_what_its_backends_declare(
    variant: str, tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    text, needs = ISLANDS[variant]
    scenario = Scenario(
        name=variant,
        covers="the store of a run against the writes of the backends it played",
        files={"project.toml": text},
        argv=("run", "project.toml"),
        needs=needs,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = [played.root / path for kind, path in played.targets if kind == "run"]
    assert len(runs) == 1
    assert undeclared_names(runs[0]) == []


def test_the_basin_stores_only_what_its_backend_declares(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """The global backend of the basin declares the series it leaves, and no head.

    A global model carries no aquifer, so no head array exists: the hold on a
    flow backend would be wrong for it. Every other name of the store comes
    from the pipeline prefix, the same names any run carries.
    """
    scenario = Scenario(
        name="writes_basin",
        covers="the store of a global run against the writes of its one backend",
        files=basin_files(),
        argv=("run", "project.toml"),
        needs=(),
        timeout_s=300.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = [played.root / path for kind, path in played.targets if kind == "run"]
    assert len(runs) == 1
    # The rule of the store is the one of the islands, without the head: a
    # global model writes none, and its series carries the whole catchment.
    assert undeclared_names(runs[0], hold_a_head=False) == []
    tables = stored_tables(runs[0] / TABLES_DIRNAME)
    assert "timeseries" in tables
