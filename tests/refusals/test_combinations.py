"""Options that are valid alone and wrong together are refused with the pair named.

The table of question 16 has five rows, and each row is the test of the same name:
a transport behind a start that did not converge, the traits Boussinesq ignores, a
restart beside a computed start, a lake under a cyclic start and a soil settled on its
first year beside a cyclic aquifer. The last two are accepted, and the test says
where the decision is written. The two depression remedies, the lumped mesh and the
soil rows follow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.solver_supports import (
    CONTAMINATIONS,
    TRAIT_USES,
    refuse_the_traits_the_solver_ignores,
    uses_of,
)
from hydromodpy.core.exceptions import (
    ConfigValidationError,
    IncompatibleCapabilitiesError,
    PipelineError,
    SolverDivergedError,
)
from hydromodpy.model.supports import SUPPORTS
from hydromodpy.schema.changes import REGISTER
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import SimulationRunner
from tests._helpers.fake_solvers import FakeAdapter, fake_adapter

REPO = Path(__file__).resolve().parents[2]
QUESTION_16 = (
    "transport_behind_an_unconverged_start",
    "traits_boussinesq_ignores",
    "restart_beside_a_computed_start",
    "lake_under_a_cyclic_start",
    "soil_first_year_beside_a_cyclic_aquifer",
)
FLOWS = tuple(solvers.names("flow"))
LAKE = {"bedleak": 0.1, "initial_stage": "85 m"}
WALL = {"line": [[0.0, 0.0], [10.0, 0.0]], "depths": [5.0], "hydchr": 1e-9}
K_FIELD = {"kind": "homogeneous", "value": "1e-5 m/s"}
SOIL = {
    "simulation": {
        "time": {
            "start_datetime": "2015-01-01",
            "end_datetime": "2016-12-31",
            "step_value": "1 day",
        }
    },
    "data": {
        "types": ["precipitation", "etp"],
        "precipitation": {"sources": [{"source": "sim2", "extent": "watershed"}]},
        "etp": {"sources": [{"source": "sim2", "extent": "watershed"}]},
    },
    "flow": {
        "first_period_steady": False,
        "sinks_sources": {"recharge": {"soil": {"ru": "150 mm"}}},
    },
}
SURFACES = {
    "domain": {
        "layers": {
            "genmtd_lay": "surfaces",
            "layer": [{"name": "weathered", "surface": "weathered_base"}, {"name": "rock"}],
        }
    },
    "data": {"layer_base": {"sources": [{"name": "weathered_base", "path": "weathered.tif"}]}},
}

# One row per trait of SUPPORTS: a document that uses it, under MODFLOW 6.
TRAIT_DOCUMENTS: dict[str, dict[str, Any]] = {
    "west_side": {"flow": {"bc": {"west_side": {"value": "10 m"}}}},
    "east_side": {"flow": {"bc": {"east_side": {"value": "10 m"}}}},
    "north_side": {"flow": {"bc": {"north_side": {"value": "10 m"}}}},
    "south_side": {"flow": {"bc": {"south_side": {"value": "10 m"}}}},
    "stream": {"flow": {"bc": {"stream": {"value": "10 m"}}}},
    "ocean": {"flow": {"bc": {"ocean": {"value": "0 m"}}}},
    "drainage": {"flow": {"bc": {"drainage": {}}}},
    "lake": {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}}},
    "sfr": {"flow": {"bc": {"drainage": {}}, "sinks_sources": {"sfr": {"main": {}}}}},
    "sink_fill": {"solver": {"sink_fill": True}},
    "drain_band_depth_m": {"solver": {"drain_band_depth_m": 0.5}},
    "drain_bed_thickness_m": {"solver": {"drain_bed_thickness_m": 0.5}},
    "drain_conductance_floor_m2_s": {"solver": {"drain_conductance_floor_m2_s": 1e-10}},
    "head_rule": {"flow": {"ic": {"kind": "bottom"}}},
    "steady_start": {"flow": {"ic": {"kind": "steady_state"}}},
    "cyclic_start": {"flow": {"ic": {"kind": "spinup_cyclic"}}},
    "prior_state": {"flow": {"restart_from": "runs/spinup/fields.zarr"}},
    "recharge": {"flow": {"sinks_sources": {"recharge": {}}}},
    "wells": {
        "flow": {
            "sinks_sources": {
                "wells": {
                    "w1": {
                        "location": {"kind": "absolute_xy", "x": 1.0, "y": 2.0},
                        "flux": -1.0,
                    }
                }
            }
        }
    },
    "etp": {"flow": {"sinks_sources": {"etp": {}}}},
    "flow_barriers": {"flow": {"sinks_sources": {"flow_barriers": {"wall": WALL}}}},
    "cutoff_wall": {"flow": {"sinks_sources": {"lakes": {"lac": {**LAKE, "cutoff_wall": WALL}}}}},
    "soil": SOIL,
    "properties": {"flow": {"param": {"K": {"field": K_FIELD}}}},
    "k_tensor": {
        "flow": {
            "param_list": ["K", "K22"],
            "param": {"K": {"field": K_FIELD}, "K22": {"field": K_FIELD}},
        }
    },
    "layers": {"domain": {"layers": {"nlay": 3}}},
    "pass_through": SURFACES,
}


REQUIRED_OPTIONS = {"linear_reservoir": {"linear_reservoir": {"time_constant": "30 days"}}}
"""The option a flow solver refuses to load without."""


def _document(extra: dict[str, Any], backend: str = "modflow6") -> dict[str, Any]:
    return {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **extra,
        "solver": {
            "backend": backend,
            **REQUIRED_OPTIONS.get(backend, {}),
            **extra.get("solver", {}),
        },
    }


def _load(tmp_path: Path, extra: dict[str, Any], *, backend: str = "modflow6") -> HydroModPyConfig:
    (tmp_path / "weathered.tif").touch()
    return HydroModPyConfig.from_dict(_document(extra, backend), base_dir=tmp_path)


def test_the_five_rows_of_question_16_are_tested() -> None:
    assert [name for name in QUESTION_16 if f"test_{name}" not in globals()] == []


# --- 1. a transport behind a start that did not converge ---------------------------------

FLOW = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
TRANSPORT = ProcessRun(
    id="transport_main::modpath",
    process_id="transport_main",
    process_type="transport",
    solver="modpath",
    depends_on=(FLOW.id,),
)


def _register_backends(isolated_solvers: Any, *, trace: list[str], converged: bool | None) -> None:
    """Register a fake flow and a fake transport that follows it, under their own names."""

    def flow_build(self: FakeAdapter, model, options, slot, upstream=()):
        trace.append("flow")
        return SolverRun(
            slot=slot,
            model=model,
            solver_model=object(),
            initial_state_converged=converged,
        )

    def transport_build(self: FakeAdapter, model, options, slot, upstream=()):
        trace.append("transport")
        if not upstream:
            raise PipelineError("A fake transport received no flow to follow.")
        (followed,) = upstream
        return SolverRun(
            slot=slot,
            model=model,
            solver_model=object(),
            output_dir=followed.output_dir if followed.written else followed.slot.directory,
        )

    isolated_solvers.solvers.register(
        fake_adapter("modflow6", "flow", build=flow_build), replace=True
    )
    isolated_solvers.solvers.register(
        fake_adapter(
            "modpath",
            "transport",
            build=transport_build,
            reads=("face_flow",),
            requires=(("flow", "modflow6"),),
        ),
        replace=True,
    )


@pytest.mark.parametrize(
    ("converged", "sealed", "outcome"),
    [
        (True, False, "runs"),
        (None, False, "runs"),
        (False, False, "refused"),
        (False, True, "warns"),
        (True, True, "runs"),
    ],
    ids=["converged", "no steady start", "not converged", "not converged, sealed", "sealed"],
)
def test_transport_behind_an_unconverged_start(
    isolated_solvers: Any, converged: bool | None, sealed: bool, outcome: str
) -> None:
    trace: list[str] = []
    _register_backends(isolated_solvers, trace=trace, converged=converged)
    state = SimpleNamespace(
        cfg=SimpleNamespace(read_as_sealed=sealed),
        setup=SimpleNamespace(model=object()),
        execution=SimpleNamespace(solver_runs={}),
        sim_id=None,
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(FLOW, TRANSPORT))

    if outcome == "refused":
        with pytest.raises(SolverDivergedError, match="did not converge") as caught:
            SimulationRunner().execute(plan, state)
        assert caught.value.code == "HMPY.E401"
        assert caught.value.run_id == TRANSPORT.id
        assert trace == ["flow"]
        return
    if outcome == "warns":
        with pytest.warns(RuntimeWarning, match="did not converge"):
            SimulationRunner().execute(plan, state)
    else:
        SimulationRunner().execute(plan, state)
    assert trace == ["flow", "transport"]


# --- 2. the traits Boussinesq ignores ----------------------------------------------------


def _under(cfg: HydroModPyConfig, backend: str) -> HydroModPyConfig:
    """Return the same validated document with another flow solver, not validated again."""
    return cfg.model_copy(update={"solver": cfg.solver.model_copy(update={"backend": backend})})


def test_the_table_of_traits_covers_the_closed_set() -> None:
    assert set(TRAIT_USES) == SUPPORTS
    assert set(TRAIT_DOCUMENTS) == SUPPORTS


@pytest.mark.parametrize("backend", FLOWS)
@pytest.mark.parametrize("trait", sorted(TRAIT_DOCUMENTS))
def test_traits_boussinesq_ignores(tmp_path: Path, trait: str, backend: str) -> None:
    cfg = _under(_load(tmp_path, TRAIT_DOCUMENTS[trait]), backend)
    uses = uses_of(cfg)
    supports = solvers.get("flow", backend).supports
    honoring = [name for name in FLOWS if trait in solvers.get("flow", name).supports]

    assert trait in uses
    if set(uses) <= supports:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)
        return
    with pytest.raises(IncompatibleCapabilitiesError) as caught:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)

    message = str(caught.value)
    assert caught.value.code == "HMPY.E407"
    assert (trait in supports) == (f"does not honor {uses[trait]}:" not in message)
    if trait not in supports:
        assert f"solver.backend = {backend!r} does not honor {uses[trait]}:" in message
        if honoring:
            assert f"run a flow solver that honors it ({', '.join(honoring)})." in message
        else:
            assert "no flow solver of this installation honors it" in message


def test_boussinesq_refuses_a_document_read_through_the_root(tmp_path: Path) -> None:
    document = _document({"solver": {"sink_fill": True}}, backend="boussinesq")
    document["mesh"] = {"engine": "triangle", "families": {"rivers": "none"}}

    with pytest.raises(IncompatibleCapabilitiesError, match="does not honor solver.sink_fill"):
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)


# --- 3. a restart beside a computed start ------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "fragment"),
    [
        (
            "steady_state",
            "flow.restart_from is set and flow.ic.kind = 'steady_state' computes its own "
            "initial heads, which would overwrite the restart without a message.",
        ),
        (
            "spinup_cyclic",
            "flow.restart_from is set and flow.ic.kind = 'spinup_cyclic' computes",
        ),
    ],
)
def test_restart_beside_a_computed_start(tmp_path: Path, kind: str, fragment: str) -> None:
    extra = {"flow": {"restart_from": "runs/a/fields.zarr", "ic": {"kind": kind}}}

    with pytest.raises(ConfigValidationError) as caught:
        _load(tmp_path, extra)

    assert caught.value.code == "HMPY.E101"
    assert fragment in str(caught.value)


def test_a_restart_beside_a_head_rule_loads(tmp_path: Path) -> None:
    _load(tmp_path, {"flow": {"restart_from": "runs/a/fields.zarr", "ic": {"kind": "top"}}})


def test_the_contaminations_are_the_pairs_refused_here() -> None:
    assert set(CONTAMINATIONS) == {"restart_beside_a_computed_start"}


# --- 4. a lake under a cyclic start ------------------------------------------------------


def test_lake_under_a_cyclic_start(tmp_path: Path) -> None:
    """Each cycle starts from the final stages of the cycle before, so the lake settles."""
    _load(
        tmp_path,
        {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}, "ic": {"kind": "spinup_cyclic"}}},
    )

    assert "lake_under_a_cyclic_start" not in CONTAMINATIONS
    assert "cyclic_spinup_restarted_the_lake" in {
        row.id for row in (*REGISTER.bugs, *REGISTER.recipes)
    }


# --- 5. a soil settled on its first year beside a cyclic aquifer -------------------------


def test_soil_first_year_beside_a_cyclic_aquifer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The two starts come from two windows, which a study may want: it is allowed."""
    extra = {**SOIL, "flow": {**SOIL["flow"], "ic": {"kind": "spinup_cyclic"}}}

    with caplog.at_level(logging.WARNING):
        cfg = _load(tmp_path, extra)

    assert cfg.flow.sinks_sources.recharge.soil.spinup == "first_year"
    assert cfg.flow.ic.h.kind == "spinup_cyclic"
    assert [record for record in caplog.records if "spinup" in record.getMessage()] == []
    page = REPO / "docs" / "source" / "theory" / "soil-reservoir.md"
    assert "(soil-start)=" in page.read_text(encoding="utf-8")


