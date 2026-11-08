"""The checks that cross a document with its flow solver read ``supports`` and name no solver."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.cross_checks import (
    CONTAMINATIONS,
    TRAIT_USES,
    check_against_the_solver,
    refuse_a_transport_its_flow_does_not_feed,
    refuse_the_contaminations,
    refuse_the_traits_the_solver_ignores,
    traits_of,
    uses_of,
    warn_on_a_coarse_conductivity_profile,
)
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.model.supports import SUPPORTS
from hydromodpy.solver.base.registry import solvers

SHIPPED_FLOWS = ("boussinesq", "modflow6", "modflow_nwt")
LAKE = {"bedleak": 0.1, "initial_stage": "85 m"}
WALL = {"line": [[0.0, 0.0], [10.0, 0.0]], "depths": [5.0], "hydchr": 1e-9}
K_FIELD = {"kind": "homogeneous", "value": "1e-5 m/s"}
PROFILE = {"kind": "exponential", "characteristic_depth": "15 m"}
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

# One row per trait: a document that uses it under MODFLOW 6, and what the refusal
# names as written by the file.
TRAIT_ROWS: dict[str, tuple[dict[str, Any], str]] = {
    "west_side": ({"flow": {"bc": {"west_side": {"value": "10 m"}}}}, "flow.bc.west_side"),
    "east_side": ({"flow": {"bc": {"east_side": {"value": "10 m"}}}}, "flow.bc.east_side"),
    "north_side": ({"flow": {"bc": {"north_side": {"value": "10 m"}}}}, "flow.bc.north_side"),
    "south_side": ({"flow": {"bc": {"south_side": {"value": "10 m"}}}}, "flow.bc.south_side"),
    "stream": ({"flow": {"bc": {"stream": {"value": "10 m"}}}}, "flow.bc.stream"),
    "ocean": ({"flow": {"bc": {"ocean": {"value": "0 m"}}}}, "flow.bc.ocean"),
    "drainage": ({"flow": {"bc": {"drainage": {}}}}, "flow.bc.drainage"),
    "lake": ({"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}}}, "flow.sinks_sources.lakes"),
    "sfr": (
        {"flow": {"bc": {"drainage": {}}, "sinks_sources": {"sfr": {"main": {}}}}},
        "flow.sinks_sources.sfr",
    ),
    "sink_fill": ({"solver": {"sink_fill": True}}, "solver.sink_fill"),
    "drain_band_depth_m": ({"solver": {"drain_band_depth_m": 0.5}}, "solver.drain_band_depth_m"),
    "drain_bed_thickness_m": (
        {"solver": {"drain_bed_thickness_m": 0.5}},
        "solver.drain_bed_thickness_m",
    ),
    "drain_conductance_floor_m2_s": (
        {"solver": {"drain_conductance_floor_m2_s": 1e-10}},
        "solver.drain_conductance_floor_m2_s",
    ),
    "head_rule": ({"flow": {"ic": {"kind": "bottom"}}}, "flow.ic.kind = 'bottom'"),
    "steady_start": ({"flow": {"ic": {"kind": "steady_state"}}}, "flow.ic.kind = 'steady_state'"),
    "cyclic_start": ({"flow": {"ic": {"kind": "spinup_cyclic"}}}, "flow.ic.kind = 'spinup_cyclic'"),
    "prior_state": ({"flow": {"restart_from": "runs/spinup/fields.zarr"}}, "flow.restart_from"),
    "recharge": ({"flow": {"sinks_sources": {"recharge": {}}}}, "flow.sinks_sources.recharge"),
    "wells": (
        {
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
        "flow.sinks_sources.wells",
    ),
    "etp": ({"flow": {"sinks_sources": {"etp": {}}}}, "flow.sinks_sources.etp"),
    "flow_barriers": (
        {"flow": {"sinks_sources": {"flow_barriers": {"wall": WALL}}}},
        "flow.sinks_sources.flow_barriers",
    ),
    "cutoff_wall": (
        {"flow": {"sinks_sources": {"lakes": {"lac": {**LAKE, "cutoff_wall": WALL}}}}},
        "flow.sinks_sources.lakes.lac.cutoff_wall",
    ),
    "soil": (SOIL, "flow.sinks_sources.recharge.soil"),
    "k_tensor": (
        {
            "flow": {
                "param_list": ["K", "K22"],
                "param": {"K": {"field": K_FIELD}, "K22": {"field": K_FIELD}},
            }
        },
        "flow.param.K22",
    ),
    "layers": (
        {"domain": {"layers": {"nlay": 3}}},
        "domain.layers (genmtd_lay = 'constant', 3 layer(s))",
    ),
    "pass_through": (SURFACES, "domain.layers.pinch_out = 'pass_through'"),
}


def _load(tmp_path: Path, extra: dict[str, Any], *, sealed: bool = False) -> HydroModPyConfig:
    (tmp_path / "weathered.tif").touch()
    document = {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **extra,
        "solver": {"backend": "modflow6", **extra.get("solver", {})},
    }
    return HydroModPyConfig.from_dict(document, base_dir=tmp_path, sealed=sealed)


def _under(cfg: HydroModPyConfig, backend: str) -> HydroModPyConfig:
    """The same validated document with another flow solver, not validated again."""
    return cfg.model_copy(update={"solver": cfg.solver.model_copy(update={"backend": backend})})


def _honoring(trait: str) -> str:
    names = [name for name in solvers.names("flow") if trait in solvers.get("flow", name).supports]
    return f"({', '.join(names)})"


def test_the_trait_table_and_the_rows_here_cover_the_closed_set() -> None:
    assert set(TRAIT_USES) == SUPPORTS
    assert set(TRAIT_ROWS) == SUPPORTS


@pytest.mark.parametrize("trait", sorted(TRAIT_ROWS))
def test_each_trait_is_found_with_what_the_file_wrote(tmp_path: Path, trait: str) -> None:
    extra, where = TRAIT_ROWS[trait]
    cfg = _load(tmp_path, extra)

    assert uses_of(cfg)[trait] == where
    assert trait in traits_of(cfg)


def test_a_default_document_uses_the_head_rule_alone(tmp_path: Path) -> None:
    assert traits_of(_load(tmp_path, {})) == {"head_rule"}


@pytest.mark.parametrize("backend", SHIPPED_FLOWS)
@pytest.mark.parametrize("trait", sorted(TRAIT_ROWS))
def test_a_trait_passes_if_and_only_if_the_solver_lists_it(
    tmp_path: Path, trait: str, backend: str
) -> None:
    extra, where = TRAIT_ROWS[trait]
    cfg = _under(_load(tmp_path, extra), backend)
    if trait in solvers.get("flow", backend).supports:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)
        return
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)

    message = str(excinfo.value)
    assert f"solver.backend = {backend!r} does not honor {where}: it would be ignored" in message
    assert f"run a flow solver that honors it {_honoring(trait)}." in message


def test_the_sentence_of_the_design_reads_as_written(tmp_path: Path) -> None:
    cfg = _under(_load(tmp_path, {"solver": {"sink_fill": True}}), "boussinesq")

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)

    assert str(excinfo.value) == (
        "solver.backend = 'boussinesq' does not honor solver.sink_fill: it would be ignored "
        "without a word. Remove it, or run a flow solver that honors it (modflow6, modflow_nwt)."
    )


def test_every_ignored_key_is_named_at_once(tmp_path: Path) -> None:
    cfg = _under(
        _load(
            tmp_path,
            {"solver": {"drain_band_depth_m": 0.5}, "flow": {"sinks_sources": {"etp": {}}}},
        ),
        "boussinesq",
    )

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)

    assert "solver.drain_band_depth_m" in str(excinfo.value)
    assert "flow.sinks_sources.etp" in str(excinfo.value)


def test_a_trait_no_solver_honors_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("modflow6", "modflow_nwt"):
        flow = solvers.get("flow", name)
        monkeypatch.setattr(flow, "supports", flow.supports - {"sink_fill"})
    cfg = _under(_load(tmp_path, {}), "boussinesq")
    cfg = cfg.model_copy(update={"solver": cfg.solver.model_copy(update={"sink_fill": True})})

    with pytest.raises(IncompatibleCapabilitiesError, match="no flow solver of this installation"):
        refuse_the_traits_the_solver_ignores(cfg, sealed=False)


def test_a_document_read_through_the_root_is_refused_by_the_same_rule(tmp_path: Path) -> None:
    extra = {"solver": {"backend": "boussinesq", "sink_fill": True}}
    extra["mesh"] = {"engine": "triangle", "families": {"rivers": "none"}}
    document = {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **extra,
    }

    with pytest.raises(IncompatibleCapabilitiesError, match="does not honor solver.sink_fill"):
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)


def _with_transport(cfg: HydroModPyConfig, transport: str) -> HydroModPyConfig:
    process = [
        {"id": "flow_main", "kind": "flow", "solvers": [cfg.solver.backend_name]},
        {"id": "transport_main", "kind": "transport", "solvers": [transport]},
    ]
    simulation = cfg.simulation.model_copy(
        update={"process": type(cfg.simulation).model_validate({"process": process}).process}
    )
    return cfg.model_copy(update={"simulation": simulation})


@pytest.mark.parametrize(
    ("backend", "transport", "refused"),
    [
        ("modflow6", "modflow6", False),
        ("modflow6", "modflow6_prt", False),
        ("modflow6", "modpath", True),
        ("modflow6", "mt3dms", True),
        ("modflow_nwt", "modpath", False),
        ("modflow_nwt", "mt3dms", False),
        ("modflow_nwt", "modflow6", True),
        ("boussinesq", "modpath", True),
        ("boussinesq", "modflow6_prt", True),
    ],
)
def test_a_transport_follows_the_flows_its_requires_names(
    tmp_path: Path, backend: str, transport: str, refused: bool
) -> None:
    cfg = _with_transport(_under(_load(tmp_path, {}), backend), transport)
    if not refused:
        refuse_a_transport_its_flow_does_not_feed(cfg, sealed=False)
        return
    followed = ", ".join(
        name for kind, name in solvers.get("transport", transport).requires if kind == "flow"
    )
    with pytest.raises(ValueError) as excinfo:
        refuse_a_transport_its_flow_does_not_feed(cfg, sealed=False)

    assert str(excinfo.value).startswith(
        f"the transport solver {transport!r} follows {followed}, and solver.backend is {backend!r}"
    )


def test_a_transport_that_requires_no_flow_follows_any(tmp_path: Path, isolated_solvers) -> None:
    from tests._helpers.fake_solvers import fake_adapter

    isolated_solvers.solvers.register(
        fake_adapter("free_transport", process_type="transport", reads=("face_flow",))
    )
    cfg = _with_transport(_under(_load(tmp_path, {}), "boussinesq"), "free_transport")

    refuse_a_transport_its_flow_does_not_feed(cfg, sealed=False)


@pytest.mark.parametrize(
    ("row", "extra", "fragment"),
    [
        (
            "restart_beside_a_computed_start",
            {"flow": {"restart_from": "runs/a/fields.zarr", "ic": {"kind": "steady_state"}}},
            "flow.restart_from is set and flow.ic.kind = 'steady_state' computes its own initial "
            "heads, which would overwrite the restart without a message.",
        ),
        (
            "restart_beside_a_computed_start",
            {"flow": {"restart_from": "runs/a/fields.zarr", "ic": {"kind": "spinup_cyclic"}}},
            "flow.restart_from is set and flow.ic.kind = 'spinup_cyclic' computes",
        ),
        (
            "lake_under_a_cyclic_start",
            {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}, "ic": {"kind": "spinup_cyclic"}}},
            "flow.sinks_sources.lakes declares a lake and flow.ic.kind = 'spinup_cyclic' repeats "
            "the run until the heads settle. The cycle carries the heads and not the lake stage",
        ),
    ],
)
def test_each_contamination_is_refused_with_its_two_keys(
    tmp_path: Path, row: str, extra: dict[str, Any], fragment: str
) -> None:
    assert row in CONTAMINATIONS
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, extra)

    assert fragment in str(excinfo.value)


def test_the_lake_row_names_the_way_out(tmp_path: Path) -> None:
    cfg = _load(tmp_path, {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}}})
    cyclic = _load(tmp_path, {"flow": {"ic": {"kind": "spinup_cyclic"}}})
    cfg = cfg.model_copy(update={"flow": cfg.flow.model_copy(update={"ic": cyclic.flow.ic})})

    with pytest.raises(ValueError) as excinfo:
        refuse_the_contaminations(cfg, sealed=False)

    assert "Run hmp spinup, which carries both" in str(excinfo.value)
    assert "flow.restart_from" in str(excinfo.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"flow": {"restart_from": "runs/a/fields.zarr", "ic": {"kind": "top"}}},
        {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}, "ic": {"kind": "steady_state"}}},
        {
            "flow": {
                "sinks_sources": {"lakes": {"lac": {**LAKE, "enabled": False}}},
                "ic": {"kind": "spinup_cyclic"},
            }
        },
    ],
    ids=["restart-from-a-head-rule", "lake-from-a-steady-start", "switched-off-lake-cycled"],
)
def test_a_pair_that_does_not_spoil_loads(tmp_path: Path, extra: dict[str, Any]) -> None:
    _load(tmp_path, extra)


def test_a_sealed_document_warns_for_every_refusal_and_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extra = {
        "solver": {"backend": "modflow_nwt", "sink_fill": True},
        "flow": {
            "restart_from": "runs/a/fields.zarr",
            "ic": {"kind": "steady_state"},
            "sinks_sources": {"lakes": {"lac": LAKE}},
        },
        "simulation": {
            "process": [
                {"id": "flow_main", "kind": "flow", "solvers": ["modflow_nwt"]},
                {"id": "particles", "kind": "transport", "solvers": ["modflow6_prt"]},
            ]
        },
    }
    document = {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **extra,
    }

    with caplog.at_level(logging.WARNING):
        cfg = HydroModPyConfig.from_dict(document, base_dir=tmp_path, sealed=True)

    assert cfg.read_as_sealed
    assert "does not honor flow.restart_from" in caplog.text
    assert "the transport solver 'modflow6_prt' follows modflow6" in caplog.text
    assert "would overwrite the restart" in caplog.text
    assert caplog.text.count("This sealed run is read as it ran.") == 3


def test_a_live_document_is_not_sealed(tmp_path: Path) -> None:
    assert not _load(tmp_path, {}).read_as_sealed


def test_an_assignment_on_a_sealed_config_keeps_it_sealed(tmp_path: Path) -> None:
    extra = {"solver": {"backend": "modflow_nwt"}, "flow": {"restart_from": "runs/a/fields.zarr"}}
    document = {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **extra,
    }
    cfg = HydroModPyConfig.from_dict(document, base_dir=tmp_path, sealed=True)

    cfg.flow = cfg.flow

    assert cfg.read_as_sealed


@pytest.mark.parametrize(
    ("sealed", "refused"),
    [(False, True), (True, False)],
    ids=["live-refuses", "sealed-warns"],
)
def test_a_change_keeps_the_seal_of_the_document(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, sealed: bool, refused: bool
) -> None:
    cfg = _load(tmp_path, {"solver": {"backend": "modflow_nwt"}}, sealed=sealed)
    change = {"flow.ic.kind": "spinup_cyclic"}

    if refused:
        with pytest.raises(IncompatibleCapabilitiesError, match="flow.ic.kind"):
            cfg.with_changes(change)
        return
    with caplog.at_level(logging.WARNING):
        changed = cfg.with_changes(change)
    assert changed.read_as_sealed
    assert changed.flow.ic.h.kind == "spinup_cyclic"
    assert "This sealed run is read as it ran." in caplog.text


@pytest.mark.parametrize(
    ("backend", "layers", "expected", "absent"),
    [
        ("boussinesq", 1, "boussinesq solves one layer and reads one K per column", "five layers"),
        ("modflow6", 2, "Use at least five layers", "one K per column"),
        ("modflow_nwt", 4, "Use at least five layers", "one K per column"),
        ("modflow6", 5, None, "five layers"),
    ],
)
def test_a_vertical_k_profile_is_warned_about_where_it_is_not_read_in_full(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    layers: int,
    expected: str | None,
    absent: str,
) -> None:
    extra = {
        "domain": {"layers": {"nlay": layers}},
        "flow": {
            "param_list": ["K"],
            "param": {"K": {"field": K_FIELD, "field_vertical_profile": PROFILE}},
        },
    }
    cfg = _under(_load(tmp_path, extra), backend)
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        warn_on_a_coarse_conductivity_profile(cfg)

    if expected is not None:
        assert expected in caplog.text
    assert absent not in caplog.text


def test_the_checks_run_in_order_and_the_solver_comes_first(tmp_path: Path) -> None:
    """A lake under a solver without lakes is named for that, before the pair it is in."""
    cfg = _load(tmp_path, {"flow": {"sinks_sources": {"lakes": {"lac": LAKE}}}})
    cyclic = _load(tmp_path, {"flow": {"ic": {"kind": "spinup_cyclic"}}})
    cfg = _under(
        cfg.model_copy(update={"flow": cfg.flow.model_copy(update={"ic": cyclic.flow.ic})}),
        "modflow_nwt",
    )

    with pytest.raises(
        IncompatibleCapabilitiesError, match="does not honor flow.sinks_sources.lakes"
    ):
        check_against_the_solver(cfg, sealed=False)
