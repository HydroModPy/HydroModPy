"""Tests of `runners.materialize`."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners import materialize as materialize_module
from hydromodpy.calibration.runners.materialize import materialize_candidate, write_overlay_toml
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

# From test_materialize_candidate.py
# Tests for :func:`hydromodpy.calibration.runners.materialize.materialize_candidate`.
#
# Covers Phase 5 of the calibration integration:
#
# - A replace-mode parameter is written as-is at its target dotted path.
# - A scale-mode parameter multiplies the base value at its target path.
# - The resulting TOML is valid, inherits the base config, and round-trips
#   through :mod:`tomllib`.
# - Missing ``candidate_label`` and ``iteration_index`` raises.
# - Missing base_config raises.


@pytest.fixture()
def base_config_path(tmp_path: Path) -> Path:
    """Write a minimal base simulation TOML with a nested parameter."""
    content = f"""
[workspace]
root = "{tmp_path.as_posix()}"

[simulation]
run_id = "base_run"

[flow.param.K.field]
kind = "homogeneous"
value = 1.0e-4

[flow.param.Sy.field]
kind = "homogeneous"
value = 0.1
"""
    path = tmp_path / "base_simulation.toml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def space_replace() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="K",
                lower=1e-6,
                upper=1e-3,
                target="flow.param.K.field.value",
                mode="replace",
            )
        ]
    )


@pytest.fixture()
def space_scale() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="K_mult",
                lower=0.1,
                upper=10.0,
                target="flow.param.K.field.value",
                mode="scale",
            )
        ]
    )


class TestMaterializeCandidateReplace:
    def test_writes_overlay_with_replace_value(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        out_dir = tmp_path / "candidates"
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K": 5.0e-4},
            space=space_replace,
            out_dir=out_dir,
            candidate_label="truth",
        )
        assert overlay_path.is_file()
        assert overlay_path.parent.name == "truth"
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["base_config"] == str(base_config_path.resolve())
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(5.0e-4)

    def test_iteration_index_produces_iter_folder(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K": 1.5e-4},
            space=space_replace,
            out_dir=tmp_path / "candidates",
            iteration_index=7,
        )
        assert overlay_path.parent.name == "iter_0007"


class TestMaterializeCandidateScale:
    def test_scale_multiplies_base_value(
        self, base_config_path: Path, space_scale: ParameterSpace, tmp_path: Path
    ):
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K_mult": 3.0},
            space=space_scale,
            out_dir=tmp_path / "candidates",
            candidate_label="scaled",
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        # base value was 1e-4, scale 3.0 → 3e-4
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(3.0e-4)

    def test_scale_reads_base_config_inheritance(self, space_scale: ParameterSpace, tmp_path: Path):
        parent = tmp_path / "parent.toml"
        parent.write_text(
            """\
