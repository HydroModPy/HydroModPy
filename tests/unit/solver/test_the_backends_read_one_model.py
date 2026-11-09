"""The three flow backends read one frozen ``Model`` and never change it.

An island project is prepared by the real steps, up to the model of its flow run,
for each backend. The solver object keeps the very ``Model`` the ``prepare_solver``
step built (``inputs``). A per-cell K set with ``Model.with_properties`` and a
recharge set on the model reach the arrays the backend writes, and a name the
backend does not read is refused. A build, and a solve, leave the model as it was,
which a digest of every member before and after shows. Each backend builds in
the folder of the ``RunSlot`` the runner fills, stops there when the slot says so,
and solves into that folder otherwise.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners.trial import built_model, prepare_trials
from hydromodpy.solver.base.plan import SolverRun
from hydromodpy.solver.base.runner import options_for, slot_for, solve_one
from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver
from hydromodpy.solver.modflow6.builders.recharge import recharge_to_spd
from tests._helpers.island_project import island_toml

K_M_S = 5e-6
K_FACTOR = 4.0
RECHARGE_FACTOR = 2.0

BACKENDS = ("modflow6", "modflow_nwt", "boussinesq")
MESH_TABLE = {
    "modflow6": "",
    "modflow_nwt": "\n[mesh]\ncell_size = 40.0\n",
    "boussinesq": '\n[mesh]\nengine = "triangle"\ncell_size = 30.0\n',
}


def _mf6_or_nwt_conductivity(solver: Any) -> np.ndarray:
    return np.asarray(solver.hk, dtype=float)


def _boussinesq_conductivity(solver: Any) -> np.ndarray:
    return np.asarray(solver.mesh.hydraulic_conductivity_m_s, dtype=float)


def _mf6_recharge(solver: Any) -> float:
    return float(np.max(np.asarray(recharge_to_spd(solver)[0], dtype=float)))


def _nwt_recharge(solver: Any) -> float:
    return float(np.max(np.asarray(solver.recharge[0], dtype=float)))


def _boussinesq_recharge(solver: Any) -> float:
    resolver = BoussinesqForcingResolver(mesh=solver.mesh, inputs=solver.inputs)
    return float(np.max(np.asarray(resolver.resolve_recharge_series(1)[0], dtype=float)))


# What each backend wrote, in its own units: only the ratio to another run is read.
READERS: dict[str, tuple[Callable[[Any], np.ndarray], Callable[[Any], float]]] = {
    "modflow6": (_mf6_or_nwt_conductivity, _mf6_recharge),
    "modflow_nwt": (_mf6_or_nwt_conductivity, _nwt_recharge),
    "boussinesq": (_boussinesq_conductivity, _boussinesq_recharge),
}


def _digest(value: object) -> str:
    """A digest of a model that walks dataclasses, mappings, sequences and arrays.

    A read-only mapping cannot be pickled, so the model is walked member by member.
    Anything else is read through its dumped fields or its ``repr``.
    """
    hasher = hashlib.sha256()
    seen: set[int] = set()

    def feed(item: object) -> None:
        if isinstance(item, np.ndarray):
            hasher.update(f"{item.dtype}{item.shape}".encode())
            if item.dtype == object:
                hasher.update(repr(item.tolist()).encode())
            else:
                hasher.update(np.ascontiguousarray(item).tobytes())
            return
        if item is None or isinstance(item, str | bytes | int | float | bool | complex):
            hasher.update(repr(item).encode())
            return
        if id(item) in seen:
            hasher.update(b"<seen>")
            return
        seen.add(id(item))
        hasher.update(type(item).__name__.encode())
        if is_dataclass(item) and not isinstance(item, type):
            for member in fields(item):
                hasher.update(member.name.encode())
                feed(getattr(item, member.name))
        elif isinstance(item, Mapping):
            for key in sorted(item, key=repr):
                feed(key)
                feed(item[key])
        elif isinstance(item, list | tuple | set | frozenset):
            for part in item if not isinstance(item, set | frozenset) else sorted(item, key=repr):
                feed(part)
        elif hasattr(item, "model_dump"):
            feed(item.model_dump(mode="python"))
        else:
            hasher.update(repr(item).encode())

    feed(value)
    return hasher.hexdigest()


def _space() -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}
    )


@contextmanager
def _island(tmp_path: Path, backend: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Yield the context of an island run whose flow model was built by ``backend``."""
    text = island_toml(f"port_{backend}").replace(
        'solvers = ["modflow6"]', f'solvers = ["{backend}"]'
    )
    path = tmp_path / "project.toml"
    path.write_text(text + MESH_TABLE[backend], encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    trial_ctx = prepare_trials(
        path, override_paths=["flow.param.K.field.value"], parameter_space=_space()
    )
    with built_model(trial_ctx, {"K": K_M_S}) as ctx:
        yield ctx


def _solve(ctx: Any, model: Any, *, solve: bool = False) -> SolverRun:
    """Run the flow adapter of ``ctx`` on ``model`` through the contract and return its run."""
    adapter, run_ctx = solver_extract.resolve_flow_adapter(ctx)
    ctx.setup.model = model
    slot = replace(slot_for(run_ctx.plan, run_ctx.run, ctx.setup), stop_before_solve=not solve)
    options = options_for(adapter, run_ctx.run, ctx.cfg)
    return solve_one(adapter, model, options, slot)


def _execute(ctx: Any, model: Any, *, solve: bool = False) -> Any:
    """Run the flow adapter of ``ctx`` on ``model`` and return the solver object it built."""
    return _solve(ctx, model, solve=solve).solver_model


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_solver_keeps_the_model_the_step_built(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        model = ctx.setup.model
        solver = _execute(ctx, model)

        assert solver.inputs is model


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_k_and_a_recharge_set_on_the_model_reach_the_backend(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_k, read_recharge = READERS[backend]
    with _island(tmp_path, backend, monkeypatch) as ctx:
        model = ctx.setup.model
        base = _execute(ctx, model)
        base_k, base_recharge = read_k(base), read_recharge(base)

        recharge = model.recharge.model_copy(
            update={"values": [RECHARGE_FACTOR * float(np.mean(model.recharge.values))]}
        )
        changed = replace(model.with_properties(K=K_FACTOR * K_M_S), recharge=recharge)
        solver = _execute(ctx, changed)

        np.testing.assert_allclose(read_k(solver), K_FACTOR * base_k, rtol=1e-12)
        assert read_recharge(solver) == pytest.approx(RECHARGE_FACTOR * base_recharge, rel=1e-12)
        assert model.properties.overrides == {}


def test_boussinesq_refuses_a_property_it_does_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, "boussinesq", monkeypatch) as ctx:
        model = ctx.setup.model.with_properties(Kv=K_M_S)

        with pytest.raises(ValueError, match="sets Kv, which this solver does not read"):
            _execute(ctx, model)


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_name_that_is_no_property_is_refused_by_the_model(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        with pytest.raises(ValueError, match="K_22 name no flow property"):
            ctx.setup.model.with_properties(K_22=K_M_S)


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_build_leaves_the_model_as_it_found_it(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        model = ctx.setup.model.with_properties(K=K_FACTOR * K_M_S)
        before = _digest(model)

        _execute(ctx, model)

        assert _digest(model) == before


@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.parametrize("backend", BACKENDS)
def test_a_solve_leaves_the_model_as_it_found_it(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        model = ctx.setup.model
        before = _digest(model)

        _execute(ctx, model, solve=True)

        assert _digest(model) == before


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_build_that_stops_before_the_solve_lies_in_its_slot_unsolved(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        built = _solve(ctx, ctx.setup.model)

        assert (built.written, built.solved) == (False, False)
        assert built.model is ctx.setup.model
        assert Path(built.solver_model.full_path).resolve() == built.slot.directory.resolve()


@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.parametrize("backend", BACKENDS)
def test_a_solve_writes_into_the_folder_of_its_slot(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _island(tmp_path, backend, monkeypatch) as ctx:
        solved = _solve(ctx, ctx.setup.model, solve=True)

        assert (solved.written, solved.solved) == (True, True)
        assert solved.output_dir is not None
        assert solved.output_dir.resolve() == solved.slot.directory.resolve()


def test_the_linear_reservoir_reads_one_model(tmp_path: Path) -> None:
    """The global backend runs the factory's one-cell Model, and the common asserts hold.

    The doc of an island names properties no global model reads, so this line
    does not walk the island path: the ``Model`` comes from the factory, on the
    one polygon cell the catchment engine meshes, at the steps of its own
    forcing. The recharge the run reads is the one the ``Model`` carries, in
    m/s, one rate per piece, and the build leaves the ``Model`` as it found it.
    """
    from hydromodpy.model.model import ModelTime
    from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
    from hydromodpy.solver.base.plan import RunSlot
    from hydromodpy.solver.linear_reservoir.adapter import (
        SERIES_FILE,
        LinearReservoirFlowAdapter,
    )
    from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions
    from tests._helpers.model_factory import make_model, one_cell_geometry, time_grid

    rates = [1.5e-8, 3.0e-8]
    model = make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(5.0, 5.0), regime="transient", first_period_steady=False),
        recharge=FlowRechargeConfig(units="m/s", values=rates),
    )
    before = _digest(model)

    adapter = LinearReservoirFlowAdapter()
    slot = RunSlot(folder=tmp_path / "runs", name="port_linear_reservoir")
    built = adapter.build(model, LinearReservoirOptions(time_constant="30 days"), slot)

    assert (built.written, built.solved) == (False, False)
    assert built.solver_model is not None
    solved = adapter.run(built)
    assert (solved.written, solved.solved) == (True, True)
    assert solved.output_dir is not None
    assert solved.output_dir.resolve() == solved.slot.directory.resolve()
    assert _digest(model) == before

    frame = pd.read_csv(solved.output_dir / SERIES_FILE, index_col="time", parse_dates=True)
    expected = np.asarray(rates) * 1.0
    np.testing.assert_allclose(frame["recharge_m_s"].to_numpy(), expected, rtol=1e-12)
