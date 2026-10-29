"""``hmp site select <file>`` replaces the retired ``[workflow] mode = "site_selection"``.

It writes under the ``output_root`` the file declares and, with ``--into-catalog``,
declares the selected sites in the workspace catalog.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.commands import site
from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.config.hydromodpy_config import WorkflowConfig
from hydromodpy.data.sites.catalog import read_catalog
from hydromodpy.workflow.site_selection import selection_run as runner
from tests._helpers.site_selection_cases import selection_section, write_selection_toml

pytestmark = pytest.mark.fast
CATCHMENTS = {"mode": "delineated_catchments", "catchments_csv": "catchments.csv"}


def _hmp_site(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hmp")
    site.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["site", *argv])
    args._handler(args)


def _selection(tmp_path: Path, profile: str = "area_only", **tables) -> str:
    rows = "site_ok,350000,6800000,100\nsite_bad,360000,6810000,50"
    (tmp_path / "catchments.csv").write_text(f"site_id,x,y,area_km2\n{rows}\n", encoding="utf-8")
    tables.setdefault("input", CATCHMENTS)
    top = tables.pop("top", {})
    return str(write_selection_toml(tmp_path, selection_section(profile, **tables), **top))


def test_the_site_selection_workflow_mode_is_refused_with_its_replacement():
    with pytest.raises(ValueError, match="hmp site select"):
        WorkflowConfig.model_validate({"mode": "site_selection"})


def test_hmp_site_select_dry_run_writes_nothing_and_refuses_the_catalog(tmp_path, capsys):
    _hmp_site(["select", _selection(tmp_path), "--dry-run"])

    assert json.loads(capsys.readouterr().out)["selection_id"] == "demo"
    assert not (tmp_path / "out").exists()
    with pytest.raises(SystemExit) as stop:
        _hmp_site(["select", _selection(tmp_path), "--dry-run", "--into-catalog"])
    assert stop.value.code == 2


def test_hmp_site_select_writes_under_the_output_root_and_into_the_catalog(tmp_path, capsys):
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    (workspace / "projects").mkdir()

    _hmp_site(["select", _selection(tmp_path), "--into-catalog", "-w", str(workspace)])

    out = capsys.readouterr().out
    assert "selected=1 rejected=1" in out
    assert (tmp_path / "out" / "selected_sites.csv").is_file()
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()
    rows = read_catalog(workspace)
    assert [row.site for row in rows] == ["site_ok"]
    assert rows[0].x_outlet == pytest.approx(350000.0)
    assert "site_selection" in rows[0].tags
    assert "[written] 1 site(s)" in out


HYDROMETRY = {"hydrometry": {"sources": [{"source": "hubeau"}]}}
GENERATED = {"input": {"mode": "generated_candidates"}}


@pytest.mark.parametrize(
    ("profile", "tables", "name"),
    [
        ("custom", GENERATED | {"outlets": {"candidate_mode": "network_sampling"}},
         "build_generated_site_selection_from_toml"),
        ("area_only", {"input": {"mode": "dem_area_light"}},
         "build_dem_area_light_site_selection_from_toml"),
        ("gauged", {"input": {"mode": "hydrometry"}, "top": HYDROMETRY},
         "build_observed_site_selection_from_toml"),
    ],
)  # fmt: skip
def test_each_input_mode_runs_its_own_build(tmp_path, monkeypatch, capsys, profile, tables, name):
    calls: list = []

    def build(**kwargs):
        calls.append(kwargs)
        kwargs["progress_callback"]("half way")
        selection = SimpleNamespace(selected=["a"], rejected=[])
        return SimpleNamespace(candidates=["a", "b"], selection=selection, output_paths={})

    monkeypatch.setattr(runner, name, build)

    _hmp_site(["select", _selection(tmp_path, profile, **tables)])

    assert calls[0]["config_path"] == tmp_path / "selection.toml"
    assert calls[0]["data_root"] is None
    assert "candidates=2 selected=1 rejected=0" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("profile", "tables", "message"),
    [
        ("custom", GENERATED | {"outlets": {"candidate_mode": "station_outlets"}},
         "candidate_mode='network_sampling'"),
        ("area_only", {"input": {"mode": "hydrometry"}, "top": HYDROMETRY},
         "principle='observation_led'"),
        ("gauged", {"input": {"mode": "hydrometry"}}, "requires [hydrometry]"),
    ],
)  # fmt: skip
def test_an_input_mode_without_what_it_reads_is_refused(tmp_path, capsys, profile, tables, message):
    with pytest.raises(SystemExit) as stop:
        _hmp_site(["select", _selection(tmp_path, profile, **tables)])

    assert stop.value.code == EXIT_CONFIG
    assert message in capsys.readouterr().err
