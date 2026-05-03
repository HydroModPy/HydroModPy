"""Unit tests for regression helper robustness."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from tests.regression import golden_utils


def test_resolve_tiered_results_dir_retries_transient_permission_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Transient Windows locks should not fail regression output cleanup."""

    run_name = "launcher_simulation_outputs"
    out_dir = tmp_path / "extensive" / run_name
    out_dir.mkdir(parents=True)
    (out_dir / "stale.txt").write_text("stale", encoding="utf-8")

    calls = {"count": 0}
    sleeps: list[float] = []
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError(32, "The process cannot access the file")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setenv("HYDROMODPY_OUT_PATH", str(tmp_path))
    monkeypatch.setattr(golden_utils.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(golden_utils.time, "sleep", sleeps.append)
    monkeypatch.setattr(golden_utils.gc, "collect", lambda: None)

    resolved = golden_utils.resolve_tiered_results_dir(
        test_file=tmp_path / "tests" / "regression" / "extensive" / "test_dummy.py",
        run_name=run_name,
    )

    assert resolved == out_dir
    assert resolved.exists()
    assert list(resolved.iterdir()) == []
    assert calls["count"] == 2
    assert sleeps == [golden_utils.remove_tree_with_retry.__kwdefaults__["base_delay_s"]]


def test_write_golden_reference_injects_schema_version(tmp_path: Path) -> None:
    """Freshly written goldens carry the current ``GOLDEN_SCHEMA_VERSION``."""
    target = tmp_path / "golden.json"
    golden_utils.write_golden_reference(target, {"modflow_expected": {}})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["_schema_version"] == golden_utils.GOLDEN_SCHEMA_VERSION
    assert "modflow_expected" in payload


def test_update_or_assert_goldens_rejects_incompatible_schema(tmp_path: Path) -> None:
    """A golden tagged with an older schema version fails loudly."""
    target = tmp_path / "golden.json"
    target.write_text(
        json.dumps({"_schema_version": "0.9", "modflow_expected": {}}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="schema version"):
        golden_utils.update_or_assert_goldens(
            actual={"modflow_expected": {}},
            golden_reference_file=target,
            update_goldens=False,
        )


def test_update_or_assert_goldens_accepts_legacy_unversioned(tmp_path: Path) -> None:
    """Pre-versioning goldens (no ``_schema_version`` key) still compare."""
    target = tmp_path / "golden.json"
    target.write_text(
        json.dumps({"modflow_expected": {}}),
        encoding="utf-8",
    )
    # Should not raise: missing version is treated as the current schema.
    golden_utils.update_or_assert_goldens(
        actual={"modflow_expected": {}},
        golden_reference_file=target,
        update_goldens=False,
    )


def test_array_stats_masks_variable_nodata_sentinels() -> None:
    """Stats should ignore nodata sentinels declared for the target variable."""
    stats = golden_utils.array_stats(
        np.array([1.0, -9999.0, 3.0, np.nan, 1.0e30]),
        variable="watertable_elevation",
    )

    assert stats["count"] == 2
    assert stats["nodata_count"] == 2
    assert stats["mean"] == pytest.approx(2.0)
    assert stats["p50"] == pytest.approx(2.0)


def test_array_stats_preserves_same_values_for_unmapped_variables() -> None:
    """Only variable-specific nodata masks should change numeric signatures."""
    stats = golden_utils.array_stats(np.array([1.0, -9999.0, 3.0]), variable="time")

    assert stats["count"] == 3
    assert stats["nodata_count"] == 0
    assert stats["p50"] == pytest.approx(1.0)


def test_array_stats_masks_transport_nodata_limits() -> None:
    """Transport outputs should mask propagated nodata magnitudes."""
    stats = golden_utils.array_stats(
        np.array([1.0e-9, 1.0e25, 3.0e-9]),
        variable="mass_seepage",
    )

    assert stats["count"] == 2
    assert stats["nodata_count"] == 1
    assert stats["mean"] == pytest.approx(2.0e-9)


def test_resolve_tiered_results_dir_retries_when_rmtree_onerror_hits_locked_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Windows onerror callbacks should defer locked files to the retry loop."""

    run_name = "launcher_simulation_outputs"
    out_dir = tmp_path / "extensive" / run_name
    out_dir.mkdir(parents=True)
    locked_file = out_dir / "stale.txt"
    locked_file.write_text("stale", encoding="utf-8")

    calls = {"count": 0}
    sleeps: list[float] = []
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            onerror = kwargs["onerror"]

            def locked_unlink(target):
                raise PermissionError(32, "The process cannot access the file", str(target))

            onerror(
                locked_unlink,
                str(locked_file),
                (
                    PermissionError,
                    PermissionError(32, "The process cannot access the file", str(locked_file)),
                    None,
                ),
            )
            raise OSError(145, "Directory not empty", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setenv("HYDROMODPY_OUT_PATH", str(tmp_path))
    monkeypatch.setattr(golden_utils.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(golden_utils.time, "sleep", sleeps.append)
    monkeypatch.setattr(golden_utils.gc, "collect", lambda: None)

    resolved = golden_utils.resolve_tiered_results_dir(
        test_file=tmp_path / "tests" / "regression" / "extensive" / "test_dummy.py",
        run_name=run_name,
    )

    assert resolved == out_dir
    assert resolved.exists()
    assert list(resolved.iterdir()) == []
    assert calls["count"] == 2
    assert sleeps == [golden_utils.remove_tree_with_retry.__kwdefaults__["base_delay_s"]]
