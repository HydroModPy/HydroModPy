"""Tests for :func:`hydromodpy.calibration.materialize.materialize_candidate`.

Covers Phase 5 of the calibration integration:

- A replace-mode parameter is written as-is at its target dotted path.
- A scale-mode parameter multiplies the base value at its target path.
- The resulting TOML is valid, inherits the base config, and round-trips
  through :mod:`tomllib`.
- Missing ``candidate_label`` and ``iteration_index`` raises.
- Missing base_config raises.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.calibration.materialize import materialize_candidate
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


@pytest.fixture()
def base_config_path(tmp_path: Path) -> Path:
    """Write a minimal base simulation TOML with a nested parameter."""
    content = f"""
[workspace]
root = "{tmp_path.as_posix()}"

[simulation]
run_id = "base_run"

[flow.param.K]
field_homogeneous = {{ value = 1.0e-4 }}

[flow.param.Sy]
field_homogeneous = {{ value = 0.1 }}
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
                target="flow.param.K.field_homogeneous.value",
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
                target="flow.param.K.field_homogeneous.value",
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
        assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == pytest.approx(5.0e-4)

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
        assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == pytest.approx(3.0e-4)


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
            run_id="case_a_run",
        )
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["simulation"]["run_id"] == "case_a_run"
        assert payload["workspace"]["root"]


class TestMaterializeCandidateHydroModPyConfig:
    def test_accepts_in_memory_config(self, space_replace: ParameterSpace, tmp_path: Path):
        from hydromodpy.config import HydroModPyConfig
        from hydromodpy.core.workspace.config import WorkspaceConfig
        from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

        cfg = HydroModPyConfig(
            workflow="simulation",
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
        assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == pytest.approx(7.5e-5)
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
        assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == pytest.approx(4.2e-4)

    def test_overlay_loads_through_from_toml(
        self,
        space_replace: ParameterSpace,
        tmp_path: Path,
    ):
        """End-to-end: a schema-complete base TOML produces an overlay that
        HydroModPyConfig.from_toml validates without errors."""
        from hydromodpy.config import HydroModPyConfig

        full_base = tmp_path / "full_base.toml"
        full_base.write_text(
            f"""\
workflow = "simulation"

[workspace]
root = "{tmp_path.as_posix()}"
project_root = "{tmp_path.as_posix()}"

[geographic]
source_mode = "synthetic"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"

[flow.param.K.field_homogeneous]
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
                    target="flow.param.K.field_homogeneous.value",
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
        if hasattr(k_param, "field_homogeneous"):
            value = k_param.field_homogeneous.value
        else:
            value = k_param["value"]
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
        :mod:`hydromodpy.calibration.cli` so the test exercises the same
        materialize call path without needing a full DuckDB / solver run.
        """
        from hydromodpy.calibration.materialize import materialize_candidate
        from hydromodpy.calibration.optimizer import EvaluationResult, ParamSuggestion
        from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace

        candidates_root = tmp_path / "overlays"
        candidates_root.mkdir(parents=True, exist_ok=True)
        space = ParameterSpace(
            [
                CalibParameter(
                    name="K",
                    lower=1e-6,
                    upper=1e-3,
                    target="flow.param.K.field_homogeneous.value",
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
                candidates_root,
                iteration_index=sugg.trial_id,
            )
            meta["materialized_overlay"] = str(overlay_path)
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=0.5,
                status="completed",
                metadata=meta,
            )

        result = wrapped_evaluator(ParamSuggestion(trial_id=0, values={"K": 2.5e-4}))
        overlay_dir = candidates_root / "iter_0000"
        overlay_path = overlay_dir / "candidate_override.toml"
        assert overlay_path.is_file()
        assert result.metadata["materialized_overlay"] == str(overlay_path)
        with open(overlay_path, "rb") as f:
            payload = tomllib.load(f)
        assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == pytest.approx(2.5e-4)
