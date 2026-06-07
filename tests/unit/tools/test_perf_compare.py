"""Unit tests for the ratio-based performance regression gate.

The gate compares pairwise benchmark median ratios between baseline and current
runs. These tests pin the three properties that make the gate trustworthy on a
CI runner whose absolute speed differs from the baseline machine:

* identical medians -> no regression,
* every median scaled uniformly -> no regression (machine factor neutralized),
* a single benchmark median doubled -> regression detected.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_perf_compare_module() -> object:
    module_path = Path("tools/ci/perf_compare.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "perf_compare_test_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def perf_compare() -> object:
    return _load_perf_compare_module()


def _write_benchmark_json(path: Path, medians: dict[str, float]) -> None:
    payload = {
        "benchmarks": [
            {"fullname": name, "stats": {"median": median}} for name, median in medians.items()
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compute_ratios_includes_every_ordered_pair(perf_compare: object) -> None:
    values = {"a": 1.0, "b": 2.0, "c": 4.0}
    ratios = perf_compare.compute_ratios(values)

    assert set(ratios) == {("a", "b"), ("a", "c"), ("b", "c")}
    assert ratios[("a", "b")] == pytest.approx(0.5)
    assert ratios[("a", "c")] == pytest.approx(0.25)
    assert ratios[("b", "c")] == pytest.approx(0.5)


def test_compute_ratios_skips_non_positive_values(perf_compare: object) -> None:
    values = {"a": 1.0, "b": 0.0, "c": 4.0}
    ratios = perf_compare.compute_ratios(values)

    assert ("a", "c") in ratios
    assert all("b" not in pair for pair in ratios)


def test_gate_passes_against_identical_baseline(
    perf_compare: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    medians = {"bench/a": 0.001, "bench/b": 0.002, "bench/c": 0.004}
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_benchmark_json(baseline, medians)
    _write_benchmark_json(current, medians)

    rc = perf_compare.main(
        ["--baseline", str(baseline), "--current", str(current), "--threshold", "0.30"]
    )
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_gate_passes_when_every_benchmark_scaled_uniformly(
    perf_compare: object, tmp_path: Path
) -> None:
    """Machine factor: doubling every median preserves all ratios."""

    base_medians = {"bench/a": 0.001, "bench/b": 0.002, "bench/c": 0.004}
    scaled_medians = {name: median * 2.0 for name, median in base_medians.items()}

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_benchmark_json(baseline, base_medians)
    _write_benchmark_json(current, scaled_medians)

    rc = perf_compare.main(
        ["--baseline", str(baseline), "--current", str(current), "--threshold", "0.30"]
    )
    assert rc == 0


def test_gate_fails_when_single_benchmark_doubles(
    perf_compare: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base_medians = {"bench/a": 0.001, "bench/b": 0.002, "bench/c": 0.004}
    current_medians = dict(base_medians)
    current_medians["bench/b"] = base_medians["bench/b"] * 2.0

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_benchmark_json(baseline, base_medians)
    _write_benchmark_json(current, current_medians)

    rc = perf_compare.main(
        ["--baseline", str(baseline), "--current", str(current), "--threshold", "0.30"]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL" in err


def test_gate_writes_report_when_path_given(perf_compare: object, tmp_path: Path) -> None:
    medians = {"bench/a": 0.001, "bench/b": 0.002}
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    report = tmp_path / "report.md"
    _write_benchmark_json(baseline, medians)
    _write_benchmark_json(current, medians)

    rc = perf_compare.main(
        [
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--threshold",
            "0.30",
            "--report",
            str(report),
        ]
    )
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert "ratio-based" in text
    assert "bench/a" in text and "bench/b" in text


def test_gate_returns_two_when_baseline_missing(perf_compare: object, tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    _write_benchmark_json(current, {"bench/a": 0.001})
    rc = perf_compare.main(
        ["--baseline", str(tmp_path / "missing.json"), "--current", str(current)]
    )
    assert rc == 2


def test_gate_ignores_new_benchmarks_in_current(perf_compare: object, tmp_path: Path) -> None:
    """A benchmark introduced only in current must not block the gate."""

    base_medians = {"bench/a": 0.001, "bench/b": 0.002}
    current_medians = {"bench/a": 0.001, "bench/b": 0.002, "bench/new": 0.010}

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_benchmark_json(baseline, base_medians)
    _write_benchmark_json(current, current_medians)

    rc = perf_compare.main(
        ["--baseline", str(baseline), "--current", str(current), "--threshold", "0.30"]
    )
    assert rc == 0
