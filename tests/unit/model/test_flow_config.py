"""The ``[flow]`` section: inline units, boundary conditions, forwarded keys and CSV forcing paths.

Lengths are in m, boundary drains in m2/s, forcing files are found next to the TOML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import _PREPARSED_KEYS, FlowConfig, resolve_forcing_paths
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions


def build(section: dict[str, Any]) -> FlowConfig:
    return FlowConfig.from_toml_section(section, base_dir=Path("."))


def bc(**boundary: Any) -> dict[str, Any]:
    return {"bc": boundary}


def test_flow_param_accepts_inline_units_with_mixed_families() -> None:
    cfg = FlowConfig(
        param_list=["K", "Ss", "Sy"],
        param={
            "K": {"field": {"id": "K", "kind": "homogeneous", "value": "8.64 m/day"}},
            "Ss": {"field": {"id": "Ss", "kind": "homogeneous", "value": "1e-6 cm-1"}},
            "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "value": "0.2 -"}},
        },
    )

    flow = Flow(cfg)

    assert float(flow.parameters["K"].value) == pytest.approx(1.0e-4)  # 8.64 m/day in m/s
    assert float(flow.parameters["Ss"].value) == pytest.approx(1.0e-4)  # 1e-6 cm-1 in m-1
    assert float(flow.parameters["Sy"].value) == pytest.approx(0.2)


def test_flow_param_refuses_conflicting_units() -> None:
    field = {"id": "K", "kind": "homogeneous", "unit": "m/day", "value": "1.0 m/s"}
    with pytest.raises(ValueError, match="mixes conflicting units"):
        Flow(FlowConfig(param_list=["K"], param={"K": {"field": field}}))


def test_drain_value_accepts_an_inline_unit() -> None:
    cfg = build(bc(drainage={"kind": "drain", "value": "10 cm2/day", "application_domain": "top"}))

    drainage = cfg.bc["drainage"]
    assert drainage.kind == "drain"
    assert drainage.value == pytest.approx(1.0e-3 / 86400.0)  # 10 cm2/day in m2/s
    assert drainage.units == "m2/s"


def test_dirichlet_value_is_converted_to_meters() -> None:
    west_side = build(bc(west_side={"kind": "dirichlet", "value": "100 cm"})).bc["west_side"]

    assert west_side.value == pytest.approx(1.0)
    assert west_side.units == "m"


def test_dirichlet_forcing_replaces_the_value() -> None:
    forcing = {"kind": "constant", "value": 99.0}
    west_side = build(bc(west_side={"kind": "dirichlet", "forcing": forcing})).bc["west_side"]

    assert west_side.value is None
    assert west_side.units == "m"
    assert west_side.forcing.kind == "constant"
    assert west_side.forcing.value == pytest.approx(99.0)
    assert west_side.forcing.units == "m"


def test_dirichlet_forcing_keeps_its_source_unit() -> None:
    boundary = {
        "kind": "dirichlet",
        "unit": "centimeter",
        "forcing": {"kind": "constant", "value": 120.0},
    }
    west_side = build(bc(west_side=boundary)).bc["west_side"]

    assert west_side.value is None
    assert west_side.units == "m"
    assert west_side.forcing.units == "cm"


def test_ocean_forcing_is_accepted() -> None:
    # A tide moves, and the backends already read the ocean head per period.
    ocean = {"kind": "dirichlet", "forcing": {"kind": "constant", "value": 0.0}}

    assert build(bc(ocean=ocean)).bc["ocean"].forcing is not None


TWICE = {"kind": "constant", "value": 99.0}

REFUSALS = [
    pytest.param(
        bc(north_side={"kind": "dirichlet", "value": 100.0, "application_domain": "south side"}),
        "does not match inferred domain",
        id="application domain of another side",
    ),
    pytest.param(
        bc(dirichlet={"south_side": {"value": 99.0}}),
        "no longer supported",
        id="boundary keyed by its family",
    ),
    pytest.param({"param_values": {}}, r"flow\.param_values", id="param_values alias"),
    pytest.param(
        bc(ocean={"kind": "dirichlet", "value": "1.0 m", "unit": "cm"}),
        "conflicting units",
        id="value and unit disagree",
    ),
    pytest.param(
        bc(ocean={"kind": "dirichlet", "value": "1.0 qblorp"}),
        "Unsupported length unit",
        id="unknown unit",
    ),
    pytest.param(
        bc(west_side={"kind": "dirichlet", "value": 100.0, "forcing": TWICE}),
        "value and flow.bc.west_side.forcing are mutually exclusive",
        id="value and forcing",
    ),
    pytest.param(
        bc(lake={"value": 1.0}),
        "A lake and a stream network are declared under",
        id="lake under flow.bc",
    ),
    pytest.param(
        {"runtime": {"backend": "petsc"}}, "Unknown TOML key.*runtime", id="runtime table"
    ),
]


@pytest.mark.parametrize(("section", "message"), REFUSALS)
def test_refusals(section, message) -> None:
    with pytest.raises(ValueError, match=message):
        build(section)


# Every declared ``[flow]`` key must survive the TOML loader. A field added to
# FlowConfig was once accepted by the unknown-key guard and then dropped, so the
# model itself is the source of truth for these probes.

# One non-default value per scalar field, to prove the value reaches the model.
SCALAR_PROBES: dict[str, Any] = {
    "flow_regime": "steady",
    "first_period_steady": False,
    "restart_from": "prior_run/fields.zarr",
}

# The same, for each field of ``[solver.boussinesq]``.
RUNTIME_PROBES: dict[str, Any] = {
    "backend": "petsc",
    "surface_interaction_model": "complementarity",
    "partition_release_depth_m": 0.02,
    "max_iterations": 77,
    "tol_residual_inf": 1e-7,
    "tol_state_update_inf": 1e-9,
    "vi_substeps_per_period": 3,
    "vi_substep_on_failure": True,
    "vi_max_adaptive_substeps": 5,
    "ts_vi_steps_per_period": 6,
    "ts_vi_adapt": True,
    "ts_vi_dt_min_fraction": 1.0 / 32.0,
    "ts_vi_dt_max_fraction": 1.0 / 2.0,
    "ts_vi_type": "cn",
    "ts_vi_snes_type": "vinewtonssls",
    "exchange_mesh": Path("mesh_bundle"),
    "wall_clock_limit_s": 600.0,
}


def test_every_field_has_a_probe() -> None:
    expected = set(FlowConfig.model_fields) - set(_PREPARSED_KEYS)
    assert set(SCALAR_PROBES) == expected
    assert set(RUNTIME_PROBES) == set(BoussinesqOptions.model_fields)


@pytest.mark.parametrize(("key", "value"), sorted(SCALAR_PROBES.items()))
def test_scalar_field_is_forwarded(key: str, value: Any) -> None:
    assert getattr(build({key: value}), key) == value


@pytest.mark.parametrize(("key", "value"), sorted(RUNTIME_PROBES.items()))
def test_runtime_field_is_forwarded(key: str, value: Any) -> None:
    cfg = SolverConfig.model_validate({"boussinesq": {key: value}})
    assert getattr(cfg.options_of("boussinesq"), key) == value


def test_preparsed_keys_are_known_to_the_model() -> None:
    unknown = set(_PREPARSED_KEYS) - set(FlowConfig.model_fields)
    assert unknown == {"param_values"}


def test_absent_keys_keep_the_model_defaults() -> None:
    cfg = build({})
    for key in SCALAR_PROBES:
        assert getattr(cfg, key) == FlowConfig.model_fields[key].default
    options = SolverConfig().options_of("boussinesq")
    for key in RUNTIME_PROBES:
        assert getattr(options, key) == BoussinesqOptions.model_fields[key].default


# A CSV forcing of a lake, an outlet or an SFR reach is found like a well forcing.


def csv(name: str) -> dict[str, object]:
    return {"kind": "csv", "path_file": name, "value_column": "v"}


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "project"
    data = tmp_path / "workspace" / "data"
    (data / "lakes").mkdir(parents=True)
    (base / "inputs").mkdir(parents=True)
    for name in ("rain.csv", "release.csv", "inflow.csv", "seg.csv"):
        (data / "lakes" / name).write_text("date,v\n2020-01-01,1\n", encoding="utf-8")
        (base / "inputs" / name).write_text("date,v\n2020-01-01,1\n", encoding="utf-8")
    return base, data


@pytest.mark.unit
def test_csv_forcings_resolve_against_the_toml_folder(layout) -> None:
    # A lake or SFR CSV is read where the TOML names it; data/<role>/ is never searched.
    base, data = layout
    raw = {
        "lakes": {
            "lac0": {
                "rainfall": csv("inputs/rain.csv"),
                "outlet": {"kind": "specified", "forcing": csv("inputs/release.csv")},
                "inflow": {
                    "kind": "piecewise",
                    "segments": [{"start": "2020-01-01", "forcing": csv("inputs/seg.csv")}],
                },
            }
        },
        "sfr": {"headwater_inflow": csv("inflow.csv")},
    }
    out = resolve_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    lac = out["lakes"]["lac0"]
    assert Path(lac["rainfall"]["path_file"]) == (base / "inputs" / "rain.csv").resolve()
    assert (
        Path(lac["outlet"]["forcing"]["path_file"]) == (base / "inputs" / "release.csv").resolve()
    )
    seg = lac["inflow"]["segments"][0]["forcing"]
    assert Path(seg["path_file"]) == (base / "inputs" / "seg.csv").resolve()
    # A file that sits only in data/lakes/ is not found by its bare name.
    assert Path(out["sfr"]["headwater_inflow"]["path_file"]) == (base / "inflow.csv").resolve()


@pytest.mark.unit
def test_a_missing_csv_keeps_a_predictable_path(layout) -> None:
    base, data = layout
    raw = {"lakes": {"lac0": {"rainfall": csv("absent.csv")}}}
    out = resolve_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    assert Path(out["lakes"]["lac0"]["rainfall"]["path_file"]) == (base / "absent.csv").resolve()
