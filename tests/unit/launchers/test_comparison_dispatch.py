from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.dispatch import (
    resolve_comparison_launcher,
    run_comparison_config,
)


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_neutral_comparison_config_exports_only_canonical_names() -> None:
    from hydromodpy.analysis.comparison.config import (
        ComparisonObservable,
        ComparisonSimulation,
        RuntimeComparisonConfig,
    )

    assert RuntimeComparisonConfig.__name__ == "RuntimeComparisonConfig"
    assert ComparisonObservable.__name__ == "ComparisonObservable"
    assert ComparisonSimulation.__name__ == "ComparisonSimulation"


def test_dispatch_prefers_canonical_comparison_launcher(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_toml(
        tmp_path / "comparison.toml",
        "[comparison]\nbase_simulation_config = 'base.toml'\n"
        "[[comparison.simulation]]\nid = 'sim_a'\nsolver = 'modflow6'\n"
        "[[comparison.observable]]\nname = 'head'\nvariable = 'head'\ncell_index = 0\n",
    )
    captured: dict[str, object] = {}

    class FakeSimulationComparisonLauncher:
        def __init__(self, path: str | Path) -> None:
            captured["path"] = Path(path)

        def run(self) -> dict[str, str]:
            return {"launcher": "simulation_comparison"}

    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.experiment_launcher.SimulationComparisonLauncher",
        FakeSimulationComparisonLauncher,
    )

    summary = run_comparison_config(config_path)

    assert captured["path"] == config_path.resolve()
    assert summary == {"launcher": "simulation_comparison"}


def test_dispatch_rejects_non_comparison_config(tmp_path: Path) -> None:
    config_path = _write_toml(
        tmp_path / "simulation.toml",
        "[simulation]\nname = 'demo'\n",
    )

    with pytest.raises(KeyError, match="\\[comparison\\]"):
        resolve_comparison_launcher(config_path)


def test_dispatch_rejects_comparison_without_simulations(tmp_path: Path) -> None:
    config_path = _write_toml(
        tmp_path / "empty_comparison.toml",
        "[comparison]\ncomparison_id = 'empty'\n",
    )

    with pytest.raises(KeyError, match="comparison\\.simulation"):
        resolve_comparison_launcher(config_path)


def test_hmp_compare_invokes_simulation_comparison_launcher(monkeypatch, tmp_path: Path) -> None:
    import hydromodpy as hmp

    config_path = _write_toml(
        tmp_path / "comparison.toml",
        '[workflow]\nmode = "comparison"\n'
        "[comparison]\nbase_simulation_config = 'base.toml'\n"
        "[[comparison.simulation]]\nid = 'sim_a'\nsolver = 'modflow6'\n"
        "[[comparison.observable]]\nname = 'head'\nvariable = 'head'\ncell_index = 0\n",
    )
    captured: dict[str, object] = {}

    class FakeSimulationComparisonLauncher:
        def __init__(self, path: str | Path) -> None:
            captured["path"] = Path(path)

        def run(self) -> dict[str, str]:
            return {"launcher": "simulation_comparison"}

    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.experiment_launcher.SimulationComparisonLauncher",
        FakeSimulationComparisonLauncher,
    )

    summary = hmp.compare(config_path)

    assert captured["path"] == config_path.resolve()
    assert summary == {"launcher": "simulation_comparison"}