# --- the two remedies of a depression ----------------------------------------------------


def test_the_two_depression_remedies_are_refused_together(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as caught:
        _load(tmp_path, {"solver": {"sink_fill": True, "drain_band_depth_m": 0.5}})

    assert "solver.sink_fill and solver.drain_band_depth_m" in str(caught.value)
    assert "Keep one." in str(caught.value)


@pytest.mark.parametrize(
    "solver",
    [
        {"sink_fill": True},
        {"drain_band_depth_m": 0.5},
        {"sink_fill": True, "drain_band_depth_m": 0.0},
    ],
    ids=["fill alone", "band alone", "fill beside a zero band"],
)
def test_each_depression_remedy_alone_loads(tmp_path: Path, solver: dict[str, Any]) -> None:
    _load(tmp_path, {"solver": solver})


# --- the lumped mesh, refused by every flow that does not read it ------------------------


@pytest.mark.parametrize("backend", FLOWS)
def test_a_flow_reads_the_catchment_engine_only_if_it_names_it(
    tmp_path: Path, backend: str
) -> None:
    reads_it = "catchment" in solvers.get("flow", backend).accepted_meshes
    document = _document({"mesh": {"engine": "catchment"}}, backend)

    if reads_it:
        # A lumped solver reads no head rule, only a steady start.
        document["flow"] = {"ic": {"kind": "steady_state"}}
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)
        return
    with pytest.raises(ConfigValidationError) as caught:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)

    assert f"solver {backend!r} reads the meshes of the engines" in str(caught.value)
    assert "mesh.engine is 'catchment'" in str(caught.value)