[flow.param.K]
field = { kind = "homogeneous", value = 1.0e-4 }
""",
            encoding="utf-8",
        )
        child = tmp_path / "child.toml"
        child.write_text(f'base_config = "{parent.as_posix()}"\n', encoding="utf-8")

        overlay_path = materialize_candidate(
            base_config=child,
            params={"K_mult": 4.0},
            space=space_scale,
            out_dir=tmp_path / "candidates",
            candidate_label="scaled_from_parent",
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["base_config"] == str(child.resolve())
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(4.0e-4)


class TestMaterializeCandidateErrors:
    def test_requires_label_or_index(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        with pytest.raises(ValueError, match="candidate_label or iteration_index"):
            materialize_candidate(
                base_config=base_config_path,
                params={"K": 1.0e-4},
                space=space_replace,
                out_dir=tmp_path / "candidates",
            )

    def test_missing_base_config_raises(self, space_replace: ParameterSpace, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            materialize_candidate(
                base_config=tmp_path / "does_not_exist.toml",
                params={"K": 1.0e-4},
                space=space_replace,
                out_dir=tmp_path / "candidates",
                candidate_label="truth",
            )

    def test_missing_param_value_raises(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        with pytest.raises(ValueError, match="missing from candidate params"):
            materialize_candidate(
                base_config=base_config_path,
                params={},  # missing K
                space=space_replace,
                out_dir=tmp_path / "candidates",
                candidate_label="truth",
            )

    def test_in_memory_config_requires_base_dir(
        self, space_replace: ParameterSpace, tmp_path: Path
    ):

        cfg = HydroModPyConfig(
            workflow={"mode": "simulation"},
            workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
            geographic=GeographicConfig(source_mode="synthetic"),
        )

        with pytest.raises(ValueError, match="requires base_dir"):
            materialize_candidate(
                base_config=cfg,
                params={"K": 7.5e-5},
                space=space_replace,
                out_dir=tmp_path / "candidates",
                candidate_label="from_obj",
            )


class TestExtraSections:
    def test_extra_sections_merged(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K": 2.0e-4},
            space=space_replace,
            out_dir=tmp_path / "candidates",
            candidate_label="no_display",
            extra_sections={"display": {"enabled": False, "show": False}},
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["display"]["enabled"] is False
        assert payload["display"]["show"] is False


class TestReimportableByTomllib:
    def test_overlay_parses_as_valid_toml(
        self, base_config_path: Path, space_replace: ParameterSpace, tmp_path: Path
    ):
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K": 1.23e-4},
            space=space_replace,
            out_dir=tmp_path / "candidates",
            candidate_label="case_a",
            name="case_a_run",
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["simulation"]["name"] == "case_a_run"
        assert payload["workspace"]["root"]


class TestMaterializeCandidateHydroModPyConfig:
    def test_accepts_in_memory_config(self, space_replace: ParameterSpace, tmp_path: Path):

        cfg = HydroModPyConfig(
            workflow={"mode": "simulation"},
            workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
            geographic=GeographicConfig(source_mode="synthetic"),
        )

        overlay_path = materialize_candidate(
            base_config=cfg,
            params={"K": 7.5e-5},
            space=space_replace,
            out_dir=tmp_path / "candidates",
            candidate_label="from_obj",
            base_dir=tmp_path,
        )
        assert overlay_path.is_file()
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(7.5e-5)
        # The rendered TOML must remain a flat valid document.
        assert isinstance(payload["workspace"], dict)


class TestOverlayReloadableViaHydroModPyConfig:
    def test_overlay_payload_round_trips_through_tomllib(
        self,
        base_config_path: Path,
        space_replace: ParameterSpace,
        tmp_path: Path,
    ):
        """The overlay must remain a valid TOML re-readable verbatim."""
        overlay_path = materialize_candidate(
            base_config=base_config_path,
            params={"K": 4.2e-4},
            space=space_replace,
            out_dir=tmp_path / "candidates",
            candidate_label="reload",
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        # base_config inheritance pointer is preserved.
        assert payload["base_config"] == str(base_config_path.resolve())
        # The injected K value matches the candidate value.
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(4.2e-4)

    def test_overlay_loads_through_from_toml(
        self,
        space_replace: ParameterSpace,
        tmp_path: Path,
    ):
        """End-to-end: a schema-complete base TOML produces an overlay that
        HydroModPyConfig.from_toml validates without errors."""

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

        space = ParameterSpace(
            [
                CalibParameter(
                    name="K",
                    lower=1e-6,
                    upper=1e-3,
                    target="flow.param.K.field.value",
                    mode="replace",
                )
            ]
        )

        overlay_path = materialize_candidate(
            base_config=full_base,
            params={"K": 4.2e-4},
            space=space,
            out_dir=tmp_path / "candidates",
            candidate_label="reload",
        )
        cfg = HydroModPyConfig.from_toml(overlay_path)
        # The injected K value must reach the resolved flow.param.K config.
        k_param = cfg.flow.param["K"]
        # The validated payload exposes the homogeneous value either as an
        # attribute on a typed sub-config or as a flat dict; both must
        # carry the candidate magnitude.
        value = k_param.field.value
        magnitude = float(value.magnitude) if hasattr(value, "magnitude") else float(value)
        assert magnitude == pytest.approx(4.2e-4)


class TestMaterializeHookFromCli:
    def test_wrapped_evaluator_writes_overlay_when_flag_true(
        self,
        base_config_path: Path,
        tmp_path: Path,
    ):
        """Smoke-test the ``materialize_candidates`` hook in isolation.

        We rebuild a minimal evaluator that mirrors the structure used by
        :mod:`hydromodpy.calibration.runner` so the test exercises the same
        materialize call path without needing a full DuckDB / solver run.
        """

        overlays_dir = tmp_path / "overlays"
        overlays_dir.mkdir(parents=True, exist_ok=True)
        space = ParameterSpace(
            [
                CalibParameter(
                    name="K",
                    lower=1e-6,
                    upper=1e-3,
                    target="flow.param.K.field.value",
                    mode="replace",
                )
            ]
        )

        def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
            meta: dict[str, object] = {}
            overlay_path = materialize_candidate(
                base_config_path,
                dict(sugg.values),
                space,
                overlays_dir,
                iteration_index=sugg.trial_id,
            )
            meta["materialized_overlay"] = str(overlay_path)
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                cost=0.5,
                status="completed",
                metadata=meta,
            )

        result = wrapped_evaluator(ParamSuggestion(trial_id=0, values={"K": 2.5e-4}))
        overlay_dir = overlays_dir / "iter_0000"
        overlay_path = overlay_dir / "candidate_override.toml"
        assert overlay_path.is_file()
        assert result.metadata["materialized_overlay"] == str(overlay_path)
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["flow"]["param"]["K"]["field"]["value"] == pytest.approx(2.5e-4)


class TestTheOverlayIsWrittenWholeOrNotAtAll:
    """The frozen ``config.toml`` of a session is read by a later replay: never half written."""

    def test_the_document_lands_in_one_rename_and_leaves_no_staging_file(self, tmp_path):
        target = tmp_path / "sessions" / "calage" / "config.toml"

        write_overlay_toml(target, {"calibration": {"method": "grid", "max_trials": 3}})

        assert tomllib.loads(target.read_text(encoding="utf-8")) == {
            "calibration": {"method": "grid", "max_trials": 3}
        }
        assert [path.name for path in target.parent.iterdir()] == ["config.toml"]

    def test_a_write_that_fails_leaves_the_previous_document_intact(self, tmp_path, monkeypatch):
        target = tmp_path / "config.toml"
        write_overlay_toml(target, {"calibration": {"method": "grid"}})

        def _refuse(source, destination):
            raise OSError("disk full")

        monkeypatch.setattr(materialize_module, "rename_over_open_file", _refuse)
        with pytest.raises(OSError, match="disk full"):
            write_overlay_toml(target, {"calibration": {"method": "cma"}})

        assert tomllib.loads(target.read_text(encoding="utf-8")) == {
            "calibration": {"method": "grid"}
        }
        assert [path.name for path in tmp_path.iterdir()] == ["config.toml"]


class _Units:
    def __format__(self, spec: str) -> str:
        return "m" if spec == "~" else "metre"


class _Quantity:
    magnitude = 2.5
    units = _Units()


@pytest.mark.parametrize(
    ("value", "coerced"),
    [
        (Path("a/b"), "a/b"),
        (_Quantity(), "2.5 m"),
        ((1, None, 2), [1, 2]),
        ({"k": None, 3: (Path("x"),)}, {"3": ["x"]}),
    ],
)
def test_a_value_is_coerced_to_what_the_toml_writer_takes(value, coerced) -> None:
    assert materialize_module._coerce_for_toml(value) == coerced


def test_a_payload_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="mapping payload"):
        write_overlay_toml(tmp_path / "o.toml", Path("x"))


@pytest.mark.parametrize(
    ("label", "clean"), [(" My Label! ", "my_label_"), ("a.b-c_d", "a.b-c_d"), ("  ", None)]
)
def test_a_label_becomes_a_filesystem_safe_name(label, clean) -> None:
    if clean is None:
        with pytest.raises(ValueError, match="cannot be empty"):
            materialize_module._sanitize_label(label)
    else:
        assert materialize_module._sanitize_label(label) == clean


@pytest.mark.parametrize(
    ("base", "dotted", "target"),
    [
        ({"flow": {"param": {"K": 5}}}, ("flow", "param", "K", "value"), None),
        ({"flow": {"param": {"K": {}}}}, ("flow", "param", "K", "value"), None),
        ({"flow": {"param": {"K": {"field": {}}}}}, ("flow", "param", "K", "value"), "field"),
        ({"flow": {"param": {"K": {"field": {}}}}}, ("flow", "param", "K", "label"), None),
        ({}, ("simulation", "name"), None),
    ],
)
def test_a_parameter_path_follows_the_field_grammar_of_the_source(base, dotted, target) -> None:
    expected = dotted[:3] + ("field",) + dotted[3:] if target else dotted

    assert materialize_module._resolve_overlay_target_path(base, dotted) == expected


@pytest.mark.parametrize(
    ("base", "mode", "message"),
    [
        (None, "scale", "requires a numeric base value at the target"),
        ("wide", "scale", "requires a numeric base value; got 'wide'"),
        (1.0, "shift", "unsupported mode 'shift'"),
    ],
)
def test_a_mode_that_cannot_apply_says_why(base, mode, message) -> None:
    with pytest.raises(ValueError, match=message):
        materialize_module._apply_parameter_mode(
            base_value=base, candidate_value=2.0, mode=mode, param_name="K"
        )


@pytest.mark.parametrize(
    ("path", "base_dir", "printed"),
    [
        (Path("/a/b"), None, "/a/b"),
        (Path("/a/b"), Path("/a"), "b"),
        (Path("/a/b"), Path("/c"), "/a/b"),
    ],
)
def test_a_path_is_written_relative_to_its_base_when_it_can_be(path, base_dir, printed) -> None:
    assert materialize_module._format_path_for_overlay(path, base_dir) == printed


def test_the_workspace_of_the_overlay_is_the_one_asked_for(
    base_config_path, space_replace, tmp_path
) -> None:
    root = tmp_path / "elsewhere"
    overlay = materialize_candidate(
        base_config_path, {"K": 2e-4}, space_replace, tmp_path / "c", iteration_index=1,
        workspace_root=root, base_dir=tmp_path,
    )  # fmt: skip

    assert tomllib.loads(overlay.read_text())["workspace"]["root"] == "elsewhere"


def test_an_in_memory_config_writes_the_base_dir_as_its_workspace_and_skips_free_parameters(
    tmp_path,
) -> None:
    class Base(BaseModel):
        simulation: dict = {"name": "mem"}

    space = ParameterSpace(
        [
            CalibParameter(name="free", lower=0.0, upper=1.0, mode="replace"),
            CalibParameter(name="K", lower=1e-6, upper=1e-3, target="flow.param.K.value"),
        ]
    )
    overlay = materialize_candidate(
        Base(), {"free": 0.5, "K": 3e-4}, space, tmp_path / "c", iteration_index=2,
        base_dir=tmp_path,
    )  # fmt: skip

    payload = tomllib.loads(overlay.read_text())
    assert payload["workspace"]["root"] == str(tmp_path.resolve())
    assert payload["flow"]["param"]["K"]["value"] == pytest.approx(3e-4)
    assert "free" not in payload
