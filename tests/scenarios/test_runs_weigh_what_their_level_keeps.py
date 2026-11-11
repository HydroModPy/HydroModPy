"""A hundred runs weigh a hundred times one, and a kept trial keeps less.

Four worker processes play twenty-five island runs each, every run on its own K,
in a project of its own and in the scratch folder of its own run. A fifth
worker plays the ``levels`` project: the same steady island at the result level,
the same island without its per-cell budget terms, the same island with the
flow between each pair of cells, and then the calibration. The weights are read
after the pool of processes is closed, so the scratch of a run whose process is
gone is what ``gc`` measures.

The scenario holds seven rules of the 4.16 lot: the run level decides what a run
keeps, a lighter run weighs what it drops, the face flows cost one value per
connection at each stamp, a kept calibration trial is a research run, and ``gc``
measures a project and frees exactly what its plan says.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pytest

from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.results.record.manifest import read_seal, seal_problems
from hydromodpy.results.retention import run_weight
from tests.scenarios.factory import island_files, transient_island
from tests.scenarios.launcher import Scenario, play

ISLANDS = 4
"""The worker processes that play a plain project."""
RUNS = 25
"""The runs each worker plays."""
TOLERANCE = 0.10
"""The share a weight and a key may move and still count as the same."""

WORKER = '''\
"""The worker processes of the level scenario."""

from __future__ import annotations

from pathlib import Path

LEVELS = (
    ("full", None),
    ("light", {"simulation.results.keep_per_cell_budget": False}),
    (
        "faces",
        {
            "simulation.results.keep_face_flows": True,
            "simulation.results.keep_solver_files": True,
        },
    ),
)


def play_island(index: int, root: str) -> list[str]:
    """Play the runs of one island, each on its own K, in its own run scratch."""
    import hydromodpy as hmp
    from hydromodpy.core.state.scratch import run_scratch

    work = Path(root) / f"w{index}"
    names = []
    for step in range(25):
        value = 2e-6 * (1.0 + step / 25.0 + index / 100.0)
        name = f"r{step:02d}"
        with run_scratch(work, name):
            hmp.run(work / "project.toml", name=name, set={"K": value})
        names.append(name)
    return names


def play_levels(root: str) -> list[str]:
    """Play the three levels of the steady island, then its calibration."""
    import hydromodpy as hmp
    from hydromodpy.core.state.scratch import run_scratch

    directory = Path(root) / "levels"
    for name, settings in LEVELS:
        with run_scratch(directory, name):
            hmp.run(directory / "project.toml", name=name, set=settings)
    hmp.calibrate(directory / "calib.toml")
    return [name for name, _ in LEVELS]
'''

CHILD = '''\
"""Play the scenario, then weigh and collect its projects."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

import island_worker  # noqa: E402


def measured(result) -> dict:
    """Return what one gc report says, as JSON."""
    plan = result.plan
    categories = plan.categories()
    return {
        "plan": categories,
        "bytes": {name: plan.bytes_of(name) for name in categories},
        "applied": result.applied,
        "freed": dict(result.freed),
        "before": result.before.as_dict(),
        "after": result.after.as_dict(),
        "total_before": result.before.total(),
        "total_after": result.after.total(),
    }


