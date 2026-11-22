"""The shipped example catalog, and the guarantee that it cannot drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.examples.generate import (
    build_catalog,
    example_folders,
    read_readme,
    repo_root,
)
from hydromodpy.project.examples.manifest import (
    SCHEMA_VERSION,
    catalog_path,
    find_entry,
    load_catalog,
    render_catalog,
)


def test_regenerating_the_manifest_reproduces_the_committed_bytes() -> None:
    """A drift between the repository and the shipped catalog fails here."""
    regenerated = render_catalog(build_catalog(repo_root()))
    assert regenerated == catalog_path().read_text(encoding="utf-8"), (
        "hydromodpy/project/examples/catalog.toml is stale. Run `python -m tools.dev examples manifest`."
    )


def test_load_rejects_another_schema_version(tmp_path: Path) -> None:
    other = tmp_path / "catalog.toml"
    other.write_text(f"schema_version = {SCHEMA_VERSION + 1}\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="schema_version"):
        load_catalog(other)


def test_unknown_id_names_the_ids_that_exist() -> None:
    with pytest.raises(FileNotFoundError, match="This build ships: 00, 01, .*, 04, "):
        find_entry("98", load_catalog())


def test_every_example_folder_of_the_checkout_is_in_the_catalog() -> None:
    """A new folder enters the catalog with no line of code."""
    folders = [folder.name for folder in example_folders(repo_root())]
    assert [entry.directory for entry in load_catalog()] == folders
    assert "04_streamflow_intermittence_in_transient" in folders


def _project(root: Path, name: str, readme: str | None, files: dict[str, str]) -> Path:
    folder = root / "examples" / "projects" / name
    folder.mkdir(parents=True)
    (folder / "project.toml").write_text('[simulation]\nname = "x"\n', encoding="utf-8")
    if readme is not None:
        (folder / "README.md").write_text(readme, encoding="utf-8")
    for relative, text in files.items():
        (folder / relative).write_text(text, encoding="utf-8")
    return folder


_README = """# Example 12: a small hillslope

A flat hillslope, 100 m long. Steady state.
A run takes about 5 s.

## The files

- `project.toml`: the model.
"""


def test_an_example_is_a_numbered_folder_with_a_readme(tmp_path: Path) -> None:
    _project(tmp_path, "12_small_hillslope", _README, {})
    _project(tmp_path, "99_tmp_scratch", None, {})
    _project(tmp_path, "notes", _README, {})
    (tmp_path / "examples" / "data").mkdir()

    assert [folder.name for folder in example_folders(tmp_path)] == ["12_small_hillslope"]
    (entry,) = build_catalog(tmp_path)
    assert (entry.id, entry.title, entry.runtime) == ("12", "A small hillslope", "about 5 s")
    assert entry.summary == "A flat hillslope, 100 m long. Steady state. A run takes about 5 s."
    assert entry.entry_config == "project.toml"
    assert [item.dest for item in entry.files] == [
        "projects/12_small_hillslope/README.md",
        "projects/12_small_hillslope/project.toml",
    ]


def test_a_readme_without_a_runtime_is_refused(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Example 12: x\n\nA hillslope.\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="A run takes about"):
        read_readme(readme)
    readme.write_text("No heading here.\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="heading"):
        read_readme(readme)


def test_two_examples_with_one_id_are_refused(tmp_path: Path) -> None:
    _project(tmp_path, "12_first", _README, {})
    _project(tmp_path, "12_second", _README, {})
    (tmp_path / "examples" / "data").mkdir()
    with pytest.raises(ConfigError, match="share the id 12"):
        build_catalog(tmp_path)


def test_two_examples_installing_one_file_differently_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--all`` writes every example in one workspace, so a shared place holds one file."""
    from hydromodpy.project.examples import generate

    data = tmp_path / "examples" / "data"
    for folder, text in (("dem", "first"), ("old/dem", "second")):
        (data / folder).mkdir(parents=True)
        (data / folder / "dem.tif").write_text(text, encoding="utf-8")
    _project(tmp_path, "12_first", _README, {})
    _project(tmp_path, "13_second", _README, {})

    def two_dems(project_dir: Path, data_root: Path, *, root: object) -> tuple:
        folder = "dem" if project_dir.name.startswith("12") else "old/dem"
        return [data_root / folder / "dem.tif"], ()

    monkeypatch.setattr(generate, "project_data", two_dems)
    with pytest.raises(ConfigError, match="both install data/dem/dem.tif"):
        build_catalog(tmp_path)
