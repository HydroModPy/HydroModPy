"""The checks that cross a document with its flow solver read ``supports`` and name no solver."""

from __future__ import annotations

import ast
import inspect
import logging
import re
import textwrap
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig, cross_checks
from hydromodpy.config.cross_checks import (
    CONTAMINATIONS,
    CROSS_RULES,
    TRAIT_USES,
    check_against_the_solver,
    coarse_conductivity_profile,
    refuse_a_transport_its_flow_does_not_feed,
    refuse_an_export_that_cannot_be_written,
    refuse_the_contaminations,
    refuse_the_reads_the_flow_does_not_write,
    refuse_the_traits_the_solver_ignores,
    run_cross_rules,
    traits_of,
    uses_of,
)
from hydromodpy.config.section_loader import SECTIONS
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigValidationError,
    HydroModPyError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.model.supports import SUPPORTS
from hydromodpy.results.exporters.export_spec import ExportKind, ExportRequest
from hydromodpy.results.exporters.vocabulary import static_export_names
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
    "properties": ({"flow": {"param": {"K": {"field": K_FIELD}}}}, "flow.param"),
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


def _register_a_flow_and_a_greedy_transport(
    isolated_solvers: object,
    *,
    writes: tuple[str, ...],
    reads: tuple[str, ...],
    flow_name: str = "writer",
) -> str:
    """Register a fake flow backend that writes *writes*, and a transport that reads *reads*."""
    from tests._helpers.fake_solvers import fake_adapter

    flow = fake_adapter(flow_name, process_type="flow", writes=writes, reads=())
    transport = fake_adapter(
        "greedy_transport",
        process_type="transport",
        reads=reads,
        requires=(("flow", flow_name),),
    )
    isolated_solvers.solvers.register(flow)
    isolated_solvers.solvers.register(transport)
    return flow_name


def test_a_transport_whose_read_the_flow_does_not_write_is_refused(
    tmp_path: Path, isolated_solvers: object
) -> None:
    """The rule of the reads: a product the flow does not write is refused while the file is read."""
    flow_name = _register_a_flow_and_a_greedy_transport(
        isolated_solvers, writes=(), reads=("face_flow",)
    )
    cfg = _with_transport(_under(_load(tmp_path, {}), flow_name), "greedy_transport")

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        refuse_the_reads_the_flow_does_not_write(cfg, sealed=False)

    message = str(excinfo.value)
    assert "the transport solver 'greedy_transport' reads face_flow, and solver.backend" in message
    assert "does not write it" in message


def test_a_transport_that_reads_a_product_nobody_writes_names_no_flow(
    tmp_path: Path, isolated_solvers: object
) -> None:
    """A product no flow solver writes is refused, and the message says so."""
    flow_name = _register_a_flow_and_a_greedy_transport(
        isolated_solvers,
        writes=("face_flow",),
        reads=("particle_pollock/exit_solve",),
    )
    cfg = _with_transport(_under(_load(tmp_path, {}), flow_name), "greedy_transport")

    with pytest.raises(IncompatibleCapabilitiesError, match="writes it"):
        refuse_the_reads_the_flow_does_not_write(cfg, sealed=False)


def test_a_transport_whose_reads_the_flow_writes_passes_the_read(
    tmp_path: Path, isolated_solvers: object
) -> None:
    """A flow that writes face_flow carries a transport that reads it."""
    flow_name = _register_a_flow_and_a_greedy_transport(
        isolated_solvers, writes=("face_flow",), reads=("face_flow",)
    )
    cfg = _with_transport(_under(_load(tmp_path, {}), flow_name), "greedy_transport")

    refuse_the_reads_the_flow_does_not_write(cfg, sealed=False)


def test_a_sealed_document_whose_read_is_not_written_warns_and_reads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, isolated_solvers: object
) -> None:
    """The refusal of reads ways a sealed document as the other refusals do: a warning."""
    flow_name = _register_a_flow_and_a_greedy_transport(
        isolated_solvers, writes=(), reads=("face_flow",)
    )
    cfg = _with_transport(_under(_load(tmp_path, {}), flow_name), "greedy_transport")

    with caplog.at_level(logging.WARNING):
        refuse_the_reads_the_flow_does_not_write(cfg, sealed=True)

    assert "reads face_flow" in caplog.text
    assert "This sealed run is read as it ran." in caplog.text


def test_a_shipped_transport_whose_reads_the_shipped_flow_does_not_write_is_refused(
    tmp_path: Path,
) -> None:
    """MT3DMS behind Boussinesq is refused because Boussinesq does not write face_flow."""
    cfg = _with_transport(_under(_load(tmp_path, {}), "boussinesq"), "mt3dms")

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        refuse_the_reads_the_flow_does_not_write(cfg, sealed=False)

    message = str(excinfo.value)
    assert (
        "the transport solver 'mt3dms' reads face_flow, and solver.backend = 'boussinesq' does not write it"
        in message
    )
    assert "Run the flow with a solver that writes it (modflow6, modflow_nwt)." in message


