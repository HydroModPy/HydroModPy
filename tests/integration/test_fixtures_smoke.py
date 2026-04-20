"""Smoke test for the root-level tmp_workspace fixture."""

from pathlib import Path


def test_tmp_workspace_creates_layout(tmp_workspace: Path) -> None:
    assert tmp_workspace.exists()
    assert (tmp_workspace / "data").is_dir()
    assert (tmp_workspace / "projects").is_dir()
