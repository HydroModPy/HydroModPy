"""The markers that make a folder a project root or a workspace root.

``project.toml`` or the index database makes a project root. ``workspace.toml`` or a
``projects/`` folder makes a workspace root, which stands for the projects it holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.layout import (
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    catalog_path_for,
    is_project_root,
    is_workspace_root,
    project_roots_under,
)


def _make_project(parent: Path, name: str) -> Path:
    """Create a project root carrying ``project.toml``."""
    root = parent / name
    root.mkdir(parents=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _make_workspace(parent: Path, name: str = "ws") -> Path:
    """Create a workspace root carrying ``workspace.toml`` and ``projects/``."""
    root = parent / name
    (root / PROJECTS_DIRNAME).mkdir(parents=True)
    (root / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _symlink_dir(link: Path, target: Path) -> None:
    """Symlink ``link`` to ``target``, skipping where the OS forbids it."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable here: {exc}")


def test_project_marker(tmp_path: Path) -> None:
    root = _make_project(tmp_path, "naizin")
    assert is_project_root(root)
    assert not is_workspace_root(root)


def test_bare_index_database(tmp_path: Path) -> None:
    root = tmp_path / "naizin"
    catalog = catalog_path_for(root)
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b"")
    assert is_project_root(root)


def test_workspace_markers(tmp_path: Path) -> None:
    with_toml = tmp_path / "by_toml"
    with_toml.mkdir()
    (with_toml / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    with_dir = tmp_path / "by_dir"
    (with_dir / PROJECTS_DIRNAME).mkdir(parents=True)
    assert is_workspace_root(with_toml)
    assert is_workspace_root(with_dir)
    assert not is_project_root(with_toml)
    assert not is_project_root(with_dir)


def test_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "downloads"
    plain.mkdir()
    assert not is_project_root(plain)
    assert not is_workspace_root(plain)


def test_roots_of_a_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "downloads"
    plain.mkdir()
    assert project_roots_under(plain) == [plain.resolve()]


def test_roots_of_a_workspace(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    projects = workspace / PROJECTS_DIRNAME
    beta = _make_project(projects, "beta")
    alpha = _make_project(projects, "alpha")
    (projects / "notes").mkdir()
    assert project_roots_under(workspace) == [alpha.resolve(), beta.resolve()]


def test_roots_of_a_workspace_that_is_a_project(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    alpha = _make_project(workspace / PROJECTS_DIRNAME, "alpha")
    assert project_roots_under(workspace) == [workspace.resolve(), alpha.resolve()]


def test_roots_of_an_empty_workspace(tmp_path: Path) -> None:
    assert project_roots_under(_make_workspace(tmp_path)) == []


def test_roots_resolve_a_symlink(tmp_path: Path) -> None:
    """An expanded entry resolves, so a symlinked project is one root, not two.

    Registering the workspace and registering the project directly must yield
    the same string, otherwise the global index holds the same project twice.
    """
    target = _make_project(tmp_path, "elsewhere")
    workspace = _make_workspace(tmp_path)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "linked", target)
    assert project_roots_under(workspace) == [target.resolve()]
    assert project_roots_under(workspace / PROJECTS_DIRNAME / "linked") == [target.resolve()]


def test_roots_drop_duplicate_symlinks(tmp_path: Path) -> None:
    target = _make_project(tmp_path, "elsewhere")
    workspace = _make_workspace(tmp_path)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "one", target)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "two", target)
    assert project_roots_under(workspace) == [target.resolve()]
