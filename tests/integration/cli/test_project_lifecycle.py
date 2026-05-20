"""End-to-end: workspace init -> project new -> project list -> project show -> delete.

Drives the full project lifecycle through ``hmp`` family verbs to make sure
the dispatch wiring and helpers handle the canonical newcomer path.
"""

from __future__ import annotations

from pathlib import Path

from tests._helpers.cli_runner import CliRunner


def test_project_lifecycle_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runner = CliRunner()

    init = runner.invoke(["hmp", "workspace", "init", "--path", str(workspace)])
    assert init.ok, init.stderr
    assert (workspace / "projects").is_dir()
    assert (workspace / "data").is_dir()
    assert "Workspace:" in init.stdout

    new = runner.invoke(["hmp", "project", "new", "demo", "--workspace", str(workspace)])
    assert new.ok, new.stderr
    project_dir = workspace / "projects" / "demo"
    assert project_dir.is_dir()
    assert (project_dir / "hydromodpy.toml").is_file()

    listed = runner.invoke(["hmp", "project", "list", "--workspace", str(workspace)])
    assert listed.ok, listed.stderr
    assert "demo" in listed.stdout

    shown = runner.invoke(["hmp", "project", "show", "demo", "--workspace", str(workspace)])
    assert shown.ok, shown.stderr
    assert "demo" in shown.stdout
    assert "hydromodpy.toml" in shown.stdout

    deleted = runner.invoke(
        ["hmp", "project", "delete", "demo", "--workspace", str(workspace), "--force"]
    )
    assert deleted.ok, deleted.stderr
    assert not project_dir.exists()


def test_workspace_clean_dry_run_lists_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runner = CliRunner()
    runner.invoke(["hmp", "workspace", "init", "--path", str(workspace)])
    (workspace / "exports").mkdir(exist_ok=True)
    (workspace / "exports" / "stale.txt").write_text("artifact")

    result = runner.invoke(
        [
            "hmp",
            "workspace",
            "clean",
            "--workspace",
            str(workspace),
            "--exports",
            "--dry-run",
        ]
    )
    assert result.ok, result.stderr
    assert "Dry-run" in result.stdout
    assert (workspace / "exports").is_dir()
