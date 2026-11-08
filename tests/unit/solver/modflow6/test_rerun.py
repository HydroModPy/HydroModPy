"""``rerun`` of MODFLOW 6 rewrites only what K or Sy reach, and refuses what needs a build.

No binary runs here. The solver object is a stand-in that holds the per-cell
arrays and the three packages a rerun writes, and the mapping of the properties
is replaced by the arrays each case gives. A refusal returns ``None`` and
touches nothing: no file is copied, the simulation stays in its folder, and no
package is written. An accepted rerun copies exactly the input files of the
previous run, moves the solver object to the new slot and writes the packages
whose values differ from what the object holds. The proof against a real build
is ``tests/integration/solver/test_modflow6_rerun_matches_a_build.py``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.model.initial.state import CyclicSpinupStrategy, CyclicStart, SteadyStart
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.modflow6 import rerun as rerun_module
from hydromodpy.solver.modflow6.rerun import plan_rerun, rerun_modflow6
from tests._helpers.model_factory import make_model

MUTABLE = frozenset({"K", "Sy"})
INPUT_FILES = ("mfsim.nam", "run.npf", "run.sto", "sub/run.rcha.0.bin")
K = np.array([[1e-5, 2e-5, 3e-5, 4e-5]])
SY = np.array([[0.1, 0.1, 0.2, 0.2]])
SS = np.full((1, 4), 1e-5)
DRN_ROWS = {0: [[0, 1, 9.0, 0.5], [0, 2, 8.0, 0.5]]}


class _Data:
    def __init__(self) -> None:
        self.set: list[Any] = []

    def set_data(self, values: Any) -> None:
        self.set.append(values)


class _Package:
    """A FloPy package: the data a rerun sets, and the writes it asks."""

    def __init__(self, *names: str, rows: dict | None = None) -> None:
        for name in names:
            setattr(self, name, _Data())
        self.writes = 0
        self.rows = rows

    def write(self) -> None:
        self.writes += 1


class _StressPeriodData(_Data):
    def __init__(self, rows: dict) -> None:
        super().__init__()
        self.rows = rows

    def get_data(self) -> dict:
        dtype = [("cellid", object), ("elev", float), ("cond", float)]
        return {
            kper: np.array(
                [((layer, cell), elev, cond) for layer, cell, elev, cond in rows], dtype=dtype
            )
            for kper, rows in self.rows.items()
        }


class _Simulation:
    def __init__(self, folder: Path) -> None:
        self.sim_path = folder
        self.moved: list[str] = []

    def set_sim_path(self, path: str) -> None:
        self.moved.append(path)
        self.sim_path = Path(path)


def _fields(**changed: np.ndarray | None) -> dict[str, np.ndarray | None]:
    fields = {"hk": K, "k33": K / 10.0, "k22": None, "angle1": None, "angle2": None, "angle3": None}
    fields.update({"sy": SY, "ss": SS})
    fields.update(changed)
    return fields


def _solver(folder: Path, model: Any, slot: RunSlot) -> SimpleNamespace:
    drn = _Package()
    drn.stress_period_data = _StressPeriodData(DRN_ROWS)
    return SimpleNamespace(
        sim=_Simulation(folder),
        inputs=model,
        slot=slot,
        full_path=str(folder),
        model_folder=slot.folder,
        **_fields(),
        npf=_Package("k", "k33", "k22", "angle1", "angle2", "angle3"),
        sto=_Package("sy", "ss"),
        drn=drn,
        _drainage_uses_hk=True,
        _drainage_cond_series=np.zeros(1),
        _ocean_support_mask=np.zeros(4, dtype=bool),
        _stream_support_mask=np.zeros(4, dtype=bool),
        _drain_dropped_cells=frozenset(),
        _property_mesh=SimpleNamespace(is_structured=False),
        solver_mesh=SimpleNamespace(idomain=np.ones((1, 4), dtype=int)),
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_enable_xt3d=None)),
        steady=[False],
        nper=1,
        nlay=1,
        dem_watershed_path="",
        grid_ctx=None,
    )


def _previous(tmp_path: Path, model: Any = None, **slot_members: Any) -> SolverRun:
    """A solved run of ``model`` in ``tmp_path/first/run``, its input files on disk."""
    model = make_model() if model is None else model
    slot = RunSlot(tmp_path / "first", "run", **slot_members)
    for name in (*INPUT_FILES, "run.hds"):
        (slot.directory / name).parent.mkdir(parents=True, exist_ok=True)
        (slot.directory / name).write_text(name)
    return SolverRun(
        slot=slot,
        model=model,
        solver_model=_solver(slot.directory, model, slot),
        output_dir=slot.directory,
        input_files=INPUT_FILES,
        written=True,
        solved=True,
    )


@pytest.fixture
def mapped(monkeypatch) -> dict[str, Any]:
    """The arrays the mapping of the new ``Model`` gives, and the sidecar writes."""
    state: dict[str, Any] = {"fields": _fields(), "sidecars": 0, "drain": DRN_ROWS}

    def fields(solver, model, mesh):
        del solver, model, mesh
        return state["fields"]

    def sidecar(solver):
        del solver
        state["sidecars"] += 1

    def drain(view, **kwargs):
        del kwargs
        hk = np.asarray(view.hk).reshape(-1)
        return {
            kper: [[layer, cell, elev, float(hk[cell]) * 1e4] for layer, cell, elev, _ in rows]
            for kper, rows in state["drain"].items()
        }

    monkeypatch.setattr(rerun_module, "flow_property_fields", fields)
    monkeypatch.setattr(rerun_module, "_save_flow_property_sidecar", sidecar)
    monkeypatch.setattr(rerun_module, "build_drain_stress_period_data", drain)
    return state


def _untouched(previous: SolverRun, tmp_path: Path, model_before: Any) -> None:
    solver = previous.solver_model
    assert not (tmp_path / "next").exists(), "a refusal copies nothing"
    assert solver.sim.moved == []
    assert solver.inputs is model_before
    assert solver.npf.writes == solver.sto.writes == solver.drn.writes == 0
    assert solver.hk is K and solver.sy is SY


def _refuse_not_solved(previous, model, tmp_path):
    return replace(previous, solved=False), model, RunSlot(tmp_path / "next", "run")


def _refuse_no_solver(previous, model, tmp_path):
    return replace(previous, solver_model=None), model, RunSlot(tmp_path / "next", "run")


def _refuse_consumed(previous, model, tmp_path):
    previous.solver_model.inputs = make_model()
    return previous, model, RunSlot(tmp_path / "next", "run")


def _refuse_moved(previous, model, tmp_path):
    previous.solver_model.sim.sim_path = tmp_path / "elsewhere"
    return previous, model, RunSlot(tmp_path / "next", "run")


def _refuse_files_gone(previous, model, tmp_path):
    (previous.output_dir / "run.npf").unlink()
    return previous, model, RunSlot(tmp_path / "next", "run")


def _refuse_other_forcing(previous, model, tmp_path):
    return previous, model, RunSlot(tmp_path / "next", "run", shared_forcing_dir=tmp_path / "f")


def _refuse_other_binaries(previous, model, tmp_path):
    return previous, model, RunSlot(tmp_path / "next", "run", bin_dir=tmp_path / "bin")


def _refuse_start(initial):
    def case(previous, model, tmp_path):
        base = make_model(initial=initial)
        previous = _previous(tmp_path / "start", base)
        return previous, base.with_properties(K=2e-5), RunSlot(tmp_path / "next", "run")

    return case


def _refuse_other_member(previous, model, tmp_path):
    return previous, make_model().with_properties(K=2e-5), RunSlot(tmp_path / "next", "run")


def _refuse_ss(previous, model, tmp_path):
    return previous, previous.model.with_properties(Ss=2e-5), RunSlot(tmp_path / "next", "run")


REFUSALS = (
    ("a previous run that is not solved", _refuse_not_solved, {}, "not solved"),
    ("a previous run without its solver object", _refuse_no_solver, {}, "no solver model"),
    ("a parent a rerun already consumed", _refuse_consumed, {}, "consumed it"),
    ("a solver object moved to another folder", _refuse_moved, {}, "no longer writes"),
    ("input files that are gone", _refuse_files_gone, {}, "run.npf"),
    ("another shared forcing folder", _refuse_other_forcing, {}, "shared forcing folder"),
    ("other binaries", _refuse_other_binaries, {}, "binaries"),
    ("a steady start", _refuse_start(SteadyStart()), {}, "SteadyStart"),
    ("a cyclic start", _refuse_start(CyclicStart(CyclicSpinupStrategy())), {}, "CyclicStart"),
    ("another member of the Model", _refuse_other_member, {}, "other than its properties"),
    ("a property outside K and Sy", _refuse_ss, {}, "Ss change"),
    ("a K22 that gains a value", None, {"k22": K}, "gains or loses k22"),
    ("an XT3D switched on by K against K22", None, {"hk": K * 3.0}, "XT3D"),
    (
        "drain cells that change",
        None,
        {"hk": K * 3.0, "drain": {0: [[0, 3, 9.0, 0.5]]}},
        "drain cells",
    ),
)


@pytest.mark.parametrize(
    ("case", "prepare", "mapping", "reason"), REFUSALS, ids=[case[0] for case in REFUSALS]
)
def test_a_change_that_needs_a_build_is_refused_and_touches_nothing(
    tmp_path: Path, mapped: dict, case: str, prepare, mapping: dict, reason: str
) -> None:
    del case
    previous = _previous(tmp_path)
    model = previous.model.with_properties(K=2e-5)
    if prepare is not None:
        previous, model, slot = prepare(previous, model, tmp_path)
    else:
        slot = RunSlot(tmp_path / "next", "run")
    if "drain" in mapping:
        mapped["drain"] = mapping["drain"]
    if mapping.get("k22") is not None:
        mapped["fields"] = _fields(k22=mapping["k22"])
    elif "hk" in mapping:
        # K22 equal to K on every cell is isotropic; a new K off K22 is not.
        if "drain" not in mapping:
            previous.solver_model.k22 = K
            mapped["fields"] = _fields(hk=mapping["hk"], k22=K)
        else:
            mapped["fields"] = _fields(hk=mapping["hk"])
    model_before = previous.solver_model.inputs if previous.solver_model is not None else None

    plan = plan_rerun(previous, model, slot, mutable=MUTABLE)
    rerun = rerun_modflow6(previous, model, slot, mutable=MUTABLE)

    assert plan.refusal is not None and reason in plan.refusal
    assert rerun is None
    if previous.solver_model is not None:
        _untouched(previous, tmp_path, model_before)


def test_an_xt3d_written_in_the_options_holds_whatever_k_is(tmp_path: Path, mapped: dict) -> None:
    previous = _previous(tmp_path)
    previous.solver_model.k22 = K
    previous.solver_model.modflow_config.runtime.mf6_enable_xt3d = True
    mapped["fields"] = _fields(hk=K * 3.0, k22=K)

    plan = plan_rerun(
        previous,
        previous.model.with_properties(K=2e-5),
        RunSlot(tmp_path / "next", "run"),
        mutable=MUTABLE,
    )

    assert plan.refusal is None and plan.npf == {"hk"}


ACCEPTED = (
    ("a new K rewrites NPF and DRN", {"hk": K * 3.0, "k33": K * 0.3}, {"K": 2e-5}, (1, 0, 1)),
    ("a new Sy rewrites STO", {"sy": SY * 2.0}, {"Sy": 0.2}, (0, 1, 0)),
    (
        "K and Sy rewrite the three",
        {"hk": K * 0.5, "sy": SY * 0.5},
        {"K": 1e-6, "Sy": 0.05},
        (1, 1, 1),
    ),
    ("the same values rewrite nothing", {}, {"K": 1e-5}, (0, 0, 0)),
)


@pytest.mark.parametrize(
    ("case", "fields", "properties", "writes"), ACCEPTED, ids=[case[0] for case in ACCEPTED]
)
def test_a_rerun_copies_the_input_files_and_writes_what_changed(
    tmp_path: Path, mapped: dict, case: str, fields: dict, properties: dict, writes: tuple
) -> None:
    del case
    previous = _previous(tmp_path)
    solver = previous.solver_model
    model = previous.model.with_properties(**properties)
    mapped["fields"] = _fields(**fields)
    slot = RunSlot(tmp_path / "next", "trial_b")

    rerun = rerun_modflow6(previous, model, slot, mutable=MUTABLE)

    assert rerun is not None
    copied = sorted(
        path.relative_to(slot.directory).as_posix()
        for path in slot.directory.rglob("*")
        if path.is_file()
    )
    assert copied == sorted(INPUT_FILES), "exactly the input files, under their names"
    assert (rerun.slot, rerun.model, rerun.solver_model) == (slot, model, solver)
    assert (rerun.written, rerun.solved, rerun.output_dir) == (True, False, None)
    assert rerun.input_files == INPUT_FILES and solver.input_files == INPUT_FILES
    assert rerun.options is previous.options
    assert solver.sim.moved == [str(slot.directory)]
    assert solver.full_path == str(slot.directory) and solver.slot is slot
    assert solver.inputs is model
    assert (solver.npf.writes, solver.sto.writes, solver.drn.writes) == writes
    assert mapped["sidecars"] == (1 if any(writes[:2]) else 0)
    for name, values in fields.items():
        assert getattr(solver, name) is values


def test_a_new_k_sets_k_and_k33_and_the_drain_conductance_it_reaches(
    tmp_path: Path, mapped: dict
) -> None:
    previous = _previous(tmp_path)
    solver = previous.solver_model
    mapped["fields"] = _fields(hk=K * 3.0, k33=K * 0.3)

    rerun_modflow6(
        previous,
        previous.model.with_properties(K=3e-5),
        RunSlot(tmp_path / "next", "run"),
        mutable=MUTABLE,
    )

    assert [values is mapped["fields"]["hk"] for values in solver.npf.k.set] == [True]
    assert [values is mapped["fields"]["k33"] for values in solver.npf.k33.set] == [True]
    assert solver.npf.k22.set == [] and solver.sto.sy.set == []
    (rows,) = solver.drn.stress_period_data.set
    assert [row[:3] for row in rows[0]] == [[0, 1, 9.0], [0, 2, 8.0]]
    assert [row[3] for row in rows[0]] == pytest.approx([0.6, 0.9], rel=1e-12)


def test_a_drain_with_a_configured_conductance_stays_the_copied_one(
    tmp_path: Path, mapped: dict
) -> None:
    previous = _previous(tmp_path)
    previous.solver_model._drainage_uses_hk = False
    mapped["fields"] = _fields(hk=K * 3.0)

    rerun_modflow6(
        previous,
        previous.model.with_properties(K=3e-5),
        RunSlot(tmp_path / "next", "run"),
        mutable=MUTABLE,
    )

    assert previous.solver_model.drn.writes == 0
    assert previous.solver_model.npf.writes == 1


def test_a_rerun_into_the_folder_of_the_previous_run_copies_nothing(
    tmp_path: Path, mapped: dict
) -> None:
    previous = _previous(tmp_path)
    mapped["fields"] = _fields(sy=SY * 2.0)

    rerun = rerun_modflow6(
        previous, previous.model.with_properties(Sy=0.2), previous.slot, mutable=MUTABLE
    )

    assert rerun is not None and rerun.slot is previous.slot
    assert (previous.output_dir / "run.hds").is_file(), "the folder keeps what it held"


def test_a_chain_reruns_from_the_run_a_rerun_returned_and_not_from_its_parent(
    tmp_path: Path, mapped: dict
) -> None:
    previous = _previous(tmp_path)
    model_k = previous.model.with_properties(K=2e-5)
    mapped["fields"] = _fields(hk=K * 2.0)
    second = rerun_modflow6(previous, model_k, RunSlot(tmp_path / "b", "run"), mutable=MUTABLE)
    assert second is not None
    (second.slot.directory / "run.hds").write_text("solved")
    second = replace(second, output_dir=second.slot.directory, solved=True)
    model_sy = model_k.with_properties(K=2e-5, Sy=0.2)
    mapped["fields"] = _fields(hk=K * 2.0, sy=SY * 2.0)

    stale = plan_rerun(previous, model_sy, RunSlot(tmp_path / "c", "run"), mutable=MUTABLE)
    third = rerun_modflow6(second, model_sy, RunSlot(tmp_path / "c", "run"), mutable=MUTABLE)

    assert stale.refusal is not None and "consumed" in stale.refusal
    assert third is not None
    solver = third.solver_model
    assert (solver.npf.writes, solver.sto.writes) == (1, 1), "K once, then Sy alone"
    assert solver.sim.moved == [str(tmp_path / "b" / "run"), str(tmp_path / "c" / "run")]
