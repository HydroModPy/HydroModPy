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
        ComparisonConfig,
        ComparisonObservable,
        ComparisonVariant,
    )

    assert ComparisonConfig.__name__ == "ComparisonConfig"
    assert ComparisonObservable.__name__ == "ComparisonObservable"
    assert ComparisonVariant.__name__ == "ComparisonVariant"


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


def test_dispatch_rejects_removed_variant_comparison_entries(tmp_path: Path) -> None:
    config_path = _write_toml(
        tmp_path / "variant_comparison.toml",
        "[comparison]\ncomparison_id = 'variant_demo'\n"
        "[[comparison.variant]]\nid = 'reference'\nrun_folder = 'runs/reference'\n"
        "[[comparison.observable]]\nname = 'head'\nvariable = 'head'\ncell_index = 0\n",
    )

    with pytest.raises(ValueError, match="comparison\\.variant.*removed"):
        resolve_comparison_launcher(config_path)


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


def test_dispatch_rejects_removed_method_comparison_section(tmp_path: Path) -> None:
    config_path = _write_toml(
        tmp_path / "removed.toml",
        "[method_comparison]\ncomparison_id = 'removed'\n",
    )

    with pytest.raises(KeyError, match="\\[comparison\\]"):
        resolve_comparison_launcher(config_path)


def test_project_compare_uses_comparison_dispatch(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.project import Project

    config_path = tmp_path / "comparison.toml"
    captured: dict[str, object] = {}

    def fake_run_comparison_config(path: str | Path) -> dict[str, str]:
        captured["path"] = Path(path)
        return {"launcher": "dispatch"}

    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.dispatch.run_comparison_config",
        fake_run_comparison_config,
    )

    project = object.__new__(Project)
    project._config_path = config_path

    summary = project.compare()

    assert captured["path"] == config_path
    assert summary == {"launcher": "dispatch"}
