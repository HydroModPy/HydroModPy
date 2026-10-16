"""``hmp catalog import`` into a project without an index builds it, as ``hmp run`` does.

Without it the import said ``imported`` and ``hmp catalog ls`` then failed
with "No indexed project found" until a ``hmp catalog reindex``.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.export.publish import publish
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_run import RUN_NAME, seal_demo_run


def test_an_import_into_a_project_without_an_index_lists_the_run(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    run_dir, _ = seal_demo_run(lab)
    (run_dir / "config.toml").write_text('[site]\nname = "demo"\n', encoding="utf-8")
    copy = publish(run_dir, tmp_path / "published" / RUN_NAME, project_root=lab, with_=("results",))
    home = tmp_path / "home"
    home.mkdir()
    (home / "project.toml").write_text("", encoding="utf-8")

    imported = CliRunner().invoke(["catalog", "import", str(copy), "-w", str(home)])

    assert imported.exit_code == 0, imported.stderr
    assert catalog_path_for(home).is_file()
    listed = CliRunner().invoke(["catalog", "ls", "-w", str(home)])
    assert listed.exit_code == 0, listed.stderr
    assert RUN_NAME in listed.stdout
