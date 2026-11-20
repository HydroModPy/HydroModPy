"""Candidate overlays of a calibration, written as TOML on top of a base config.

A parameter set (K in m/s, multipliers without unit) becomes the overlay file
that one trial reads. A replace parameter writes its value at its dotted path,
a scale parameter multiplies the base value found there.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners import materialize as materialize_module
from hydromodpy.calibration.runners.materialize import materialize_candidate, write_overlay_toml
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig

K_TARGET = "flow.param.K.field.value"


def k_space(name: str = "K", lower: float = 1e-6, upper: float = 1e-3, mode: str = "replace"):
    return ParameterSpace(
        [CalibParameter(name=name, lower=lower, upper=upper, target=K_TARGET, mode=mode)]
    )


@pytest.fixture
def base_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "base_simulation.toml"
    path.write_text(
        f"""
[workspace]
root = "{tmp_path.as_posix()}"

[simulation]
name = "base_run"

[flow.param.K.field]
kind = "homogeneous"
value = 1.0e-4

[flow.param.Sy.field]
kind = "homogeneous"
value = 0.1
""",
        encoding="utf-8",
    )
    return path


def in_memory_config(tmp_path: Path) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
    )


def read_overlay(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_replace_writes_the_value(base_config_path, tmp_path):
    overlay_path = materialize_candidate(
        base_config=base_config_path,
        params={"K": 5.0e-4},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="truth",
    )

    payload = read_overlay(overlay_path)
    assert overlay_path.parent.name == "truth"
    assert payload["base_config"] == str(base_config_path.resolve())
    assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(5.0e-4)


def test_scale_multiplies_the_base_value(base_config_path, tmp_path):
    overlay_path = materialize_candidate(
        base_config=base_config_path,
        params={"K_mult": 3.0},
        space=k_space("K_mult", 0.1, 10.0, mode="scale"),
        out_dir=tmp_path / "candidates",
        candidate_label="scaled",
    )

    # Base value 1e-4 m/s times 3.
    assert read_overlay(overlay_path)["flow"]["param"]["K"]["field"]["value"] == pytest.approx(3e-4)


def test_scale_reads_the_base_through_inheritance(tmp_path):
    parent = tmp_path / "parent.toml"
    parent.write_text(
        '[flow.param.K]\nfield = { kind = "homogeneous", value = 1.0e-4 }\n', encoding="utf-8"
    )
    child = tmp_path / "child.toml"
    child.write_text(f'base_config = "{parent.as_posix()}"\n', encoding="utf-8")

    overlay_path = materialize_candidate(
        base_config=child,
        params={"K_mult": 4.0},
        space=k_space("K_mult", 0.1, 10.0, mode="scale"),
        out_dir=tmp_path / "candidates",
        candidate_label="scaled_from_parent",
    )

    payload = read_overlay(overlay_path)
    assert payload["base_config"] == str(child.resolve())
    assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(4e-4)


def test_extra_sections_are_merged(base_config_path, tmp_path):
    overlay_path = materialize_candidate(
        base_config=base_config_path,
        params={"K": 2.0e-4},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="no_display",
        extra_sections={"display": {"enabled": False, "theme": "print"}},
    )

    assert read_overlay(overlay_path)["display"] == {"enabled": False, "theme": "print"}


def test_overlay_names_the_simulation(base_config_path, tmp_path):
    overlay_path = materialize_candidate(
        base_config=base_config_path,
        params={"K": 1.23e-4},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="case_a",
        name="case_a_run",
    )

    payload = read_overlay(overlay_path)
    assert payload["simulation"]["name"] == "case_a_run"
    assert payload["workspace"]["root"]


def test_in_memory_config_with_a_base_dir(tmp_path):
    overlay_path = materialize_candidate(
        base_config=in_memory_config(tmp_path),
        params={"K": 7.5e-5},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="from_obj",
        base_dir=tmp_path,
    )

    payload = read_overlay(overlay_path)
    assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(7.5e-5)
    assert isinstance(payload["workspace"], dict)


def test_overlay_round_trips_through_tomllib(base_config_path, tmp_path):
    overlay_path = materialize_candidate(
        base_config=base_config_path,
        params={"K": 4.2e-4},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="reload",
    )

    payload = read_overlay(overlay_path)
    assert payload["base_config"] == str(base_config_path.resolve())
    assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(4.2e-4)


def test_overlay_loads_through_from_toml(tmp_path):
    full_base = tmp_path / "full_base.toml"
    full_base.write_text(
        f"""\
