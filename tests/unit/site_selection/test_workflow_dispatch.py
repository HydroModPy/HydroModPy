"""``hmp site select`` runs a selection file; the workflow mode is gone.

The ``[workflow] mode = "site_selection"`` route of ``hmp run`` is retired: a
site selection is run by ``hmp site select <file>``, which writes under the
``output_root`` the file declares and, with ``--into-catalog``, declares the
selected sites in the workspace catalog.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from hydromodpy.cli.commands import site
from hydromodpy.config.hydromodpy_config import WorkflowConfig
from hydromodpy.data.sites.catalog import read_catalog


def _hmp_site(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hmp")
    site.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["site", *argv])
    args._handler(args)


def _selection(tmp_path: Path, mode: str = "delineated_catchments") -> Path:
    (tmp_path / "catchments.csv").write_text(
        "site_id,x,y,area_km2\nsite_ok,350000,6800000,100\nsite_bad,360000,6810000,50\n",
        encoding="utf-8",
    )
    path = tmp_path / "selection.toml"
    path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                f'mode = "{mode}"',
                'catchments_csv = "catchments.csv"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "projects").mkdir()
    return root


@pytest.mark.fast
def test_the_site_selection_workflow_mode_is_refused_with_its_replacement(tmp_path):
    with pytest.raises(ValueError, match="hmp site select"):
        WorkflowConfig.model_validate({"mode": "site_selection"})


@pytest.mark.fast
def test_hmp_site_select_writes_under_the_declared_output_root(tmp_path, capsys):
    config = _selection(tmp_path)

    _hmp_site(["select", str(config)])

    out = capsys.readouterr().out
    assert "selected=1 rejected=1" in out
    assert (tmp_path / "out" / "selected_sites.csv").is_file()
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()


@pytest.mark.fast
def test_hmp_site_select_dry_run_writes_nothing(tmp_path, capsys):
    config = _selection(tmp_path)

    _hmp_site(["select", str(config), "--dry-run"])

    plan = json.loads(capsys.readouterr().out)
    assert plan["selection_id"] == "demo"
    assert not (tmp_path / "out").exists()


@pytest.mark.fast
def test_hmp_site_select_into_catalog_declares_the_selected_sites(tmp_path, capsys):
    config = _selection(tmp_path)
    workspace = _workspace(tmp_path)

    _hmp_site(["select", str(config), "--into-catalog", "-w", str(workspace)])

    rows = read_catalog(workspace)
    assert [row.site for row in rows] == ["site_ok"]
    assert rows[0].x_outlet == pytest.approx(350000.0)
    assert "site_selection" in rows[0].tags
    assert "[written] 1 site(s)" in capsys.readouterr().out


@pytest.mark.fast
def test_into_catalog_and_dry_run_are_refused_together(tmp_path):
    config = _selection(tmp_path)

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["select", str(config), "--dry-run", "--into-catalog"])

    assert stop.value.code == 2
