"""Unit tests for regression helper robustness."""

from __future__ import annotations

import shutil
from pathlib import Path

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