[workflow]
mode = "simulation"

[workspace]
root = "{tmp_path.as_posix()}"

[geographic]
source_mode = "synthetic"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1.0e-4 m/s"
""",
        encoding="utf-8",
    )

    overlay_path = materialize_candidate(
        base_config=full_base,
        params={"K": 4.2e-4},
        space=k_space(),
        out_dir=tmp_path / "candidates",
        candidate_label="reload",
    )

    # The overlay is plain TOML and HydroModPyConfig accepts it.
    payload = read_overlay(overlay_path)
    assert payload["base_config"] == str(full_base.resolve())
    assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(4.2e-4)
    value = HydroModPyConfig.from_toml(overlay_path).flow.param["K"].field.value
    magnitude = float(value.magnitude) if hasattr(value, "magnitude") else float(value)
    assert magnitude == pytest.approx(4.2e-4)


def test_iteration_overlay_folder(base_config_path, tmp_path):
    # Same call as one trial of a search: the folder is named by the trial id.
    overlays_dir = tmp_path / "overlays"
    overlays_dir.mkdir()
    suggestion = ParamSuggestion(trial_id=0, values={"K": 2.5e-4})

    overlay_path = materialize_candidate(
        base_config_path, dict(suggestion.values), k_space(), overlays_dir, iteration_index=0
    )
    result = EvaluationResult(
        trial_id=0,
        sim_id=None,
        cost=0.5,
        status="completed",
        metadata={"materialized_overlay": str(overlay_path)},
    )

    assert overlay_path == overlays_dir / "iter_0000" / "candidate_override.toml"
    assert result.metadata["materialized_overlay"] == str(overlay_path)
    assert read_overlay(overlay_path)["flow"]["param"]["K"]["field"]["value"] == pytest.approx(
        2.5e-4
    )


def test_workspace_root_is_the_one_asked_for(base_config_path, tmp_path):
    overlay = materialize_candidate(
        base_config_path,
        {"K": 2e-4},
        k_space(),
        tmp_path / "c",
        iteration_index=1,
        workspace_root=tmp_path / "elsewhere",
        base_dir=tmp_path,
    )

    assert read_overlay(overlay)["workspace"]["root"] == "elsewhere"


def test_in_memory_config_skips_free_parameters(tmp_path):
    class Base(BaseModel):
        simulation: dict = {"name": "mem"}

    space = ParameterSpace(
        [
            CalibParameter(name="free", lower=0.0, upper=1.0, mode="replace"),
            CalibParameter(name="K", lower=1e-6, upper=1e-3, target="flow.param.K.value"),
        ]
    )
    overlay = materialize_candidate(
        Base(),
        {"free": 0.5, "K": 3e-4},
        space,
        tmp_path / "c",
        iteration_index=2,
        base_dir=tmp_path,
    )

    payload = read_overlay(overlay)
    assert payload["workspace"]["root"] == str(tmp_path.resolve())
    assert payload["flow"]["param"]["K"]["value"] == pytest.approx(3e-4)
    assert "free" not in payload


def test_failed_write_keeps_the_previous_overlay(tmp_path, monkeypatch):
    # The frozen config.toml of a session is read by a later replay, never half written.
    target = tmp_path / "config.toml"
    write_overlay_toml(target, {"calibration": {"method": "grid"}})

    def refuse(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(materialize_module, "rename_over_open_file", refuse)
    with pytest.raises(OSError, match="disk full"):
        write_overlay_toml(target, {"calibration": {"method": "cma"}})

    assert read_overlay(target) == {"calibration": {"method": "grid"}}
    assert [path.name for path in tmp_path.iterdir()] == ["config.toml"]


class _Units:
    def __format__(self, spec: str) -> str:
        return "m" if spec == "~" else "metre"


class _Quantity:
    magnitude = 2.5
    units = _Units()


COERCIONS = [
    pytest.param(Path("a/b"), "a/b", id="path"),
    pytest.param(_Quantity(), "2.5 m", id="quantity"),
    pytest.param((1, None, 2), [1, 2], id="tuple without none"),
    pytest.param({"k": None, 3: (Path("x"),)}, {"3": ["x"]}, id="mapping with int key"),
]


@pytest.mark.parametrize(("value", "coerced"), COERCIONS)
def test_value_for_the_toml_writer(value, coerced):
    assert materialize_module._coerce_for_toml(value) == coerced


LABELS = [
    pytest.param(" My Label! ", "my_label_", id="spaces and punctuation"),
    pytest.param("a.b-c_d", "a.b-c_d", id="already safe"),
]


@pytest.mark.parametrize(("label", "clean"), LABELS)
def test_filesystem_safe_label(label, clean):
    assert materialize_module._sanitize_label(label) == clean


# The field grammar of the source: a parameter under "field" gets that key inserted.
TARGET_PATHS = [
    pytest.param(
        {"flow": {"param": {"K": 5}}}, ("flow", "param", "K", "value"), False, id="scalar"
    ),
    pytest.param(
        {"flow": {"param": {"K": {}}}}, ("flow", "param", "K", "value"), False, id="empty table"
    ),
    pytest.param(
        {"flow": {"param": {"K": {"field": {}}}}},
        ("flow", "param", "K", "value"),
        True,
        id="value under field",
    ),
    pytest.param(
        {"flow": {"param": {"K": {"field": {}}}}},
        ("flow", "param", "K", "label"),
        False,
        id="other key",
    ),
    pytest.param({}, ("simulation", "name"), False, id="short path"),
]


@pytest.mark.parametrize(("base", "dotted", "through_field"), TARGET_PATHS)
def test_parameter_path(base, dotted, through_field):
    expected = dotted[:3] + ("field",) + dotted[3:] if through_field else dotted

    assert materialize_module._resolve_overlay_target_path(base, dotted) == expected


PATHS = [
    pytest.param(Path("/a/b"), None, "/a/b", id="no base"),
    pytest.param(Path("/a/b"), Path("/a"), "b", id="inside base"),
    pytest.param(Path("/a/b"), Path("/c"), "/a/b", id="outside base"),
]


@pytest.mark.parametrize(("path", "base_dir", "printed"), PATHS)
def test_path_relative_to_its_base(path, base_dir, printed):
    assert materialize_module._format_path_for_overlay(path, base_dir) == printed


REFUSALS = [
    pytest.param(
        lambda base, space, out: materialize_candidate(
            base_config=base, params={"K": 1e-4}, space=space, out_dir=out
        ),
        ValueError,
        "candidate_label or iteration_index",
        id="no label nor index",
    ),
    pytest.param(
        lambda base, space, out: materialize_candidate(
            base_config=out / "does_not_exist.toml",
            params={"K": 1e-4},
            space=space,
            out_dir=out,
            candidate_label="truth",
        ),
        FileNotFoundError,
        "does_not_exist",
        id="missing base config",
    ),
    pytest.param(
        lambda base, space, out: materialize_candidate(
            base_config=base, params={}, space=space, out_dir=out, candidate_label="truth"
        ),
        ValueError,
        "missing from candidate params",
        id="missing parameter value",
    ),
    pytest.param(
        lambda base, space, out: write_overlay_toml(out / "o.toml", Path("x")),
        TypeError,
        "mapping payload",
        id="payload not a mapping",
    ),
]


@pytest.mark.parametrize(("call", "error", "message"), REFUSALS)
def test_refusals(call, error, message, base_config_path, tmp_path):
    out = tmp_path / "candidates"
    out.mkdir()

    with pytest.raises(error, match=message):
        call(base_config_path, k_space(), out)


def test_in_memory_config_requires_base_dir(tmp_path):
    with pytest.raises(ValueError, match="requires base_dir"):
        materialize_candidate(
            base_config=in_memory_config(tmp_path),
            params={"K": 7.5e-5},
            space=k_space(),
            out_dir=tmp_path / "candidates",
            candidate_label="from_obj",
        )


def test_empty_label_is_refused():
    with pytest.raises(ValueError, match="cannot be empty"):
        materialize_module._sanitize_label("  ")


MODE_REFUSALS = [
    pytest.param(None, "scale", "requires a numeric base value at the target", id="no base"),
    pytest.param("wide", "scale", "requires a numeric base value; got 'wide'", id="text base"),
    pytest.param(1.0, "shift", "unsupported mode 'shift'", id="unknown mode"),
]


@pytest.mark.parametrize(("base", "mode", "message"), MODE_REFUSALS)
def test_mode_refusals(base, mode, message):
    with pytest.raises(ValueError, match=message):
        materialize_module._apply_parameter_mode(
            base_value=base, candidate_value=2.0, mode=mode, param_name="K"
        )
