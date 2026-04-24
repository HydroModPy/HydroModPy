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