def test_a_shipped_transport_whose_reads_the_shipped_flow_writes_passes_the_read(
    tmp_path: Path,
) -> None:
    """MT3DMS behind MODFLOW-NWT passes because MODFLOW-NWT writes face_flow."""
    cfg = _with_transport(_under(_load(tmp_path, {}), "modflow_nwt"), "mt3dms")
    refuse_the_reads_the_flow_does_not_write(cfg, sealed=False)


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

    said = " ".join(coarse_conductivity_profile(cfg))

    if expected is not None:
        assert expected in said
    assert absent not in said


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


class _ADocument:
    """A document as the rules read it, built by hand and not by the loader.

    The rules read a validated document through its attributes alone: the
    solver the run builds, the flow regime, the families the mesh file wrote
    and the time section. A document built here carries the same attributes
    with the values the card of the test needs, so a rule is tested without
    loading the sources a real file would name.
    """

    def __init__(
        self,
        *,
        backend: str = "modflow6",
        engine: str = "catchment",
        families_written: tuple[str, ...] = (),
        rivers: str = "cell",
        county_point_method: str | None = None,
    ) -> None:
        from types import SimpleNamespace

        solver = SimpleNamespace(backend_name=backend)
        recharge = None
        if county_point_method is not None:
            recharge = SimpleNamespace(
                model_fields_set={"interpolation_method"},
                interpolation_method=county_point_method,
            )
        families = SimpleNamespace(
            model_fields_set=set(families_written),
            rivers=rivers,
            geology="face",
            lakes="face",
            barriers="face",
            watershed_boundary="none",
        )
        self.solver = solver
        self.flow = SimpleNamespace(
            flow_regime="transient",
            first_period_steady=False,
            sinks_sources=SimpleNamespace(recharge=recharge, etp=None),
        )
        self.mesh = SimpleNamespace(engine=engine, families=families, model_fields_set=set())
        self.simulation = SimpleNamespace(
            time=SimpleNamespace(
                start_datetime="2015-01-01",
                end_datetime="2015-03-01",
                step_value="30 day",
                step_unit="day",
            ),
        )


class TestNativeStepOfTheFlowSolver:
    def test_a_native_step_finer_than_a_transient_period_is_refused(self, isolated_solvers) -> None:
        from hydromodpy.config.cross_checks import refuse_a_native_step_finer_than_the_time_grid
        from tests._helpers.fake_solvers import fake_adapter

        isolated_solvers.solvers.register(fake_adapter("snail", native_step="1.5D"))
        cfg = _ADocument(backend="snail")

        with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
            refuse_a_native_step_finer_than_the_time_grid(cfg, sealed=False)

        message = str(excinfo.value)
        assert "snail" in message
        assert "1 days 12:00:00" in message
        assert "simulation.time.step_value" in message

    def test_a_native_step_as_long_as_the_periods_loads(self, isolated_solvers) -> None:
        from hydromodpy.config.cross_checks import refuse_a_native_step_finer_than_the_time_grid
        from tests._helpers.fake_solvers import fake_adapter

        isolated_solvers.solvers.register(fake_adapter("steady", native_step="30D"))
        refuse_a_native_step_finer_than_the_time_grid(_ADocument(backend="steady"), sealed=False)

    def test_a_flow_without_a_native_step_is_never_refused(self, isolated_solvers) -> None:
        from hydromodpy.config.cross_checks import refuse_a_native_step_finer_than_the_time_grid

        refuse_a_native_step_finer_than_the_time_grid(_ADocument(backend="modflow6"), sealed=False)

    def test_a_native_step_on_a_steady_run_loads(self, isolated_solvers) -> None:
        from hydromodpy.config.cross_checks import refuse_a_native_step_finer_than_the_time_grid
        from tests._helpers.fake_solvers import fake_adapter

        isolated_solvers.solvers.register(fake_adapter("snail", native_step="1.5D"))
        cfg = _ADocument(backend="snail")
        cfg.flow.flow_regime = "steady"
        refuse_a_native_step_finer_than_the_time_grid(cfg, sealed=False)

    def test_a_calendar_alias_native_step_is_refused(self, isolated_solvers) -> None:
        from hydromodpy.config.cross_checks import refuse_a_native_step_finer_than_the_time_grid
        from tests._helpers.fake_solvers import fake_adapter

        isolated_solvers.solvers.register(fake_adapter("calendar", native_step="MS"))
        cfg = _ADocument(backend="calendar")

        with pytest.raises(IncompatibleCapabilitiesError, match="fixed frequency"):
            refuse_a_native_step_finer_than_the_time_grid(cfg, sealed=False)


