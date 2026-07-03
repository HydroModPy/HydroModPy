"""Unit tests for ``hmp.report``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from tests._helpers.api_doubles import make_capturing_catalog

pytestmark = pytest.mark.fast


def test_report_with_explicit_workspace(monkeypatch, tmp_path: Path) -> None:
    """``hmp.report`` resolves the session across the workspace, then renders."""
    captured: dict = {}

    def fake_resolve(workspace_root, raw):
        captured["resolve_workspace"] = workspace_root
        captured["raw"] = raw
        return tmp_path, "abcdef0123456789"

    def fake_render(*, catalog, session_id, workspace_root):
        captured["render_session_id"] = session_id
        captured["render_workspace_root"] = workspace_root
        return Path("/tmp/report.html")

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", make_capturing_catalog(captured))
    monkeypatch.setattr("hydromodpy.calibration.report.resolve_session_in_workspace", fake_resolve)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.calibration.step_render_calibration_report", fake_render
    )

    result = hmp.report("ab12cd34", workspace=tmp_path)
    assert result == Path("/tmp/report.html")
    assert captured["resolve_workspace"] == tmp_path.resolve()
    assert captured["raw"] == "ab12cd34"
    # The catalog opened for rendering is the project root the resolver returned.
    assert captured["workspace_root"] == tmp_path
    assert captured["render_session_id"] == "abcdef0123456789"
    assert captured["render_workspace_root"] == tmp_path
    assert captured["closed"] is True


def test_report_default_workspace_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    """When ``workspace`` is ``None``, the helper walks up from cwd."""
    catalog_file = tmp_path / "catalog.duckdb"
    catalog_file.touch()
    monkeypatch.chdir(tmp_path)
    captured: dict = {}

    def fake_resolve(workspace_root, raw):
        captured["resolve_workspace"] = workspace_root
        return tmp_path, "session"

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", make_capturing_catalog(captured))
    monkeypatch.setattr("hydromodpy.calibration.report.resolve_session_in_workspace", fake_resolve)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.calibration.step_render_calibration_report",
        lambda **kwargs: Path("/tmp/report.html"),
    )

    hmp.report()
    assert Path(captured["resolve_workspace"]) == tmp_path


def test_report_propagates_session_lookup_error(monkeypatch, tmp_path: Path) -> None:
    """Errors from session resolution propagate to the caller."""

    def fake_resolve(workspace_root, raw):
        raise FileNotFoundError("no session")

    monkeypatch.setattr("hydromodpy.calibration.report.resolve_session_in_workspace", fake_resolve)

    with pytest.raises(FileNotFoundError, match="no session"):
        hmp.report("bad", workspace=tmp_path)
