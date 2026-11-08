from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import _PREPARSED_KEYS, FlowConfig, resolve_forcing_paths
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions


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
    assert float(flow.parameters["K"].value) == pytest.approx(1.0e-4)
    assert float(flow.parameters["Ss"].value) == pytest.approx(1.0e-4)
    assert float(flow.parameters["Sy"].value) == pytest.approx(0.2)


def test_flow_param_rejects_inline_unit_conflicting_with_field_unit() -> None:
    with pytest.raises(ValueError, match="mixes conflicting units"):
        cfg = FlowConfig(
            param_list=["K"],
            param={
                "K": {
                    "field": {
                        "id": "K",
                        "kind": "homogeneous",
                        "unit": "m/day",
                        "value": "1.0 m/s",
                    },
                }
            },
        )
        _ = Flow(cfg)


# Every declared ``[flow]`` key must survive the TOML loader.
#
# The loader used to rebuild the validation payload from a hand-written key
# list, so a field added to :class:`FlowConfig` was accepted by the unknown-key
# guard and then silently dropped (``restart_from`` was the regression). These
# tests pin the model itself as the source of truth.


# One non-default value per scalar field, used to prove the value reaches the
# model instead of being replaced by the field default.
_SCALAR_PROBES: dict[str, Any] = {
    "flow_regime": "steady",
    "first_period_steady": False,
    "restart_from": "prior_run/fields.zarr",
}


#: The same, for each field of ``[solver.boussinesq]``.
_RUNTIME_PROBES: dict[str, Any] = {
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
}


def _build(section: dict[str, Any]) -> FlowConfig:
    return FlowConfig.from_toml_section(section, base_dir=Path("."))


def test_restart_from_declared_in_toml_reaches_the_config() -> None:
    cfg = _build({"restart_from": "runs/spinup/fields.zarr"})
    assert cfg.restart_from == "runs/spinup/fields.zarr"


def test_every_scalar_field_has_a_probe() -> None:
    """The probe table must cover all non-preparsed model fields."""
    expected = set(FlowConfig.model_fields) - set(_PREPARSED_KEYS)
    assert set(_SCALAR_PROBES) == expected
    assert set(_RUNTIME_PROBES) == set(BoussinesqOptions.model_fields)


@pytest.mark.parametrize(("key", "value"), sorted(_SCALAR_PROBES.items()))
def test_scalar_field_is_forwarded(key: str, value: Any) -> None:
    cfg = _build({key: value})
    assert getattr(cfg, key) == value


@pytest.mark.parametrize(("key", "value"), sorted(_RUNTIME_PROBES.items()))
def test_runtime_field_is_forwarded(key: str, value: Any) -> None:
    cfg = SolverConfig.model_validate({"boussinesq": {key: value}})
    assert getattr(cfg.options_of("boussinesq"), key) == value


def test_the_runtime_table_is_not_a_key_of_the_flow_section() -> None:
    with pytest.raises(ValueError, match="Unknown TOML key.*runtime"):
        _build({"runtime": {"backend": "petsc"}})


def test_preparsed_keys_are_known_to_the_model() -> None:
    unknown = set(_PREPARSED_KEYS) - set(FlowConfig.model_fields)
    assert unknown == {"param_values"}


def test_absent_keys_keep_the_model_defaults() -> None:
    cfg = _build({})
    for key in _SCALAR_PROBES:
        assert getattr(cfg, key) == FlowConfig.model_fields[key].default
    options = SolverConfig().options_of("boussinesq")
    for key in _RUNTIME_PROBES:
        assert getattr(options, key) == BoussinesqOptions.model_fields[key].default


# A CSV forcing of a lake, an outlet or an SFR reach is found like a well forcing.


def _csv(name: str) -> dict[str, object]:
    return {"kind": "csv", "path_file": name, "value_column": "v"}


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "project"
    data = tmp_path / "workspace" / "data"
    (data / "lakes").mkdir(parents=True)
    base.mkdir()
    for name in ("rain.csv", "release.csv", "inflow.csv", "seg.csv"):
        (data / "lakes" / name).write_text("date,v\n2020-01-01,1\n", encoding="utf-8")
    return base, data


@pytest.mark.unit
def test_lake_outlet_and_sfr_csv_resolve_against_data(layout) -> None:
    base, data = layout
    raw = {
        "lakes": {
            "lac0": {
                "rainfall": _csv("rain.csv"),
                "outlet": {"kind": "specified", "forcing": _csv("release.csv")},
                "inflow": {
                    "kind": "piecewise",
                    "segments": [{"start": "2020-01-01", "forcing": _csv("seg.csv")}],
                },
            }
        },
        "sfr": {"headwater_inflow": _csv("inflow.csv")},
    }
    out = resolve_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    lac = out["lakes"]["lac0"]
    assert Path(lac["rainfall"]["path_file"]) == (data / "lakes" / "rain.csv").resolve()
    assert Path(lac["outlet"]["forcing"]["path_file"]) == (data / "lakes" / "release.csv").resolve()
    seg = lac["inflow"]["segments"][0]["forcing"]
    assert Path(seg["path_file"]) == (data / "lakes" / "seg.csv").resolve()
    # SFR has no data/sfr folder here: the bare name falls back to data/ then stays beside the TOML.
    assert Path(out["sfr"]["headwater_inflow"]["path_file"]).name == "inflow.csv"


@pytest.mark.unit
def test_a_missing_lake_csv_keeps_a_predictable_path(layout) -> None:
    base, data = layout
    raw = {"lakes": {"lac0": {"rainfall": _csv("absent.csv")}}}
    out = resolve_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    assert Path(out["lakes"]["lac0"]["rainfall"]["path_file"]) == (base / "absent.csv").resolve()
