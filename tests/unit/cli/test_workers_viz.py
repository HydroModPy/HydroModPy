"""Unit tests for private ``hmp viz`` workers and wrappers."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.cli._workers import viz as viz_worker
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.display.runs import FigureRenderReport, SkippedFigure
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from tests._helpers.cli_runner import CliRunner


def test_render_figure_defaults_to_the_figures_dir_of_the_run(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    catalog_root = tmp_path / "catalog"
    run_dir = catalog_root / RUNS_DIRNAME / "sim_a"
    calls: dict[str, object] = {}

    class FakeCatalog:
        def __init__(self, root: Path, *, read_only: bool = False) -> None:
            calls["catalog_root"] = root
            calls["read_only"] = read_only

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def resolve(self, sim_ref: str) -> str:
            calls["sim_ref"] = sim_ref
            return "sim-001"

        def run_dir_for(self, sid: str) -> Path:
            calls["run_dir_for"] = sid
            return run_dir

        def __getitem__(self, sid: str) -> SimpleNamespace:
            calls["sim_id"] = sid
            return SimpleNamespace(name="sim-a")

    class FakeFigure:
        def unavailable_reason(self, sim: SimpleNamespace) -> None:
            return None

        def plot(self, sim: SimpleNamespace, *, save_path: Path, **opts: object) -> str:
            calls["plot"] = {"sim": sim.name, "save_path": save_path, "opts": opts}
            save_path.write_bytes(b"png")
            return "figure"

    def fake_resolve_project_root(start: Path) -> Path:
        calls["catalog_search_start"] = start
        return catalog_root

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "hydromodpy.core.state.paths.resolve_project_root", fake_resolve_project_root
    )
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: FakeFigure())

    output = viz_worker.render_figure("abc123", "head_map", workspace=workspace)

    expected_output = run_dir / RUN_FIGURES_DIRNAME / "head_map.png"
    assert output == expected_output
    assert calls == {
        "catalog_search_start": workspace.resolve(),
        "catalog_root": catalog_root,
        "read_only": True,
        "sim_ref": "abc123",
        "run_dir_for": "sim-001",
        "sim_id": "sim-001",
        "plot": {"sim": "sim-a", "save_path": expected_output, "opts": {}},
        "closed": True,
    }
    assert expected_output.is_file()


class _OneRunCatalog:
    """A read-only catalog holding one run, the way ``hmp viz show`` opens it."""

    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def resolve(self, sim_ref: str) -> str:
        return "sim-001"

    def run_dir_for(self, sid: str) -> Path:
        return self.root / RUNS_DIRNAME / "sim_a"

    def __getitem__(self, sid: str) -> SimpleNamespace:
        return SimpleNamespace(name="sim-a")


class _Figure:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.saved: list[Path] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> str | None:
        return self.reason

    def plot(self, sim: SimpleNamespace, *, save_path: Path, **opts: object) -> str:
        self.saved.append(save_path)
        save_path.write_bytes(b"png")
        return "figure"


def _one_run_workspace(monkeypatch, tmp_path: Path, figure: _Figure) -> None:
    monkeypatch.setattr("hydromodpy.core.state.paths.resolve_project_root", lambda start: tmp_path)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", _OneRunCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: figure)


class _SealedRunCatalog(_OneRunCatalog):
    """One run whose sealed ``[display]`` names October and a south-north cut."""

    def __getitem__(self, sid: str) -> SimpleNamespace:
        from hydromodpy.display.config import DisplayConfig

        display = DisplayConfig().model_dump(mode="json")
        display.update(time="2002-10-15", overrides={"cross_section": {"orientation": "sn"}})
        return SimpleNamespace(
            name="sim-a",
            config_snapshot={"display": display},
            step_at=lambda time: {"2002-10-15": 33, "first": 0}[time],
        )


class _InstantFigure:
    """A map that draws one instant and records what it was asked for."""

    def __init__(self) -> None:
        self.drawn: list[dict] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> None:
        return None

    def plot(self, sim, *, save_path: Path, timestep=None, orientation="we", **_) -> str:
        self.drawn.append({"timestep": timestep, "orientation": orientation})
        save_path.write_bytes(b"png")
        return "figure"


@pytest.mark.parametrize(("time", "step"), [(None, 33), ("first", 0)])
def test_a_redraw_applies_the_display_of_the_run_and_time_replaces_its_instant(
    monkeypatch, tmp_path, time, step
) -> None:
    figure = _InstantFigure()
    _one_run_workspace(monkeypatch, tmp_path, figure)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", _SealedRunCatalog)

    viz_worker.render_figure("abc123", "cross_section", workspace=tmp_path, time=time)

    assert figure.drawn == [{"timestep": step, "orientation": "sn"}]


def test_viz_show_passes_time_to_the_worker(monkeypatch) -> None:
    from hydromodpy.cli.commands.viz import show

    seen: dict[str, object] = {}

    def _worker(sim_ref, figure, **kwargs):
        seen.update(kwargs, sim_ref=sim_ref, figure=figure)
        return Path("out.png")

    monkeypatch.setattr("hydromodpy.cli._workers.viz.render_figure", _worker)
    parser = argparse.ArgumentParser()
    show.register(parser.add_subparsers())
    args = parser.parse_args(["show", "abc123", "seepage_map", "--time", "2002-10-15"])

    show.run(args)

    assert seen["time"] == "2002-10-15"
    assert seen["figure"] == "seepage_map"


def test_an_output_without_a_suffix_is_written_and_named_as_png(monkeypatch, tmp_path) -> None:
    figure = _Figure()
    _one_run_workspace(monkeypatch, tmp_path, figure)

    output = viz_worker.render_figure(
        "abc123", "head_map", workspace=tmp_path, output=tmp_path / "maps" / "head"
    )

    assert output == tmp_path / "maps" / "head.png"
    assert figure.saved == [output]
    assert output.is_file()


def test_viz_show_names_the_file_it_wrote(monkeypatch, tmp_path) -> None:
    _one_run_workspace(monkeypatch, tmp_path, _Figure())

    result = CliRunner().invoke(
        ["viz", "show", "abc123", "head_map", "--output", str(tmp_path / "head")]
    )

    assert result.exit_code == 0
    assert f"wrote {tmp_path / 'head.png'}" in result.stderr


def test_viz_show_refuses_a_figure_the_run_cannot_feed(monkeypatch, tmp_path) -> None:
    figure = _Figure(reason="missing result field(s): watertable_depth")
    _one_run_workspace(monkeypatch, tmp_path, figure)

    result = CliRunner().invoke(["viz", "show", "abc123", "head_map"])

    assert result.exit_code == 1
    assert (
        "figure 'head_map' does not apply to this run: missing result field(s): watertable_depth"
    ) in result.stderr
    assert figure.saved == []


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
        def __init__(self, root: Path, *, read_only: bool = False) -> None:
            calls["project_root"] = root
            calls["read_only"] = read_only

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
    ) -> FigureRenderReport:
        calls["render_request"] = {
            "sim": sim.name,
            "show": display_cfg.show,
            "output_dir": output_dir,
            "figure_names": figure_names,
        }
        return FigureRenderReport(
            requested=("head", "budget"),
            rendered=("head", "budget"),
            written=(output_dir / "head.png", output_dir / "budget.png"),
        )

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        lambda path: {"display": {"show": True}},
    )
    monkeypatch.setattr("hydromodpy.display.config.DisplayConfig", FakeDisplayConfig)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)
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
    # Project-relative, never absolute: a copied project must recognise its runs.
    assert calls["list_kwargs"] == {
        "config_source": config.name,
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


def test_render_gallery_summarizes_a_figure_it_could_not_produce(monkeypatch, tmp_path) -> None:
    # Same contract as the run path: the gallery never drops a requested
    # figure without a visible line naming it and why.
    config = tmp_path / "model.toml"
    config.write_text("[display]\n", encoding="utf-8")

    class FakeDisplayConfig:
        show = True

        @classmethod
        def model_validate(cls, raw: dict[str, object]):
            return cls()

    class FakeCatalog:
        def __init__(self, root: Path, *, read_only: bool = False) -> None:
            self.root = root
            self.read_only = read_only

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def list_simulations(self, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"sim_id": ["abcd1111"], "name": ["baseline"]})

        def __getitem__(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(name="baseline")

    monkeypatch.setattr(
        "hydromodpy.core.toml_io.loader.load_toml_with_base_config",
        lambda path: {"display": {}},
    )
    monkeypatch.setattr("hydromodpy.display.config.DisplayConfig", FakeDisplayConfig)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.display.runs.resolve_run_output_dir",
        lambda cfg, *, project_root, run_name, sim_id: project_root / "figures" / run_name,
    )
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        lambda sim, cfg, *, output_dir, figure_names: FigureRenderReport(
            requested=("piezometric_map", "calibration_convergence"),
            rendered=("piezometric_map",),
            written=(output_dir / "piezometric_map.png",),
            skipped=(
                SkippedFigure(
                    name="calibration_convergence",
                    reason="missing catalog table(s): calibration_trials",
                ),
            ),
        ),
    )

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    summary_logger = get_logger("hydromodpy.display.runs")
    previous_level = summary_logger.level
    summary_logger.setLevel(logging.INFO)
    summary_logger.addHandler(handler)
    try:
        paths = viz_worker.render_gallery(config, no_show=True)
    finally:
        summary_logger.removeHandler(handler)
        summary_logger.setLevel(previous_level)

    assert paths == [tmp_path / "figures" / "baseline" / "piezometric_map.png"]
    # Each run gets its summary as on the run path: a figure inapplicable to
    # the run is counted, then named at INFO, never dropped.
    messages = [(r.levelname, r.getMessage()) for r in records]
    assert [level for level, _ in messages] == ["INFO", "INFO"]
    assert messages[0][1].startswith("Rendered 1/2 figure(s)")
    assert messages[0][1].endswith("; 1 not applicable to this run")
    assert messages[1][1] == (
        "Not applicable to this run: "
        "calibration_convergence (missing catalog table(s): calibration_trials)"
    )


def test_render_gallery_reads_an_old_key_as_hmp_run_does(monkeypatch, tmp_path) -> None:
    # `hmp run` renames the old per-figure `timestep` in memory before
    # validation. The gallery reads the same file the same way, so the two
    # commands load and report an old key alike.
    import warnings

    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    config = tmp_path / "model.toml"
    config.write_text(
        '[display]\nfigures = ["seepage_map"]\n[display.overrides.seepage_map]\ntimestep = 33\n',
        encoding="utf-8",
    )

    class FakeCatalog:
        def __init__(self, root: Path, *, read_only: bool = False) -> None:
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def list_simulations(self, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"sim_id": ["abcd1111"], "name": ["baseline"]})

        def __getitem__(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(name="baseline")

    seen: list[object] = []

    def _render(sim, cfg, *, output_dir, figure_names):
        seen.append(cfg)
        return FigureRenderReport(requested=(), rendered=(), written=(), skipped=())

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.display.runs.resolve_run_output_dir",
        lambda cfg, *, project_root, run_name, sim_id: project_root / "figures" / run_name,
    )
    monkeypatch.setattr("hydromodpy.display.runs.render_figures_for_run", _render)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        viz_worker.render_gallery(config, no_show=True)

    assert seen[0].overrides == {"seepage_map": {"time": 33}}
    assert not [w for w in caught if issubclass(w.category, ConfigKeyRenamedWarning)]


def test_render_gallery_rejects_ambiguous_sim_prefix(monkeypatch, tmp_path) -> None:
    config = tmp_path / "model.toml"
    config.write_text("[display]\n", encoding="utf-8")

    class FakeDisplayConfig:
        @classmethod
        def model_validate(cls, raw: dict[str, object]):
            return cls()

    class FakeCatalog:
        def __init__(self, root: Path, *, read_only: bool = False) -> None:
            self.root = root
            self.read_only = read_only

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
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)

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


def _availability(sim_ref: str, *, workspace: object = None):
    from hydromodpy.display.figure import FigureSpec

    return [
        (FigureSpec(name="piezometric_map", title="p", kind="spatial"), None),
        (
            FigureSpec(name="particle_tracks", title="t", kind="particles"),
            "missing result field(s): particles",
        ),
    ]


def test_viz_list_run_says_which_figures_the_run_supports(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["piezometric_map", "spatial", "available"]
    assert lines[1].split()[:2] == ["particle_tracks", "particles"]
    assert lines[1].endswith("missing result field(s): particles")
    assert "2 figure(s), 1 available for abc123" in result.stdout


def test_viz_list_run_keeps_the_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123", "--kind", "particles"])

    assert "piezometric_map" not in result.stdout
    assert "1 figure(s), 0 available for abc123" in result.stdout


def test_viz_list_run_maps_an_unknown_run_to_not_found(monkeypatch) -> None:
    from hydromodpy.results.catalog import SimulationNotFoundError

    def unknown(sim_ref: str, *, workspace: object = None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", unknown)

    result = CliRunner().invoke(["viz", "list", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr
