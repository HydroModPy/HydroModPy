"""Every file a run writes lands in the directory of that run, and says whose it is.

``hmp run step1_minimal.toml`` of example 04 renders figures and writes three
``[[export]]`` blocks. Afterwards, nothing new exists in the project outside
``runs/<run>/`` but the reconstructible ``.hmp/`` and the cache pin
``hydromodpy.lock``; no ``share/``, ``outputs/``, ``figures/`` or ``reports/``
appears anywhere. The figures and the exports each have their ledger, every
file of the ledger exists, and every file carries the identity block of the
run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from tests.e2e._step1_minimal import RUN_NAME, disposable_env, files_under, hmp, make_workspace

pytestmark = pytest.mark.e2e

FORBIDDEN = {"share", "outputs", "figures", "exports", "reports", "simulations", ".solver_scratch"}
ALLOWED_AT_PROJECT_ROOT = {"runs", ".hmp", "hydromodpy.lock"}


@pytest.fixture(scope="module")
def solved(tmp_path_factory) -> tuple[Path, Path, set[Path]]:
    root = tmp_path_factory.mktemp("writers")
    project = make_workspace(root / "workspace")
    before = files_under(project)
    env = disposable_env(root / "home")
    result = hmp("run", "step1_minimal.toml", cwd=project, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    return project, project / "runs" / RUN_NAME, files_under(project) - before


def test_nothing_new_lands_outside_the_run_directory(solved) -> None:
    project, run_dir, new = solved
    outside = sorted(
        path.as_posix()
        for path in new
        if path.parts[0] not in ALLOWED_AT_PROJECT_ROOT
        or (path.parts[0] == "runs" and path.parts[1] != RUN_NAME)
    )
    assert outside == []
    assert run_dir.is_dir()


def test_no_project_wide_output_folder_exists(solved) -> None:
    project, _run_dir, _new = solved
    found = sorted(
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_dir() and path.name in FORBIDDEN and path.parent in (project, project / "runs")
    )
    assert found == []


def test_the_figures_are_recorded_and_carry_the_identity_of_the_run(solved) -> None:
    _project, run_dir, _new = solved
    figures = run_dir / "figures"
    ledger = Ledger.read(figures)
    pngs = sorted(path.name for path in figures.glob("*.png"))
    assert pngs
    assert sorted(entry.file for entry in ledger.entries) == pngs
    for entry in ledger.entries:
        identity = read_identity_from(figures / entry.file)
        assert identity is not None, entry.file
        assert identity.case_id == RUN_NAME
        assert identity == entry.identity


def test_the_exports_are_recorded_and_carry_the_identity_of_the_run(solved) -> None:
    _project, run_dir, _new = solved
    exports = run_dir / "exports"
    ledger = Ledger.read(exports)
    written = sorted(
        path.relative_to(exports).as_posix()
        for path in exports.rglob("*")
        if path.is_file()
        and path.name != "index.json"
        and not path.name.endswith(".meta.json")
        and path.suffix in {".gpkg", ".tif", ".csv", ".nc", ".shp", ".vtu"}
    )
    assert written
    assert sorted(entry.file for entry in ledger.entries) == written
    for entry in ledger.entries:
        identity = read_identity_from(exports / entry.file)
        assert identity is not None, entry.file
        assert identity.sim_id == entry.identity.sim_id
        assert identity.case_id == RUN_NAME