def main() -> None:
    import hydromodpy as hmp

    with ProcessPoolExecutor(max_workers=5, mp_context=get_context("spawn")) as pool:
        jobs = [pool.submit(island_worker.play_island, index, str(ROOT)) for index in range(4)]
        levels = pool.submit(island_worker.play_levels, str(ROOT))
        for job in jobs:
            job.result()
        levels.result()
    weights = {}
    for name in ("w0", "w1", "w2", "w3", "levels"):
        project = hmp.open(ROOT / name)
        try:
            weights[name] = measured(project.gc(dry_run=True))
        finally:
            project.close()
    project = hmp.open(ROOT / "w0")
    try:
        weights["w0"]["applied"] = measured(project.gc())
    finally:
        project.close()
    (ROOT / "weights.json").write_text(json.dumps(weights, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
'''


def _files() -> dict[str, str]:
    """Return the four islands, the levels project and the worker module."""
    files: dict[str, str] = {
        f"w{index}/project.toml": transient_island(f"w{index}", "modflow6")
        for index in range(ISLANDS)
    }
    for name, text in island_files("calage").items():
        if name == "calib.toml":
            text = text.replace('save_runs = "best_n"', 'save_runs = "all"')
        files[f"levels/{name}"] = text
    files["island_worker.py"] = WORKER
    return files


def _run_dirs(project: Path) -> list[Path]:
    """Return the sealed runs of one project, in name order."""
    runs = project / "runs"
    return sorted(path for path in runs.iterdir() if (path / "manifest.json").is_file())


def _bytes_under(path: Path) -> int:
    """Return the bytes of one file or of every file under one folder."""
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _expected_face_flow(faces: Path, cells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the face flows read again from the CBC file, and the last heads.

    MODFLOW 6 counts positive in ``FLOW-JA-FACE`` what enters the cell of the
    row, so the flow from ``m`` to ``n`` sits in row ``n`` at column ``m``. That
    position is read here from ``ia`` and ``ja`` of the binary grid, apart from
    the extractor. A stamp is the mean of its steps weighted by ``delt``,
    divided by the seconds of the time unit.
    """
    from flopy.mf6.utils import MfGrdFile
    from flopy.utils import HeadFile

    from hydromodpy.core.units.time import factor_to_seconds
    from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader
    from hydromodpy.solver.modflow_common.period_steps import (
        group_steps_by_stamp,
        weighted_period_mean,
    )
    from hydromodpy.solver.modflow_common.time_units import resolve_solver_time_unit

    # ``keep_solver_files`` keeps the folder of each solver run under ``solver/``.
    folders = sorted({path.parent for path in (faces / "solver").rglob("*.cbc")})
    assert len(folders) == 1, f"{faces / 'solver'} keeps {len(folders)} solver folders"
    solver = folders[0]
    heads = sorted(solver.glob("*.hds"))
    budgets = sorted(solver.glob("*.cbc"))
    assert heads and budgets, f"{solver} kept no heads file or no budget file"
    model = heads[0].stem
    head_file = HeadFile(str(heads[0]))
    stamps = [(int(kstp) + 1, int(kper) + 1) for kstp, kper in head_file.get_kstpkper()]
    last_heads = np.asarray(head_file.get_data(kstpkper=head_file.get_kstpkper()[-1]))

    grids = sorted(solver.glob("*.grb"))
    assert grids, f"{solver} carries no binary grid"
    grid = MfGrdFile(str(grids[0]), verbose=False)
    ia, ja = np.asarray(grid.ia), np.asarray(grid.ja)
    positions = np.empty(cells.shape[0], dtype=np.int64)
    for index, (first, second) in enumerate(cells.tolist()):
        row = np.arange(ia[second], ia[second + 1])
        found = row[ja[row] == first]
        assert found.size == 1, f"row {second} of the grid lists cell {first} {found.size} times"
        positions[index] = found[0]
    seconds = factor_to_seconds(resolve_solver_time_unit(solver, model))

    budget = Mf6CellBudgetReader(budgets[0])
    try:
        steps = [
            (index, record)
            for index, record in enumerate(budget.records)
            if record.text == "FLOW-JA-FACE"
        ]
        assert steps, f"{budgets[0].name} carries no FLOW-JA-FACE record"
        step_position: dict[tuple[int, int], int] = {}
        lengths: list[float] = []
        for _, record in steps:
            key = (int(record.kstp), int(record.kper))
            if key not in step_position:
                step_position[key] = len(lengths)
                lengths.append(float(record.delt))
        placed: dict[int, tuple[int, float]] = {}
        for group in group_steps_by_stamp(list(step_position), lengths, stamps):
            for position, weight in zip(group.positions, group.weights, strict=True):
                placed[position] = (group.stamp, weight)
        values: dict[int, list[np.ndarray]] = {}
        weights: dict[int, list[float]] = {}
        for index, record in steps:
            here = placed.get(step_position[(int(record.kstp), int(record.kper))])
            if here is None:
                continue
            flowja = np.asarray(budget.read_record(index), dtype="float64").reshape(-1)
            assert flowja.size == ja.size
            stamp, weight = here
            values.setdefault(stamp, []).append(flowja[positions])
            weights.setdefault(stamp, []).append(weight)
    finally:
        budget.close()

    expected = np.full((len(stamps), cells.shape[0]), np.nan, dtype="float64")
    for stamp, own in values.items():
        expected[stamp] = weighted_period_mean(own, weights[stamp]) / seconds
    return expected, last_heads.reshape(-1)


def test_a_hundred_runs_weigh_a_hundred_times_one(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    scenario = Scenario(
        name="levels",
        covers="one hundred runs of the result level, a light run, face flows, and gc",
        files=_files(),
        python=CHILD,
        needs=("mf6", "libmf6.so"),
        expected_s=70.0,
        timeout_s=300.0,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    log = played.log.read_text(encoding="utf-8", errors="replace")[-4000:]
    # The harness stops the scenario at timeout_s. A tighter wall-clock bound fails on a busy machine.
    assert played.returncode == 0, log

    weights: dict[str, dict[str, Any]] = json.loads(
        (played.root / "weights.json").read_text(encoding="utf-8")
    )
    islands = {f"w{index}": _run_dirs(played.root / f"w{index}") for index in range(ISLANDS)}
    runs = [run for group in islands.values() for run in group]

    # A hundred runs of the result level, each solved on its own parameter.
    assert len(runs) == ISLANDS * RUNS
    seals = [read_seal(run) for run in runs]
    assert len({seal.identity.solution_key for seal in seals}) == ISLANDS * RUNS
    assert {seal.budget.policy for seal in seals if seal.budget is not None} == {"all"}

    # One hundred runs weigh one hundred times one, and no run is an odd one.
    one = np.asarray([sum(run_weight(run).values()) for run in runs], dtype="float64")
    middle = float(np.median(one))
    assert np.all(np.abs(one - middle) <= TOLERANCE * middle), (one.min(), one.max(), middle)
    stored = sum(weights[f"w{index}"]["before"]["runs"] for index in range(ISLANDS))
    assert abs(stored - ISLANDS * RUNS * middle) <= TOLERANCE * ISLANDS * RUNS * middle

    # A run without its budget terms weighs what its budget terms weigh less.
    levels = played.root / "levels" / "runs"
    full = run_weight(levels / "full")
    light = run_weight(levels / "light")
    expected_light = sum(full.values()) - full["budget"]
    assert abs(sum(light.values()) - expected_light) <= TOLERANCE * expected_light
    light_seal = read_seal(levels / "light")
    assert light_seal.budget is not None and light_seal.budget.policy == "consumers"

    # Face flows cost one value per connection at each stamp, and nothing else.
    import zarr

    faces = levels / "faces"
    store = zarr.open_group(str(faces / "fields.zarr"), mode="r", use_consolidated=False)
    face_flow = np.asarray(store[FACE_FLOW][...])
    connection_cells = np.asarray(store[CONNECTION_CELLS][...])
    mesh = store["mesh"]
    edges = np.asarray(mesh["edge_face_connectivity"][...])
    idomain = np.asarray(mesh["idomain"][...])
    active = idomain.any(axis=0)
    internal = (edges >= 0).all(axis=1)
    here = internal & active[edges[:, 0]] & active[edges[:, 1]]
    count = int(here.sum())
    assert face_flow.ndim == 2
    assert face_flow.shape[1] == count
    assert connection_cells.shape == (count, 2)
    assert connection_cells.dtype == np.int32
    expected_pairs = {tuple(sorted(map(int, row))) for row in edges[here]}
    assert {tuple(map(int, row)) for row in connection_cells} == expected_pairs
    assert (connection_cells[:, 0] < connection_cells[:, 1]).all()

    stamps, n_connections, itemsize = face_flow.shape[0], count, face_flow.dtype.itemsize
    surplus = _bytes_under(faces / "fields.zarr" / FACE_FLOW)
    assert 0 < surplus <= 1.1 * stamps * n_connections * itemsize
    full_store = zarr.open_group(
        str(levels / "full" / "fields.zarr"), mode="r", use_consolidated=False
    )
    assert FACE_FLOW not in full_store
    assert sorted((faces / "solver").rglob("*.cbc"))

    # The store carries the flow of the budget file, at the position of each
    # connection, and water runs from the higher head to the lower.
    expected_flow, heads = _expected_face_flow(faces, connection_cells)
    np.testing.assert_allclose(face_flow, expected_flow, rtol=1e-6, atol=0.0, equal_nan=True)
    drop = heads[connection_cells[:, 0]] - heads[connection_cells[:, 1]]
    steep = np.abs(drop) > 1e-6
    assert steep.any()
    assert (np.sign(face_flow[-1][steep]) == np.sign(drop[steep])).all()

    # A kept trial of the calibration is a research run.
    trials = [
        path
        for path in sorted((played.root / "levels" / "sessions" / "calage" / "trials").iterdir())
        if (path / "manifest.json").is_file()
    ]
    assert trials
    for trial in trials:
        seal = read_seal(trial)
        assert seal.lineage.kind == "trial"
        assert seal.budget is not None and seal.budget.policy == "consumers"
        assert seal.budget.kept_terms == []
        assert not (trial / "figures").exists()
        assert not (trial / "exports").exists()
    best = read_seal(played.root / "levels" / "runs" / "calage")
    assert best.budget is not None and best.budget.policy == "all"

    # gc measures the dead scratch and frees exactly what its plan says. The
    # applied call reindexes the project, so the index may move; the scratch
    # family is the one the plan names, and no run loses a byte.
    plan = weights["w0"]["plan"]
    assert len(plan["dead_scratch"]) >= RUNS
    assert weights["w0"]["bytes"]["dead_scratch"] > 0
    applied = weights["w0"]["applied"]
    assert applied["applied"] is True
    assert applied["freed"]["dead_scratch"] == applied["bytes"]["dead_scratch"]
    assert (
        applied["before"]["scratch"] - applied["after"]["scratch"]
        == applied["bytes"]["dead_scratch"]
    )
    assert applied["after"]["scratch"] == 0
    assert applied["before"]["runs"] == applied["after"]["runs"]
    for run in islands["w0"]:
        assert seal_problems(run) == []
