"""Unit tests for ``hydromodpy.calibration.optim.objective_mapping``.

The module is a dependency-light JSONL reader that turns persisted
calibration iteration traces into :class:`ObjectiveMappingPoint` records.
These tests pin its real transformation behaviour:

- normal multi-line history parsing with full payloads,
- empty file, blank/whitespace lines, and a missing path,
- key/value coercion (named params to ``str``/``float``, vector to a
  ``tuple[float, ...]``),
- neutral defaults for absent optional keys,
- ``objective_total`` sign/None/NaN handling and the
  ``finite_objective`` predicate,
- malformed JSON lines surfacing as a hard error (not silently dropped).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.objective_mapping import (
    ObjectiveMappingPoint,
    load_objective_mapping_points,
)


def _write_jsonl(tmp_path: Path, lines: list[object], name: str = "history.jsonl") -> Path:
    """Serialize each entry as one JSON line; raw ``str`` lines pass through."""
    path = tmp_path / name
    out: list[str] = []
    for line in lines:
        out.append(line if isinstance(line, str) else json.dumps(line))
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Normal parsing
# ---------------------------------------------------------------------------


class TestNormalParsing:
    def test_parses_full_payload_into_typed_point(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [
                {
                    "iteration_id": "it-1",
                    "params_named": {"k": 1.5, "sy": 0.2},
                    "params_vector": [1.5, 0.2],
                    "objective_total": 0.42,
                    "block_costs": {"flow": 0.3, "head": 0.12},
                    "status": "completed",
                    "failure_reason": None,
                }
            ],
        )
        points = load_objective_mapping_points(path)

        assert len(points) == 1
        point = points[0]
        assert isinstance(point, ObjectiveMappingPoint)
        assert point.iteration_id == "it-1"
        assert point.params_named == {"k": 1.5, "sy": 0.2}
        assert point.params_vector == (1.5, 0.2)
        assert point.objective_total == pytest.approx(0.42)
        assert point.block_costs == {"flow": 0.3, "head": 0.12}
        assert point.status == "completed"
        assert point.failure_reason is None

    def test_preserves_line_order_across_multiple_entries(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [
                {"iteration_id": "a", "objective_total": 3.0},
                {"iteration_id": "b", "objective_total": 1.0},
                {"iteration_id": "c", "objective_total": 2.0},
            ],
        )
        points = load_objective_mapping_points(path)

        assert [p.iteration_id for p in points] == ["a", "b", "c"]
        assert [p.objective_total for p in points] == [3.0, 1.0, 2.0]

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        """A plain string path must be coerced to ``Path`` internally."""
        path = _write_jsonl(tmp_path, [{"iteration_id": "x", "objective_total": 0.0}])
        points = load_objective_mapping_points(str(path))
        assert len(points) == 1
        assert points[0].iteration_id == "x"

    def test_params_vector_is_immutable_tuple(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"params_vector": [0.1, 0.2, 0.3]}])
        point = load_objective_mapping_points(path)[0]
        assert isinstance(point.params_vector, tuple)
        assert point.params_vector == (0.1, 0.2, 0.3)


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------


class TestCoercion:
    def test_named_param_keys_become_str_and_values_float(self, tmp_path: Path) -> None:
        """Integer-like JSON keys/values must be normalised, not kept as ints."""
        path = _write_jsonl(
            tmp_path,
            [{"params_named": {"alpha": 2, "beta": "3.5"}}],
        )
        point = load_objective_mapping_points(path)[0]

        assert set(point.params_named) == {"alpha", "beta"}
        for value in point.params_named.values():
            assert isinstance(value, float)
        assert point.params_named["alpha"] == 2.0
        assert point.params_named["beta"] == pytest.approx(3.5)

    def test_vector_values_coerced_to_float(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"params_vector": [1, 2, "3"]}])
        point = load_objective_mapping_points(path)[0]
        assert point.params_vector == (1.0, 2.0, 3.0)
        assert all(isinstance(v, float) for v in point.params_vector)

    def test_block_costs_keys_and_values_coerced(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"block_costs": {"flow": "0.5", "head": 1}}])
        point = load_objective_mapping_points(path)[0]
        assert point.block_costs == {"flow": 0.5, "head": 1.0}
        assert all(isinstance(v, float) for v in point.block_costs.values())

    def test_iteration_id_coerced_to_str(self, tmp_path: Path) -> None:
        """A numeric ``iteration_id`` becomes its string form."""
        path = _write_jsonl(tmp_path, [{"iteration_id": 7}])
        point = load_objective_mapping_points(path)[0]
        assert point.iteration_id == "7"
        assert isinstance(point.iteration_id, str)


# ---------------------------------------------------------------------------
# Defaults for missing keys
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_empty_object_yields_neutral_defaults(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{}])
        point = load_objective_mapping_points(path)[0]

        assert point.iteration_id == ""
        assert point.params_named == {}
        assert point.params_vector == ()
        assert point.objective_total is None
        assert point.block_costs == {}
        assert point.status == "unknown"
        assert point.failure_reason is None

    def test_failure_reason_passthrough(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [{"status": "failed", "failure_reason": "solver diverged"}],
        )
        point = load_objective_mapping_points(path)[0]
        assert point.status == "failed"
        assert point.failure_reason == "solver diverged"


# ---------------------------------------------------------------------------
# Empty / missing / whitespace inputs
# ---------------------------------------------------------------------------


class TestEmptyAndMissing:
    def test_missing_path_returns_empty_list(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.jsonl"
        assert load_objective_mapping_points(missing) == []

    def test_directory_path_returns_empty_list(self, tmp_path: Path) -> None:
        """A path that exists but is not a regular file is treated as empty."""
        assert load_objective_mapping_points(tmp_path) == []

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        assert load_objective_mapping_points(path) == []

    def test_blank_and_whitespace_lines_are_skipped(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [
                {"iteration_id": "first"},
                "",
                "   ",
                "\t",
                {"iteration_id": "second"},
            ],
        )
        points = load_objective_mapping_points(path)
        assert [p.iteration_id for p in points] == ["first", "second"]

    def test_trailing_newline_does_not_add_empty_point(self, tmp_path: Path) -> None:
        path = tmp_path / "trailing.jsonl"
        path.write_text(json.dumps({"iteration_id": "only"}) + "\n", encoding="utf-8")
        points = load_objective_mapping_points(path)
        assert len(points) == 1
        assert points[0].iteration_id == "only"


# ---------------------------------------------------------------------------
# Objective extraction and sign / NaN handling
# ---------------------------------------------------------------------------


class TestObjectiveExtraction:
    def test_negative_objective_sign_preserved(self, tmp_path: Path) -> None:
        """No sign flip: a maximised NSE stored as a negative cost stays signed."""
        path = _write_jsonl(
            tmp_path,
            [
                {"iteration_id": "neg", "objective_total": -0.87},
                {"iteration_id": "pos", "objective_total": 0.87},
            ],
        )
        points = load_objective_mapping_points(path)
        by_id = {p.iteration_id: p for p in points}
        assert by_id["neg"].objective_total == pytest.approx(-0.87)
        assert by_id["pos"].objective_total == pytest.approx(0.87)
        # The reader must not collapse opposite signs onto the same magnitude.
        assert by_id["neg"].objective_total != by_id["pos"].objective_total

    def test_objective_string_number_is_parsed(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"objective_total": "1.25"}])
        point = load_objective_mapping_points(path)[0]
        assert point.objective_total == pytest.approx(1.25)

    def test_explicit_null_objective_is_none(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"objective_total": None}])
        point = load_objective_mapping_points(path)[0]
        assert point.objective_total is None

    def test_non_numeric_objective_falls_back_to_none(self, tmp_path: Path) -> None:
        """A non-coercible objective must degrade to ``None``, not raise."""
        path = _write_jsonl(tmp_path, [{"objective_total": "not-a-number"}])
        point = load_objective_mapping_points(path)[0]
        assert point.objective_total is None

    def test_zero_objective_is_preserved_not_treated_as_missing(self, tmp_path: Path) -> None:
        """0.0 is falsy but a valid objective: it must survive as ``0.0``."""
        path = _write_jsonl(tmp_path, [{"objective_total": 0.0}])
        point = load_objective_mapping_points(path)[0]
        assert point.objective_total == 0.0
        assert point.objective_total is not None


# ---------------------------------------------------------------------------
# finite_objective predicate
# ---------------------------------------------------------------------------


class TestFiniteObjective:
    def test_finite_value_is_finite(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"objective_total": 1.0}])
        point = load_objective_mapping_points(path)[0]
        assert point.finite_objective is True

    def test_none_objective_is_not_finite(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{}])
        point = load_objective_mapping_points(path)[0]
        assert point.objective_total is None
        assert point.finite_objective is False

    def test_nan_objective_is_not_finite(self) -> None:
        point = ObjectiveMappingPoint(
            iteration_id="nan",
            params_vector=(),
            params_named={},
            objective_total=float("nan"),
        )
        assert math.isnan(point.objective_total)
        assert point.finite_objective is False

    def test_inf_objective_is_not_finite(self) -> None:
        point = ObjectiveMappingPoint(
            iteration_id="inf",
            params_vector=(),
            params_named={},
            objective_total=float("inf"),
        )
        assert point.finite_objective is False

    def test_zero_objective_is_finite(self) -> None:
        """0.0 is a real, finite objective even though it is falsy."""
        point = ObjectiveMappingPoint(
            iteration_id="zero",
            params_vector=(),
            params_named={},
            objective_total=0.0,
        )
        assert point.finite_objective is True


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_malformed_json_line_raises(self, tmp_path: Path) -> None:
        """An invalid JSON line is a hard error, not a silently dropped row."""
        path = _write_jsonl(
            tmp_path,
            [
                {"iteration_id": "ok"},
                "{not valid json",
            ],
        )
        with pytest.raises(json.JSONDecodeError):
            load_objective_mapping_points(path)

    def test_json_array_line_breaks_dict_assumptions(self, tmp_path: Path) -> None:
        """A top-level JSON array (not an object) must fail loudly."""
        path = _write_jsonl(tmp_path, [[1, 2, 3]])
        with pytest.raises((AttributeError, TypeError)):
            load_objective_mapping_points(path)


# ---------------------------------------------------------------------------
# Frozen dataclass contract
# ---------------------------------------------------------------------------


class TestPointImmutability:
    def test_point_is_frozen(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"iteration_id": "frozen"}])
        point = load_objective_mapping_points(path)[0]
        with pytest.raises(Exception):  # FrozenInstanceError
            point.iteration_id = "mutated"  # type: ignore[misc]
