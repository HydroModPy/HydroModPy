"""The value digests of a run: what the seal compares, taken from the store or from the writer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zarr

from hydromodpy.core.io.value_digest import ValueDigester, value_digest
from hydromodpy.results.record.values import (
    QUANTIZATION_ATTR,
    run_value_digests,
    stored_value_digests,
    value_deltas,
)

HEAD = np.asarray(
    [[1.2345678901234567, 2.3456789012345678], [np.nan, 4.567890123456789]],
    dtype=np.float64,
)


def _rounded_store(run_dir: Path) -> zarr.Group:
    group = zarr.open_group(str(run_dir / "fields.zarr"), mode="w")
    heads = group.create_array(
        "heads", shape=HEAD.shape, dtype="float32", dimension_names=("time", "cell")
    )
    heads[:] = HEAD
    heads.attrs[QUANTIZATION_ATTR] = {"method": "stored"}
    cells = group.create_array("cells", shape=(2,), dtype="float64")
    cells[:] = [10.0, 20.0]
    return group


def _facts(field_digests: dict[str, dict[str, str]]) -> SimpleNamespace:
    return SimpleNamespace(field_digests=field_digests)


def _writer_digests(array: np.ndarray) -> dict[str, str]:
    digester = ValueDigester()
    for step in range(array.shape[0]):
        digester.update(step, array[step])
    return {str(step): value_digest(array[step]) for step in range(array.shape[0])}


def _write_table(run_dir: Path) -> None:
    tables = run_dir / "tables.parquet"
    tables.mkdir()
    pq.write_table(
        pa.table(
            {
                "sim_id": ["s"],
                "duration_s": pa.array([1.5], type=pa.float64()),
                "value": pa.array([3.5], type=pa.float64()),
            }
        ),
        tables / "simulation.parquet",
    )


def test_a_step_the_writer_never_recorded_is_folded_from_the_stored_fill_value(tmp_path: Path):
    group = _rounded_store(tmp_path)
    registry = {"heads": {"0": value_digest(HEAD[0])}}
    digests = run_value_digests(tmp_path, _facts(registry))

    expected = ValueDigester()
    expected.update(0, HEAD[0])
    expected.update(1, np.asarray(group["heads"][1]))
    assert digests.digests["fields/heads"] == expected.digest(2)


def test_a_moved_column_is_measured_in_absolute_and_relative_terms(tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    for run_dir, value in ((first, 3.0), (second, 4.0)):
        (run_dir / "tables.parquet").mkdir(parents=True)
        pq.write_table(
            pa.table({"value": pa.array([value, 0.0], type=pa.float64())}),
            run_dir / "tables.parquet" / "t.parquet",
        )

    measured = value_deltas(first, second, {"tables/t/value"})

    assert measured["tables/t/value"]["max_abs"] == 1.0
    assert measured["tables/t/value"]["rel_l2"] == pytest.approx(1.0 / 3.0)
    assert measured["tables/t/value"]["precision"] == "exact"


def test_a_key_one_side_does_not_store_has_no_measure(tmp_path: Path):
    (tmp_path / "a").mkdir()
    group = zarr.open_group(str(tmp_path / "a" / "fields.zarr"), mode="w")
    group.create_array("heads", shape=(1,), dtype="float64")[:] = [1.0]

    measured = value_deltas(tmp_path / "a", tmp_path / "b", {"fields/heads"})

    assert measured["fields/heads"] == {
        "max_abs": None,
        "rel_l2": None,
        "precision": None,
        "reason": None,
    }


def _write_metrics(run_dir: Path, clock: float, value: float = 0.9) -> None:
    tables = run_dir / "tables.parquet"
    tables.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "metric": ["nse", "flow_solve_time_seconds"],
                "value": pa.array([value, clock], type=pa.float64()),
            }
        ),
        tables / "metrics.parquet",
    )


def test_the_wall_clock_row_of_metrics_is_left_out_of_the_digest(tmp_path: Path):
    _write_metrics(tmp_path / "a", clock=1.0)
    _write_metrics(tmp_path / "b", clock=7.0)

    first = stored_value_digests(tmp_path / "a").digests
    assert first == stored_value_digests(tmp_path / "b").digests
    assert first["tables/metrics/value"] == value_digest(np.asarray([0.9]))


def test_the_wall_clock_row_is_left_out_of_a_measure_too(tmp_path: Path):
    _write_metrics(tmp_path / "a", clock=1.0, value=0.5)
    _write_metrics(tmp_path / "b", clock=7.0, value=0.75)

    measured = value_deltas(tmp_path / "a", tmp_path / "b", {"tables/metrics/value"})

    assert measured["tables/metrics/value"]["max_abs"] == 0.25


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    [
        ([1.0, 2.0], [1.0, 2.0, 3.0], "shape"),
        ([1.0, np.nan], [1.0, 2.0], "nan_pattern"),
        ([0.0, 0.0], [0.0, 1.0], "zero_norm"),
    ],
)
def test_a_difference_no_number_measures_is_null_with_its_reason(tmp_path, left, right, reason):
    for name, values in (("a", left), ("b", right)):
        group = zarr.open_group(str(tmp_path / name / "fields.zarr"), mode="w")
        group.create_array("heads", shape=(len(values),), dtype="float64")[:] = values

    measured = value_deltas(tmp_path / "a", tmp_path / "b", {"fields/heads"})["fields/heads"]

    assert measured["rel_l2"] is None
    assert measured["reason"] == reason
    assert json.dumps(measured, allow_nan=False)


def _fold(array: np.ndarray) -> str:
    digester = ValueDigester()
    for step in range(array.shape[0]):
        digester.update(step, array[step])
    return digester.digest(array.shape[0])