def test_the_lumped_engine_is_read_by_the_linear_reservoir_alone() -> None:
    readers = [n for n in FLOWS if "catchment" in solvers.get("flow", n).accepted_meshes]

    assert readers == ["linear_reservoir"]


# --- the soil reservoir ------------------------------------------------------------------


def _soil_with(**changes: Any) -> dict[str, Any]:
    """Return the soil document with the given top-level sections replaced."""
    return {**SOIL, **changes}


SOIL_REFUSALS = [
    pytest.param(
        _soil_with(
            flow={
                "first_period_steady": False,
                "sinks_sources": {"recharge": {"enabled": False, "soil": {"ru": "150 mm"}}},
            }
        ),
        "computes a recharge and its table says enabled = false",
        id="recharge switched off",
    ),
    pytest.param(
        _soil_with(flow={**SOIL["flow"], "first_period_steady": True}),
        "flow.first_period_steady = true solves the first stress period",
        id="steady first period",
    ),
    pytest.param(
        _soil_with(
            simulation={
                "time": {
                    "start_datetime": "2015-01-01",
                    "end_datetime": "2015-06-30",
                    "step_value": "1 day",
                }
            }
        ),
        "extend the run to 52 weeks at least",
        id="run shorter than a year",
    ),
    pytest.param(
        _soil_with(
            flow={
                "first_period_steady": False,
                "sinks_sources": {"recharge": {"soil": {"ru": "150 mm", "spinup": "sometimes"}}},
            }
        ),
        'write "first_year" to repeat the first year',
        id="a spin-up that is not a start",
    ),
    pytest.param(
        _soil_with(
            data={
                **SOIL["data"],
                "types": ["precipitation", "etp", "recharge"],
                "recharge": {"sources": [{"source": "sim2", "extent": "watershed"}]},
            }
        ),
        "data.types also loads one from [data.recharge]",
        id="a loaded recharge beside the soil",
    ),
    pytest.param(
        _soil_with(
            data={
                **SOIL["data"],
                "precipitation": {
                    "sources": [{"source": "sim2", "extent": "watershed", "components": ["liquid"]}]
                },
            }
        ),
        "the soil reservoir takes one precipitation grid",
        id="precipitation in parts",
    ),
    pytest.param(
        _soil_with(
            flow={
                **SOIL["flow"],
                "bc": {"drainage": {}},
                "sinks_sources": {
                    **SOIL["flow"]["sinks_sources"],
                    "lakes": {"lac": LAKE},
                },
            }
        ),
        "declares a lake with no stream network",
        id="a lake with no stream network",
    ),
]


@pytest.mark.parametrize(("extra", "fragment"), SOIL_REFUSALS)
def test_a_soil_reservoir_is_refused_with_the_key_to_change(
    tmp_path: Path, extra: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ConfigValidationError) as caught:
        _load(tmp_path, extra)

    assert caught.value.code == "HMPY.E101"
    assert fragment in str(caught.value)


@pytest.mark.parametrize(
    "backend", [name for name in FLOWS if "soil" not in solvers.get("flow", name).supports]
)
def test_a_flow_that_does_not_read_the_soil_refuses_it_by_name(
    tmp_path: Path, backend: str
) -> None:
    with pytest.raises(IncompatibleCapabilitiesError, match="soil"):
        _load(tmp_path, SOIL, backend=backend)
