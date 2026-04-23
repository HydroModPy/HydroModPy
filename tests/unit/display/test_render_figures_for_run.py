"""Coverage for ``hydromodpy.results.display`` - the shared helper used by
both ``hmp display`` and the pipeline ``DisplayStep``.

These tests exercise policy, not rendering:
    * ``enabled=False`` or empty ``figures`` must produce zero output.
    * Unknown figure names are skipped with a warning, never raised.
    * Written files land in ``<output_dir>/<figure>.png``.
    * ``resolve_run_output_dir`` picks the run name when available and
      falls back to a short sim_id otherwise.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.display import (
    render_figures_for_run,
    resolve_run_output_dir,
)


class _StubRun:
    """Minimal Run stand-in - the stubbed figure never reads from it."""

    sim_id = "11111111-2222-3333-4444-555555555555"
    name = "baseline"


class _StubFigure:
    """Stubbed figure that just writes a placeholder PNG."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[Path | None, int]] = []

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        self.calls.append((save_path, dpi))
        if save_path is not None:
            Path(save_path).write_bytes(b"stub-png")


@pytest.fixture
def patched_registry(monkeypatch):
    """Patch the figure lookup so the test never imports matplotlib."""
    stubs: dict[str, _StubFigure] = {}

    def _fake_get(name: str):
        if name not in stubs:
            if name.startswith("bad_"):
                raise KeyError(name)
            stubs[name] = _StubFigure(name)
        return stubs[name]

    import hydromodpy.results.display as mod

    monkeypatch.setattr(mod, "_get_figure", _fake_get)
    return stubs


def test_disabled_config_renders_nothing(tmp_path, patched_registry):
    cfg = DisplayConfig(enabled=False, figures=["piezometric_map"])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert written == []
    assert not out.exists()


def test_empty_figures_list_renders_nothing(tmp_path, patched_registry):
    cfg = DisplayConfig(enabled=True, figures=[])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert written == []


def test_writes_one_file_per_figure(tmp_path, patched_registry):
    cfg = DisplayConfig(enabled=True, figures=["piezometric_map", "hydrograph"])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert sorted(p.name for p in written) == ["hydrograph.png", "piezometric_map.png"]
    assert all(p.exists() for p in written)


def test_unknown_figure_is_skipped_not_raised(tmp_path, patched_registry):
    # The helper must swallow KeyError for unknown figures and keep going -
    # one typo in the TOML must not abort an otherwise-good render batch.
    cfg = DisplayConfig(enabled=True, figures=["bad_missing", "piezometric_map"])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert [p.name for p in written] == ["piezometric_map.png"]


def test_save_false_skips_filesystem(tmp_path, patched_registry):
    cfg = DisplayConfig(enabled=True, save=False, figures=["piezometric_map"])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert written == []
    assert not out.exists()


def test_figure_names_override_shadows_config(tmp_path, patched_registry):
    cfg = DisplayConfig(enabled=True, figures=["piezometric_map", "hydrograph"])
    out = tmp_path / "figures" / "baseline"
    written = render_figures_for_run(
        _StubRun(),
        cfg,
        output_dir=out,
        figure_names=["hydrograph"],
    )
    assert [p.name for p in written] == ["hydrograph.png"]


def test_resolve_run_output_dir_prefers_run_name(tmp_path):
    cfg = DisplayConfig(output_dir=Path("figures"))
    path = resolve_run_output_dir(
        cfg,
        project_root=tmp_path,
        run_name="calib_best",
        sim_id="abcdef1234567890",
    )
    assert path == tmp_path / "figures" / "calib_best"


def test_resolve_run_output_dir_falls_back_to_short_sim_id(tmp_path):
    cfg = DisplayConfig(output_dir=Path("figures"))
    path = resolve_run_output_dir(
        cfg,
        project_root=tmp_path,
        run_name=None,
        sim_id="abcdef1234567890",
    )
    assert path == tmp_path / "figures" / "abcdef12"