class TestAnIgnoredFamilyWritten:
    def test_a_family_the_engine_ignores_written_with_a_value_is_refused(self) -> None:
        from hydromodpy.config.cross_checks import refuse_an_ignored_family_written

        cfg = _ADocument(families_written=("rivers",))

        with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
            refuse_an_ignored_family_written(cfg, sealed=False)

        message = str(excinfo.value)
        assert "[mesh.families] rivers" in message
        assert "mesh engine 'catchment'" in message

    def test_a_family_written_to_none_is_kept(self) -> None:
        from hydromodpy.config.cross_checks import refuse_an_ignored_family_written

        cfg = _ADocument(families_written=("rivers",), rivers="none")

        refuse_an_ignored_family_written(cfg, sealed=False)

    def test_a_family_the_file_does_not_write_is_kept(self) -> None:
        from hydromodpy.config.cross_checks import refuse_an_ignored_family_written

        refuse_an_ignored_family_written(_ADocument(), sealed=False)

    def test_a_family_an_engine_that_meshes_it_reads(self) -> None:
        from hydromodpy.config.cross_checks import refuse_an_ignored_family_written

        refuse_an_ignored_family_written(
            _ADocument(engine="triangle", families_written=("rivers",)), sealed=False
        )


class TestAPointMethodUnderALumpedMesh:
    def test_a_point_method_written_for_the_recharge_is_refused(self) -> None:
        from hydromodpy.config.cross_checks import (
            refuse_a_point_method_under_a_lumped_mesh,
        )

        cfg = _ADocument(county_point_method="nearest")

        with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
            refuse_a_point_method_under_a_lumped_mesh(cfg, sealed=False)

        message = str(excinfo.value)
        assert "flow.sinks_sources.recharge.interpolation_method" in message
        assert "area" in message

    def test_a_point_method_written_to_area_loads(self) -> None:
        from hydromodpy.config.cross_checks import (
            refuse_a_point_method_under_a_lumped_mesh,
        )

        refuse_a_point_method_under_a_lumped_mesh(
            _ADocument(county_point_method="area"), sealed=False
        )

    def test_a_point_method_the_file_does_not_write_loads(self) -> None:
        from hydromodpy.config.cross_checks import (
            refuse_a_point_method_under_a_lumped_mesh,
        )

        refuse_a_point_method_under_a_lumped_mesh(_ADocument(), sealed=False)

    def test_a_point_method_for_a_triangulated_mesh_loads(self) -> None:
        from hydromodpy.config.cross_checks import (
            refuse_a_point_method_under_a_lumped_mesh,
        )

        refuse_a_point_method_under_a_lumped_mesh(
            _ADocument(engine="triangle", county_point_method="nearest"), sealed=False
        )


# ---------------------------------------------------------------------------
# The rules of the sections that read one another
# ---------------------------------------------------------------------------

SOLVER_ROWS = frozenset(
    {
        "refuse_the_traits_the_solver_ignores",
        "refuse_the_reads_the_flow_does_not_write",
        "refuse_an_ignored_family_written",
        "refuse_a_point_method_under_a_lumped_mesh",
        "refuse_a_native_step_finer_than_the_time_grid",
        "refuse_a_transport_its_flow_does_not_feed",
        "refuse_the_contaminations",
        "coarse_conductivity_profile",
    }
)
"""The rows the tests above drive by hand, with their own documents."""

ORDER = (
    "refuse_a_real_catchment_without_a_site",
    "refuse_a_station_other_than_the_gauge",
    "refuse_site_and_sites_together",
    "refuse_a_metrics_window_outside_the_run",
    "refuse_an_overview_without_its_section",
    "refuse_strict_inference_without_types",
    "refuse_conditioning_choices_on_a_conditioned_dem",
    "refuse_a_raster_depth_without_its_substratum",
    "refuse_a_river_mesh_without_a_threshold",
    "refuse_a_calibration_without_parameters",
    "refuse_the_traits_the_solver_ignores",
    "refuse_the_reads_the_flow_does_not_write",
    "refuse_an_ignored_family_written",
    "refuse_a_point_method_under_a_lumped_mesh",
    "refuse_a_native_step_finer_than_the_time_grid",
    "refuse_a_transport_its_flow_does_not_feed",
    "refuse_the_contaminations",
    "coarse_conductivity_profile",
    "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
    "refuse_a_soil_recharge_that_cannot_reach_the_streams",
    "refuse_soil_precipitation_in_parts",
    "refuse_a_soil_run_the_time_cannot_carry",
    "refuse_a_recharge_the_model_would_not_read",
    "refuse_a_soil_capacity_without_the_soil",
    "refuse_layer_bases_that_do_not_match",
    "refuse_an_angle_with_a_depth_profile",
    "refuse_a_solver_that_cannot_read_the_mesh",
    "refuse_a_cell_address_on_an_irregular_mesh",
    "refuse_a_time_the_run_does_not_hold",
    "refuse_an_export_that_cannot_be_written",
)
"""The order the loader always refused in: the first fault of a document is the first row."""


def _ns(**attributes: Any) -> SimpleNamespace:
    return SimpleNamespace(**attributes)


def _document(base: Any, **sections: Any) -> SimpleNamespace:
    """The sections of *base* with the ones given replaced, as a rule reads a document."""
    held = {name: getattr(base, name) for name in SECTIONS}
    return SimpleNamespace(**{**held, **sections})


