"""A read-only catalog holding one run, and a figure that records what it draws.

Shared by the tests of ``hydromodpy.display.catalog_figures`` and of ``hmp viz``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.layout import RUNS_DIRNAME


class OneRunCatalog:
    """A read-only catalog holding one run, the way ``hmp viz show`` opens it."""

    def __init__(self, root: Path) -> None:
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


class Figure:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.saved: list[Path] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> str | None:
        return self.reason

    def plot(self, sim: SimpleNamespace, *, save_path: Path, **opts: object) -> str:
        self.saved.append(save_path)
        save_path.write_bytes(b"png")
        return "figure"


def one_run_workspace(monkeypatch, tmp_path: Path, figure: Figure) -> None:
    monkeypatch.setattr(
        "hydromodpy.core.state.result_dirs.resolve_project_root", lambda start: tmp_path
    )
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", OneRunCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: figure)
