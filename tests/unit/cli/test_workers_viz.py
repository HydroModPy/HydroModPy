"""Unit tests for private ``hmp viz`` workers and wrappers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.cli._workers import viz as viz_worker
from tests._helpers.cli_runner import CliRunner


def test_render_figure_resolves_catalog_and_default_output(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    catalog_root = tmp_path / "catalog"
    calls: dict[str, object] = {}

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            calls["catalog_root"] = root

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def __getitem__(self, sim_ref: str) -> SimpleNamespace:
            calls["sim_ref"] = sim_ref
            return SimpleNamespace(name="sim-a")

    class FakeFigure:
        def plot(self, sim: SimpleNamespace, *, save_path: Path) -> None:
            calls["plot"] = {"sim": sim.name, "save_path": save_path}
            save_path.write_bytes(b"png")

    def fake_find_catalog_root(start: Path) -> Path:
        calls["catalog_search_start"] = start
        return catalog_root

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("hydromodpy.cli.helpers.find_catalog_root", fake_find_catalog_root)
    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    monkeypatch.setattr("hydromodpy.display.get", lambda name: FakeFigure())

    output = viz_worker.render_figure("abc123", "head_map", workspace=workspace)

    expected_output = tmp_path / "figures" / "head_map.png"
    assert output == expected_output
    assert calls == {
        "catalog_search_start": workspace.resolve(),
        "catalog_root": catalog_root,
        "sim_ref": "abc123",
        "plot": {"sim": "sim-a", "save_path": expected_output},
        "closed": True,
    }
    assert expected_output.is_file()


def test_render_gallery_selects_sim_prefix_and_forwards_display_options(
    monkeypatch,
    tmp_path,
) -> None:
    config = tmp_path / "model.toml"
    config.write_text("[display]\n", encoding="utf-8")
    calls: dict[str, object] = {}
    simulations = pd.DataFrame(
        {
            "sim_id": ["ABCD1234", "deff5678"],
            "name": ["baseline", "variant"],
        }
    )

    class FakeDisplayConfig:
        def __init__(self, raw: dict[str, object]) -> None:
            self.raw = raw
            self.show = True

        @classmethod
        def model_validate(cls, raw: dict[str, object]):
            calls["display_raw"] = raw
            return cls(raw)

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            calls["project_root"] = root

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def list_simulations(self, **kwargs: object) -> pd.DataFrame:
            calls["list_kwargs"] = kwargs
            return simulations

        def resolve(self, ref: str, *, project: str | None = None) -> str:
            matches = [
                s for s in simulations["sim_id"].astype(str) if s.lower().startswith(ref.lower())
            ]
            return matches[0]

        def __getitem__(self, sim_id: str) -> SimpleNamespace:
            calls["selected_sim_id"] = sim_id
            return SimpleNamespace(name=f"run-{sim_id}")

    def fake_resolve_run_output_dir(
        display_cfg: FakeDisplayConfig,
        *,
        project_root: Path,
        run_name: str,
        sim_id: str,
    ) -> Path:
        calls["output_request"] = {
            "show": display_cfg.show,
            "project_root": project_root,
            "run_name": run_name,
            "sim_id": sim_id,
        }
        return project_root / "figures" / sim_id

    def fake_render_figures_for_run(
        sim: SimpleNamespace,
        display_cfg: FakeDisplayConfig,
        *,
        output_dir: Path,
        figure_names: list[str] | None,
    ) -> list[Path]:
        calls["render_request"] = {
            "sim": sim.name,
            "show": display_cfg.show,
            "output_dir": output_dir,
            "figure_names": figure_names,
        }
        return [output_dir / "head.png", output_dir / "budget.png"]

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        lambda path: {"display": {"show": True}},
    )
    monkeypatch.setattr("hydromodpy.display.config.DisplayConfig", FakeDisplayConfig)
    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.display.runs.resolve_run_output_dir",
        fake_resolve_run_output_dir,
    )
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        fake_render_figures_for_run,
    )

    paths = viz_worker.render_gallery(
        config,
        sim_ref="abcd",
        only=["head", "budget"],
        no_show=True,
    )

    expected_dir = tmp_path / "figures" / "ABCD1234"
    assert paths == [expected_dir / "head.png", expected_dir / "budget.png"]
    assert calls["project_root"] == tmp_path
    assert calls["display_raw"] == {"show": True}
    assert calls["list_kwargs"] == {
        "config_source": str(config.resolve()),
        "order_by": "created_at DESC",
    }
    assert calls["selected_sim_id"] == "ABCD1234"
    assert calls["output_request"] == {
        "show": False,
        "project_root": tmp_path,
        "run_name": "run-ABCD1234",
        "sim_id": "ABCD1234",
    }
    assert calls["render_request"] == {
        "sim": "run-ABCD1234",
        "show": False,
        "output_dir": expected_dir,
        "figure_names": ["head", "budget"],
    }
    assert calls["closed"] is True


def test_render_gallery_rejects_ambiguous_sim_prefix(monkeypatch, tmp_path) -> None:
    config = tmp_path / "model.toml"
    config.write_text("[display]\n", encoding="utf-8")

    class FakeDisplayConfig:
        @classmethod
        def model_validate(cls, raw: dict[str, object]):
            return cls()

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def list_simulations(self, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"sim_id": ["abcd1111", "abcd2222"], "name": ["a", "b"]})

        def resolve(self, ref: str, *, project: str | None = None) -> str:
            from hydromodpy.results.catalog import AmbiguousReferenceError

            matches = [
                s
                for s in self.list_simulations()["sim_id"].astype(str)
                if s.lower().startswith(ref.lower())
            ]
            if len(matches) > 1:
                raise AmbiguousReferenceError(ref, [(m, None) for m in matches])
            return matches[0]

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        lambda path: {"display": {}},
    )
    monkeypatch.setattr("hydromodpy.display.config.DisplayConfig", FakeDisplayConfig)
    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)

    from hydromodpy.results.catalog import AmbiguousReferenceError

    with pytest.raises(AmbiguousReferenceError):
        viz_worker.render_gallery(config, sim_ref="abcd")


def test_viz_gallery_cli_splits_only_and_maps_missing_run(monkeypatch, tmp_path) -> None:
    config = tmp_path / "model.toml"
    config.write_text("[display]\n", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_render_gallery(config_toml: str, **kwargs: object) -> list[Path]:
        calls["config_toml"] = config_toml
        calls["kwargs"] = kwargs
        raise FileNotFoundError("No run named 'baseline'")

    monkeypatch.setattr("hydromodpy.cli._workers.viz.render_gallery", fake_render_gallery)

    result = CliRunner().invoke(
        [
            "viz",
            "gallery",
            str(config),
            "--run",
            "baseline",
            "--latest",
            "2",
            "--only",
            "head, budget,,",
            "--no-show",
        ]
    )

    assert result.exit_code == 10
    assert calls == {
        "config_toml": str(config),
        "kwargs": {
            "run_name": "baseline",
            "sim_ref": None,
            "all_runs": False,
            "latest": 2,
            "only": ["head", "budget"],
            "no_show": True,
        },
    }
    assert "No run named 'baseline'" in result.stderr
