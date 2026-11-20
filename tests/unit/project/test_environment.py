""":class:`Environment` at the open of a project, and no other moment.

``default()`` answers the machine: the credentials at their default place,
the default bounds. ``check`` is the one moment the file is read, so a
refused file stops the verb before its first step instead of stopping a
delivery after hours of solve. An absent file at the default place is an
answer (no identifiers), an absent file the caller named is a refusal.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, exit_code_for
from hydromodpy.core.exceptions import BoundsError, CredentialsError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project.environment import Environment

GOOD = """
[[host]]
prefix = "ftps://depot.example.org/hydromodpy/"
user = "bastien"
password = "s3cr3t-hunter2"
"""


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The state root of the machine, here: a folder next to the project."""
    home = tmp_path / "state"
    monkeypatch.setenv("HMP_STATE_HOME", str(home))
    return home


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    project = tmp_path / "projects" / "one"
    workspace = tmp_path / "workspace"
    project.mkdir(parents=True)
    workspace.mkdir(parents=True)
    return {"project": project, "workspace": workspace}


def _write(path: Path, body: str = GOOD, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(mode)
    return path


def test_check_accepts_named_roots(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    environment = Environment(bounds=Bounds(allowed_roots=(tmp_path,)))
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_check_refuses_outside_roots(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    elsewhere = tmp_path / "other-project"
    elsewhere.mkdir()
    environment = Environment(bounds=Bounds(allowed_roots=(roots["workspace"],)))
    with pytest.raises(BoundsError) as raised:
        environment.check(project_root=elsewhere, workspace_root=roots["workspace"])
    message = str(raised.value)
    assert "opening the project" in message
    assert str(elsewhere) in message


def test_named_absent_file_refused(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    missing = tmp_path / "elsewhere.toml"
    environment = Environment(credentials=missing)
    with pytest.raises(CredentialsError) as raised:
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])
    message = str(raised.value)
    assert "does not exist" in message and "elsewhere.toml" in message
    assert not isinstance(raised.value, FileNotFoundError)
    assert exit_code_for(raised.value) == EXIT_CONFIG == 14


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_credentials_outside_project_only(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    inside = _write(roots["project"] / "credentials.toml")
    environment = Environment(credentials=inside)
    with pytest.raises(CredentialsError, match="outside every project and workspace"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])

    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_loose_mode_refused(tmp_path: Path, state_home: Path, roots: dict[str, Path]) -> None:
    loose = _write(tmp_path / "loose.toml", mode=0o644)
    environment = Environment(credentials=loose)
    with pytest.raises(CredentialsError, match="chmod 600"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_repr_hides_secret(tmp_path: Path, state_home: Path, roots: dict[str, Path]) -> None:
    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    rendered = repr(environment)
    assert "credentials-depot.toml" in rendered
    assert "s3cr3t-hunter2" not in rendered


def test_no_file_reads_nothing(
    roots: dict[str, Path],
) -> None:
    environment = Environment(credentials=None)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def _chain(tmp_path: Path, base: str) -> Path:
    """Write a project file whose ``base_config`` is the TOML value *base*, and a file outside."""
    (tmp_path / "other").mkdir(exist_ok=True)
    (tmp_path / "other" / "secret.toml").write_text('[simulation]\nname = "other"\n')
    (tmp_path / "project" / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "project" / "common.toml").write_text("[simulation]\n")
    file = tmp_path / "project" / "inputs" / "case.toml"
    file.write_text(f"base_config = {base.format(tmp=tmp_path.as_posix())}\n")
    return file


CHAINS = {
    "a base that climbs": ("'../../other/secret.toml'", False),
    "an absolute base": ("'{tmp}/other/secret.toml'", False),
    "a base list with one outside": ("['../common.toml', '../../other/secret.toml']", False),
    "a base inside": ("'../common.toml'", True),
}


@pytest.mark.parametrize(("base", "kept"), CHAINS.values(), ids=list(CHAINS))
def test_require_chain_bounds_each_base(tmp_path: Path, base: str, kept: bool) -> None:
    file = _chain(tmp_path, base)
    environment = Environment(bounds=Bounds(allowed_roots=(tmp_path / "project",)))
    if kept:
        environment.require_chain(file)
        return
    with pytest.raises(BoundsError, match="reading a base_config file"):
        environment.require_chain(file)


def test_require_chain_without_roots_checks_nothing(tmp_path: Path) -> None:
    Environment().require_chain(_chain(tmp_path, "'../../other/secret.toml'"))


def _basin(tmp_path: Path) -> tuple[Path, dict]:
    """Write the scenario basin under ``tmp_path/project`` and return its folder and document."""
    import tomllib

    from tests.scenarios.factory import basin_files

    project = tmp_path / "project"
    for relative, text in basin_files(True).items():
        (project / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / relative).write_text(text)
    return project, tomllib.loads((project / "project.toml").read_text())


def _with_mask(document: dict, mask: str) -> dict:
    document["data"]["recharge"]["sources"][0]["mask_path"] = mask
    return document


MASKS = {
    "a file of another project": ("{tmp}/other/mask.geojson", False),
    "a missing file outside": ("{tmp}/nowhere/mask.geojson", False),
    "a path that climbs": ("../other/mask.geojson", False),
    "a system file": ("/etc/passwd", False),
    "a file of the project": ("inputs/mask.geojson", True),
}


@pytest.mark.parametrize(("mask", "kept"), MASKS.values(), ids=MASKS.keys())
def test_a_bounded_project_refuses_a_file_outside_its_roots(
    tmp_path: Path, mask: str, kept: bool
) -> None:
    import hydromodpy as hmp

    project, document = _basin(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "mask.geojson").write_text("{}")
    _with_mask(document, mask.format(tmp=tmp_path.as_posix()))
    environment = Environment(bounds=Bounds(allowed_roots=(project,)))
    if kept:
        hmp.Project(document, base=project, environment=environment)
        return
    # One sentence whether the file exists or not, so nothing can be probed.
    with pytest.raises(BoundsError, match="data.recharge.sources.0.mask_path names"):
        hmp.Project(document, base=project, environment=environment)


def test_a_change_of_the_run_is_bounded_too(tmp_path: Path) -> None:
    import hydromodpy as hmp

    project, document = _basin(tmp_path)
    environment = Environment(bounds=Bounds(allowed_roots=(project,)))
    opened = hmp.Project(document, base=project, environment=environment)
    sources = _with_mask(document, "/etc/passwd")["data"]["recharge"]["sources"]
    with pytest.raises(BoundsError, match="mask_path names"):
        opened.simulate(set={"data.recharge.sources": sources}, dry_run=True)


RESTARTS = {
    "a run of the project": ("baseline", True),
    "a store outside": ("{tmp}/other/runs/x/fields.zarr", False),
    "a table form that climbs": ({"path": "../other/runs/x"}, False),
}


@pytest.mark.parametrize(("reference", "kept"), RESTARTS.values(), ids=RESTARTS.keys())
def test_restart_from_is_bounded(tmp_path: Path, reference: Any, kept: bool) -> None:
    from types import SimpleNamespace

    from hydromodpy.model.flow_config import RestartReference

    if isinstance(reference, dict):
        reference = RestartReference(**reference)
    else:
        reference = reference.format(tmp=tmp_path.as_posix())
    project = tmp_path / "project"
    project.mkdir()
    cfg = SimpleNamespace(flow=SimpleNamespace(restart_from=reference))
    environment = Environment(bounds=Bounds(allowed_roots=(project,)))
    if kept:
        environment.require_document(cfg, project_root=project)
        return
    with pytest.raises(BoundsError, match="restart_from names"):
        environment.require_document(cfg, project_root=project)


def test_require_document_leaves_the_workspace_and_open_calls(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    document = {"workspace": {"root": tmp_path / "space"}, "mesh": {"path": Path("/etc/passwd")}}
    Environment().require_document(document, project_root=project)
    with pytest.raises(BoundsError, match="mesh.path names"):
        Environment(bounds=Bounds(allowed_roots=(project,))).require_document(
            document, project_root=project
        )
    del document["mesh"]
    Environment(bounds=Bounds(allowed_roots=(project,))).require_document(
        document, project_root=project
    )