@pytest.fixture(scope="module")
def documents(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """A plain document and a soil document, both loaded, so every rule passes them."""
    where = tmp_path_factory.mktemp("rules")
    return SimpleNamespace(plain=_load(where, {}), soil=_load(where, SOIL))


def _soil_flow(documents: SimpleNamespace, **attributes: Any) -> SimpleNamespace:
    """A flow section that holds the soil reservoir of the soil document, with *attributes*."""
    held = {
        "sinks_sources": documents.soil.flow.sinks_sources,
        "active_sinks_sources": ["recharge"],
        "active_bc": [],
        "flow_regime": "transient",
        "first_period_steady": False,
    }
    return _ns(**{**held, **attributes})


def _soil_time(documents: SimpleNamespace, end: str) -> Any:
    time = documents.soil.simulation.time.model_copy(
        update={"end_datetime": datetime.fromisoformat(end)}
    )
    return documents.soil.simulation.model_copy(update={"time": time})


def _with_export(documents: SimpleNamespace, **request: Any) -> SimpleNamespace:
    return _document(documents.soil, export=[ExportRequest(**request)])


# One row per refusal: the rule, the document that trips it, and what the refusal says.
ROWS: list[tuple[str, str, Any, str]] = [
    (
        "refuse_a_real_catchment_without_a_site",
        "dem",
        lambda d: _document(d.plain, site=None, sites=None, geographic=_ns(catch_def="dem")),
        "geographic.catchment.kind = 'dem' models a real catchment, and no [site] names it",
    ),
    (
        "refuse_a_station_other_than_the_gauge",
        "station",
        lambda d: _document(d.plain, site=_ns(gauge="A"), metrics=_ns(station="B")),
        "site.gauge = 'A' but metrics.station = 'B'",
    ),
    (
        "refuse_site_and_sites_together",
        "both",
        lambda d: _document(d.plain, site=_ns(), sites=_ns()),
        "[site] and [sites] are both declared",
    ),
    (
        "refuse_a_metrics_window_outside_the_run",
        "window",
        lambda d: _document(
            d.plain,
            metrics=_ns(window=_ns(start=date(2001, 1, 1), end=date(2001, 2, 1))),
            simulation=_ns(
                time=_ns(start_datetime=datetime(2015, 1, 1), end_datetime=datetime(2016, 1, 1))
            ),
        ),
        "[metrics] window runs from 2001-01-01 to 2001-02-01 and shares no day with "
        "[simulation.time], which runs from 2015-01-01 to 2016-01-01: the run would be "
        "scored on nothing",
    ),
    (
        "refuse_an_overview_without_its_section",
        "overview",
        lambda d: _document(d.plain, workflow=_ns(mode="overview"), overview=None),
        "workflow.mode = 'overview' needs an [overview] section",
    ),
    (
        "refuse_strict_inference_without_types",
        "strict",
        lambda d: _document(d.plain, data=_ns(inference_mode="strict", types=[])),
        "data.inference_mode='strict' requires at least one explicit data type in data.types",
    ),
    (
        "refuse_conditioning_choices_on_a_conditioned_dem",
        "conditioned",
        lambda d: _document(
            d.plain,
            data=_ns(dem=_ns(sources=[_ns(state="conditioned")])),
            geographic=_ns(
                model_fields_set={"dem_correc_type"},
                catchment=_ns(model_fields_set={"dem_resolution"}),
                crossings=_ns(enabled=True),
            ),
        ),
        "geographic.dem_correc_type, geographic.catchment.dem_resolution, "
        "geographic.crossings.enabled would be ignored in silence",
    ),
    (
        "refuse_a_raster_depth_without_its_substratum",
        "raster",
        lambda d: _document(
            d.plain,
            domain=_ns(depth_model=_ns(kind="raster_thickness")),
            data=_ns(substratum=None),
        ),
        "domain.depth_model kind = 'raster_thickness' reads the raster declared under "
        "[data.substratum]",
    ),
    (
        "refuse_a_river_mesh_without_a_threshold",
        "threshold",
        lambda d: _document(
            d.plain,
            geographic=_ns(
                uses_synthetic_geographic=lambda: False,
                river_network=_ns(
                    enabled=False,
                    missing_threshold_refusal=lambda *, needed_by: f"no threshold for {needed_by}",
                ),
            ),
            mesh=_ns(
                engine="triangle",
                triangle=None,
                families=_ns(rivers="cell"),
                requires_river_trace=lambda **_: True,
            ),
            flow=_ns(active_bc=["stream"]),
        ),
        "no threshold for [mesh] engine = 'triangle' with families.rivers = 'cell'",
    ),
    (
        "refuse_a_calibration_without_parameters",
        "calibration",
        lambda d: _document(d.plain, calibration=_ns(), flow=_ns(param_list=[])),
        "[calibration] requires flow.param_list to declare at least one tunable parameter",
    ),
    (
        "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
        "recharge loaded",
        lambda d: _document(
            d.soil, data=_ns(types=["recharge"], precipitation=object(), etp=object())
        ),
        "computes the recharge from the precipitation and the ETP",
    ),
    (
        "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
        "runoff loaded",
        lambda d: _document(
            d.soil, data=_ns(types=["runoff"], precipitation=object(), etp=object())
        ),
        "[data.runoff] loads a surface runoff that already takes its share",
    ),
    (
        "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
        "no precipitation",
        lambda d: _document(d.soil, data=_ns(types=[], precipitation=None, etp=object())),
        "no [data.precipitation] section says where to read it",
    ),
    (
        "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
        "no etp",
        lambda d: _document(d.soil, data=_ns(types=[], precipitation=object(), etp=None)),
        "no [data.etp] section says where to read it",
    ),
    (
        "refuse_a_soil_recharge_that_cannot_reach_the_streams",
        "switched off",
        lambda d: _document(d.soil, flow=_soil_flow(d, active_sinks_sources=["etp"])),
        "its table says enabled = false, so MODFLOW would receive none",
    ),
    (
        "refuse_a_soil_recharge_that_cannot_reach_the_streams",
        "lake without streams",
        lambda d: _document(d.soil, flow=_soil_flow(d, active_bc=["lake"])),
        "declares a lake with no stream network",
    ),
    (
        "refuse_a_soil_recharge_that_cannot_reach_the_streams",
        "drains not routed",
        lambda d: _document(
            d.soil,
            flow=_soil_flow(
                d,
                active_bc=["lake", "sfr"],
                sinks_sources=_ns(
                    recharge=d.soil.flow.sinks_sources.recharge,
                    sfr={"main": _ns(route_drainage=False)},
                ),
            ),
        ),
        "[flow.sinks_sources.sfr.main] sets route_drainage = false with a lake",
    ),
    (
        "refuse_soil_precipitation_in_parts",
        "two components",
        lambda d: _document(
            d.soil,
            data=_ns(precipitation=_ns(sources=[_ns(components=["rain", "snow"])]), types=[]),
        ),
        "[data.precipitation] loads components = ['rain', 'snow']",
    ),
    (
        "refuse_a_soil_run_the_time_cannot_carry",
        "no window",
        lambda d: _document(d.soil, simulation=_ns(time=None)),
        "runs day by day over [simulation.time], which this file does not declare",
    ),
    (
        "refuse_a_soil_run_the_time_cannot_carry",
        "run too short",
        lambda d: _document(d.soil, simulation=_soil_time(d, "2015-03-01")),
        "spinup",
    ),
    (
        "refuse_a_soil_run_the_time_cannot_carry",
        "drained first period",
        lambda d: _document(d.soil, flow=_soil_flow(d, first_period_steady=True)),
        "flow.first_period_steady = true solves the first stress period",
    ),
    (
        "refuse_a_recharge_the_model_would_not_read",
        "impossible rate",
        lambda d: _document(
            d.plain,
            flow=_ns(sinks_sources=_ns(recharge=_ns(peak_rate_mm_day=lambda: 1e6, values=[1e6]))),
        ),
        "flow.sinks_sources.recharge.values reaches 1e+06 mm/day",
    ),
    (
        "refuse_a_recharge_the_model_would_not_read",
        "replaced by a loaded series",
        lambda d: _document(
            d.plain,
            flow=_ns(sinks_sources=_ns(recharge=_ns(peak_rate_mm_day=lambda: 1.0, values=[1.0]))),
            data=_ns(types=["recharge"]),
        ),
        "would be replaced by the series [data.recharge] loads",
    ),
    (
        "refuse_a_soil_capacity_without_the_soil",
        "capacity",
        lambda d: _document(d.plain, data=_ns(soil_capacity=object(), types=[])),
        "[data.soil_capacity] is read only by the soil reservoir",
    ),
    (
        "refuse_layer_bases_that_do_not_match",
        "base not declared",
        lambda d: _document(
            d.plain,
            domain=_ns(layers=_ns(base_surface_names=["wb"])),
            data=_ns(layer_base=None),
        ),
        "[domain.layers] reads the base surfaces ['wb'], and [data.layer_base] does not declare",
    ),
    (
        "refuse_layer_bases_that_do_not_match",
        "base not read",
        lambda d: _document(
            d.plain,
            domain=_ns(layers=_ns(base_surface_names=[])),
            data=_ns(layer_base=_ns(sources=[_ns(name="wb")])),
        ),
        "[data.layer_base] declares ['wb'], and no layer of [domain.layers] reads them",
    ),
    (
        "refuse_an_angle_with_a_depth_profile",
        "angle",
        lambda d: _document(
            d.plain,
            flow=_ns(param={"angle1": _ns(field_vertical_profile=_ns(kind="exponential"))}),
        ),
        "flow.param.angle1 has a vertical profile, which would scale the angle with depth",
    ),
    (
        "refuse_a_solver_that_cannot_read_the_mesh",
        "nwt on triangles",
        lambda d: _document(
            d.plain,
            solver=_ns(backend_name="modflow_nwt"),
            mesh=_ns(engine="triangle", model_fields_set={"engine"}),
        ),
        "solver 'modflow_nwt' reads the meshes of the engines regular, and mesh.engine is "
        "'triangle'",
    ),
    (
        "refuse_a_cell_address_on_an_irregular_mesh",
        "well",
        lambda d: _document(
            d.plain,
            mesh=_ns(engine="triangle"),
            flow=_ns(
                sinks_sources=_ns(wells={"w1": _ns(location=_ns(kind="cell"))}, sfr={}),
            ),
        ),
        "A cell is addressed by [lay, row, col] at flow.sinks_sources.wells.w1.location",
    ),
    (
        "refuse_a_time_the_run_does_not_hold",
        "date outside the record",
        lambda d: _with_export(d, variables="head", time="2030-01-01"),
        "export[0].time: 2030-01-01 is outside the record",
    ),
    (
        "refuse_an_export_that_cannot_be_written",
        "unknown name",
        lambda d: _with_export(d, variables=["hed"]),
        "no run can export export[0]: 'hed'",
    ),
]


def test_the_rows_here_and_the_solver_rows_are_the_table() -> None:
    assert {rule for rule, *_ in ROWS} | SOLVER_ROWS == set(CROSS_RULES)


def test_the_rules_run_in_the_order_the_loader_refused_in() -> None:
    assert tuple(CROSS_RULES) == ORDER


@pytest.mark.parametrize(
    ("rule", "case", "build", "says"), ROWS, ids=[f"{r}:{c}" for r, c, *_ in ROWS]
)
def test_each_rule_refuses_the_document_that_trips_it(
    documents: SimpleNamespace, rule: str, case: str, build: Any, says: str
) -> None:
    document = build(documents)

    with pytest.raises((ValueError, HydroModPyError), match=re.escape(says)):
        CROSS_RULES[rule].rule(document, sealed=False)


@pytest.mark.parametrize("which", ["plain", "soil"])
def test_every_rule_passes_a_document_that_loads(documents: SimpleNamespace, which: str) -> None:
    outcomes = run_cross_rules(getattr(documents, which), sealed=False)

    assert [outcome.error for outcome in outcomes] == [None] * len(CROSS_RULES)
    assert [outcome.rule.name for outcome in outcomes] == list(ORDER)


def test_a_refusal_that_is_not_a_value_error_keeps_its_type(documents: SimpleNamespace) -> None:
    refused = [
        outcome
        for outcome in run_cross_rules(_with_export(documents, variables=["hed"]), sealed=False)
        if outcome.error is not None
    ]

    assert [type(outcome.error) for outcome in refused] == [ConfigError]
    assert refused[0].rule.name == "refuse_an_export_that_cannot_be_written"


def test_a_real_catchment_without_a_site_is_a_value_error_of_the_rule(
    documents: SimpleNamespace,
) -> None:
    document = _document(documents.plain, site=None, sites=None, geographic=_ns(catch_def="dem"))

    with pytest.raises(ValueError) as caught:
        CROSS_RULES["refuse_a_real_catchment_without_a_site"].rule(document, sealed=False)
    assert not isinstance(caught.value, ConfigError)


def test_a_site_or_a_sites_table_names_a_real_catchment(documents: SimpleNamespace) -> None:
    rule = CROSS_RULES["refuse_a_real_catchment_without_a_site"].rule
    for held in ({"site": _ns()}, {"sites": _ns()}):
        document = _document(
            documents.plain,
            **{"site": None, "sites": None, **held},
            geographic=_ns(catch_def="dem"),
        )
        rule(document, sealed=False)


def test_a_synthetic_domain_needs_no_site(documents: SimpleNamespace) -> None:
    document = _document(
        documents.plain, site=None, sites=None, geographic=_ns(catch_def="synthetic")
    )

    CROSS_RULES["refuse_a_real_catchment_without_a_site"].rule(document, sealed=False)


def test_a_station_that_is_the_gauge_passes(documents: SimpleNamespace) -> None:
    rule = CROSS_RULES["refuse_a_station_other_than_the_gauge"].rule
    for station in ("A", ["A", "B"], None):
        rule(
            _document(documents.plain, site=_ns(gauge="A"), metrics=_ns(station=station)),
            sealed=False,
        )


def test_a_sealed_document_is_not_checked_for_its_station(documents: SimpleNamespace) -> None:
    document = _document(documents.plain, site=_ns(gauge="A"), metrics=_ns(station="B"))

    CROSS_RULES["refuse_a_station_other_than_the_gauge"].rule(document, sealed=True)


def test_a_window_that_shares_a_day_with_the_run_passes(documents: SimpleNamespace) -> None:
    document = _document(
        documents.plain,
        metrics=_ns(window=_ns(start=date(2015, 12, 1), end=date(2016, 6, 1))),
        simulation=_ns(
            time=_ns(start_datetime=datetime(2015, 1, 1), end_datetime=datetime(2016, 1, 1))
        ),
    )

    assert CROSS_RULES["refuse_a_metrics_window_outside_the_run"].rule(document, sealed=False) == []


def test_a_sealed_window_outside_the_run_gives_a_warning_and_no_refusal(
    documents: SimpleNamespace,
) -> None:
    window = ROWS[3]
    document = window[2](documents)

    said = CROSS_RULES[window[0]].rule(document, sealed=True)

    assert len(said) == 1
    assert said[0].endswith("this sealed run has no score.")


@pytest.mark.parametrize(
    "rule", ["refuse_a_time_the_run_does_not_hold", "refuse_an_export_that_cannot_be_written"]
)
def test_a_sealed_document_only_warns_of_an_export_it_cannot_write(
    documents: SimpleNamespace, caplog: pytest.LogCaptureFixture, rule: str
) -> None:
    row = next(row for row in ROWS if row[0] == rule)
    document = row[2](documents)

    with caplog.at_level(logging.WARNING):
        CROSS_RULES[rule].rule(document, sealed=True)

    assert row[3] in caplog.text
    assert "This sealed run is read as it ran." in caplog.text


def test_a_soil_rule_leaves_a_document_without_the_soil_alone(documents: SimpleNamespace) -> None:
    for rule in (
        "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
        "refuse_a_soil_recharge_that_cannot_reach_the_streams",
        "refuse_soil_precipitation_in_parts",
        "refuse_a_soil_run_the_time_cannot_carry",
    ):
        document = _document(
            documents.plain,
            data=_ns(types=["recharge", "runoff"], precipitation=None, etp=None),
        )
        CROSS_RULES[rule].rule(document, sealed=False)


def test_a_loaded_recharge_beside_a_zero_rate_is_not_replaced(documents: SimpleNamespace) -> None:
    document = _document(
        documents.plain,
        flow=_ns(sinks_sources=_ns(recharge=_ns(peak_rate_mm_day=lambda: 0.0, values=[0.0]))),
        data=_ns(types=["recharge"]),
    )

    CROSS_RULES["refuse_a_recharge_the_model_would_not_read"].rule(document, sealed=False)


def test_the_soil_capacity_is_read_by_the_soil_reservoir(documents: SimpleNamespace) -> None:
    document = _document(documents.soil, data=_ns(soil_capacity=object(), types=[]))

    CROSS_RULES["refuse_a_soil_capacity_without_the_soil"].rule(document, sealed=False)


def test_a_layering_that_reads_what_the_layer_base_declares_passes(
    documents: SimpleNamespace,
) -> None:
    document = _document(
        documents.plain,
        domain=_ns(layers=_ns(base_surface_names=["wb"])),
        data=_ns(layer_base=_ns(sources=[_ns(name="wb")])),
    )

    CROSS_RULES["refuse_layer_bases_that_do_not_match"].rule(document, sealed=False)


def test_an_angle_without_a_profile_passes(documents: SimpleNamespace) -> None:
    document = _document(
        documents.plain,
        flow=_ns(param={"angle1": _ns(field_vertical_profile=_ns(kind="none"))}),
    )

    CROSS_RULES["refuse_an_angle_with_a_depth_profile"].rule(document, sealed=False)


@pytest.mark.parametrize("engine", ["regular", "triangle"])
def test_a_cell_address_passes_on_the_regular_mesh_and_a_coordinate_on_any(
    documents: SimpleNamespace, engine: str
) -> None:
    kind = "cell" if engine == "regular" else "absolute_xy"
    document = _document(
        documents.plain,
        mesh=_ns(engine=engine),
        flow=_ns(sinks_sources=_ns(wells={"w1": _ns(location=_ns(kind=kind))}, sfr={})),
    )

    CROSS_RULES["refuse_a_cell_address_on_an_irregular_mesh"].rule(document, sealed=False)


def test_a_solver_that_reads_the_engine_of_the_mesh_passes(documents: SimpleNamespace) -> None:
    document = _document(
        documents.plain,
        solver=_ns(backend_name="modflow_nwt"),
        mesh=_ns(engine="regular", model_fields_set={"engine"}),
    )

    CROSS_RULES["refuse_a_solver_that_cannot_read_the_mesh"].rule(document, sealed=False)


def test_the_walk_logs_the_warnings_before_a_refusal_and_raises_the_first_row(
    documents: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    outside = _ns(window=_ns(start=date(2001, 1, 1), end=date(2001, 2, 1)))
    sealed_window = documents.soil.model_copy(update={"metrics": outside})

    with caplog.at_level(logging.WARNING):
        check_against_the_solver(sealed_window, sealed=True)
    assert "this sealed run has no score." in caplog.text

    twice = sealed_window.model_copy(update={"site": _ns(gauge=None), "sites": _ns()})
    with pytest.raises(ValueError, match=re.escape("[site] and [sites] are both declared")):
        check_against_the_solver(twice, sealed=False)


def test_the_run_keeps_every_refusal_when_it_is_not_asked_to_stop(
    documents: SimpleNamespace,
) -> None:
    both = _document(
        documents.plain,
        site=_ns(gauge=None),
        sites=_ns(),
        data=documents.plain.data.model_copy(update={"inference_mode": "strict", "types": []}),
    )

    refused = [o.rule.name for o in run_cross_rules(both, sealed=False) if o.error is not None]

    assert refused == ["refuse_site_and_sites_together", "refuse_strict_inference_without_types"]


def _traits_region_reads() -> set[str]:
    """The sections the ``where`` of every trait reads: the text between its table and ``uses_of``."""
    source = inspect.getsource(cross_checks)
    start = source.index("class TraitUse:") - len("@dataclass(frozen=True)\n")
    region = ast.parse(source[start : source.index("def uses_of(")])
    return {
        node.attr
        for node in ast.walk(region)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cfg"
    }


READS_OF_HELPERS = {
    "_TimeOfTheRun": {"simulation", "flow"},
    "resolve_simulation_time_window": {"simulation"},
    "resolve_simulation_time_grid": {"simulation"},
    "require_flow_simulation_time_grid": {"simulation", "flow"},
}
"""The sections the helpers of ``core/time``, and the holder of the time of a walk, read of the document."""


def _sections_read(function: Any) -> set[str]:
    """The root sections *function* reads of its first argument, found in its source.

    A section is read by ``cfg.<name>`` or ``getattr(cfg, "<name>")``. A helper that
    receives the whole document is followed into this module, or read in
    ``READS_OF_HELPERS``, and an unknown helper stops the test.
    """
    node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    document = node.args.args[0].arg
    read: set[str] = set()
    for item in ast.walk(node):
        if (
            isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == document
        ):
            read.add(item.attr)
        if not (isinstance(item, ast.Call) and isinstance(item.func, ast.Name)):
            continue
        callee, args = item.func.id, item.args
        takes_it = any(isinstance(arg, ast.Name) and arg.id == document for arg in args)
        if callee == "getattr" and takes_it and isinstance(args[1], ast.Constant):
            read.add(args[1].value)
        elif takes_it and callee in {"uses_of", "traits_of"}:
            read |= _traits_region_reads()
        elif takes_it and callee in READS_OF_HELPERS:
            read |= READS_OF_HELPERS[callee]
        elif takes_it and callee != "getattr":
            assert hasattr(cross_checks, callee), (
                f"{function.__name__} hands the document to {callee}"
            )
            read |= _sections_read(getattr(cross_checks, callee))
    return read & set(SECTIONS)


@pytest.mark.parametrize("name", sorted(CROSS_RULES))
def test_a_rule_reads_the_sections_its_row_says(name: str) -> None:
    rule = CROSS_RULES[name]

    assert _sections_read(rule.rule) == set(rule.reads)


def test_every_section_a_rule_reads_is_a_section_of_the_loader() -> None:
    assert frozenset().union(*(rule.reads for rule in CROSS_RULES.values())) <= set(SECTIONS)


def test_the_name_of_a_rule_is_the_name_of_its_function() -> None:
    assert all(name == rule.rule.__name__ for name, rule in CROSS_RULES.items())


# ---------------------------------------------------------------------------
# The vocabulary of ``[[export]]``
# ---------------------------------------------------------------------------

TERMS = ("storage", "storage_ss", "storage_sy", "evapotranspiration")


@pytest.mark.parametrize("term", TERMS)
def test_the_vocabulary_holds_the_term_as_a_field(term: str) -> None:
    assert static_export_names()[term] is ExportKind.field


def test_a_block_naming_the_terms_is_written() -> None:
    cfg = SimpleNamespace(
        simulation=SimpleNamespace(name="demo"),
        export=[ExportRequest(variables=list(TERMS))],
    )

    refuse_an_export_that_cannot_be_written(cfg, sealed=False)


# ---------------------------------------------------------------------------
# Two ``[[export]]`` blocks that write one file
# ---------------------------------------------------------------------------


def _exports(*requests: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(name=None),
        export=[ExportRequest(**request) for request in requests],
    )


GROUP = {"variables": ["head", "watertable_depth"]}


def test_a_file_that_looks_like_the_group_of_a_run_named_run_is_written() -> None:
    cfg = _exports(GROUP, {"variables": "head", "file": "run_fields.nc"})

    refuse_an_export_that_cannot_be_written(cfg, sealed=False)


@pytest.mark.parametrize(
    ("first", "second", "written"),
    [
        (GROUP, {"variables": ["head", "storage"]}, "<run>_fields.nc"),
        ({"variables": "head"}, {"variables": "watertable_depth", "file": "head.nc"}, "head.nc"),
    ],
    ids=["the group of the run, whatever its name", "a file a single name writes"],
)
def test_two_blocks_that_write_one_file_are_refused(
    first: dict[str, Any], second: dict[str, Any], written: str
) -> None:
    cfg = _exports(first, second)

    with pytest.raises(ConfigError, match=rf"export\[0\] and export\[1\] both write {written}"):
        refuse_an_export_that_cannot_be_written(cfg, sealed=False)
