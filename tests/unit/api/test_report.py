"""Unit tests for ``hmp.report``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def test_report_with_explicit_workspace(monkeypatch, tmp_path: Path) -> None:
    """``hmp.report`` resolves the session id via the catalog and renders."""
    captured: dict = {}

    class FakeCatalog:
        def __init__(self, workspace_root):
            captured["catalog_workspace"] = workspace_root

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            captured["closed"] = True

    def fake_resolve_session(catalog, raw):
        captured["resolve_catalog"] = catalog
        captured["raw"] = raw
        return "abcdef0123456789"

    def fake_render(*, catalog, session_id, workspace_root):
        captured["render_session_id"] = session_id
        captured["render_workspace_root"] = workspace_root
        return Path("/tmp/report.html")

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.calibration.report.resolve_calibration_session_id",
        fake_resolve_session,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.calibration.step_render_calibration_report",
        fake_render,
    )

    result = hmp.report("ab12cd34", workspace=tmp_path)
    assert result == Path("/tmp/report.html")
    assert captured["catalog_workspace"] == tmp_path.resolve()
    assert captured["raw"] == "ab12cd34"
    assert captured["render_session_id"] == "abcdef0123456789"
    assert captured["render_workspace_root"] == tmp_path.resolve()
    assert captured["closed"] is True


def test_report_default_workspace_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    """When ``workspace`` is ``None``, the helper walks up from cwd."""
    catalog_file = tmp_path / "catalog.duckdb"
    catalog_file.touch()
    monkeypatch.chdir(tmp_path)
    captured: dict = {}

    class FakeCatalog:
        def __init__(self, workspace_root):
            captured["workspace_root"] = Path(workspace_root)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.calibration.report.resolve_calibration_session_id",
        lambda catalog, raw: "session",
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.calibration.step_render_calibration_report",
        lambda **kwargs: Path("/tmp/report.html"),
    )

    hmp.report()
    assert captured["workspace_root"] == tmp_path


def test_report_propagates_session_lookup_error(monkeypatch, tmp_path: Path) -> None:
    """Errors from session resolution propagate to the caller."""

    class FakeCatalog:
        def __init__(self, workspace_root):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    def fake_resolve(catalog, raw):
        raise FileNotFoundError("no session")

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    monkeypatch.setattr(
        "hydromodpy.calibration.report.resolve_calibration_session_id", fake_resolve
    )

    with pytest.raises(FileNotFoundError, match="no session"):
        hmp.report("bad", workspace=tmp_path)
