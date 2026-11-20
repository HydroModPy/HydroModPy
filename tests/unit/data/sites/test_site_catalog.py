"""The site catalog of a workspace: one file, one reader and writer, two refusals.

``data/sites/catalog.csv`` holds ``SiteRow`` rows. A name is declared once; an
outlet closer than ``[sites] near_site_m`` of ``workspace.toml`` to a site of
another name is refused; ``--force`` replaces and accepts. ``hmp site add``,
``ls`` and ``show`` drive the same functions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from hydromodpy.cli.commands import site
from hydromodpy.cli.exit_codes import fail
from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.data.sites.catalog import (
    SITE_CATALOG_RELPATH,
    SiteConflictError,
    add_sites,
    declare_sites,
    nearest_site,
    read_catalog,
    write_catalog,
)

NANCON = SiteRow(
    site="nancon",
    label="Le Nancon a Lecousse",
    gauge="J001401001",
    uri="hubeau:J0014010",
    x_outlet=389285.91,
    y_outlet=6816518.75,
    crs="EPSG:2154",
    tags=("bretagne",),
)


def _workspace(tmp_path: Path, *, near_site_m: str | None = None) -> Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "projects").mkdir()
    if near_site_m is not None:
        (root / "workspace.toml").write_text(
            "\n".join(
                [
                    "[workspace]",
                    'name = "ws"',
                    'contact = "a@b.c"',
                    'created_at = "2026-10-15T00:00:00+00:00"',
                    "",
                    "[sites]",
                    f'near_site_m = "{near_site_m}"',
                ]
            ),
            encoding="utf-8",
        )
    return root


def _hmp_site(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hmp")
    site.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["site", *argv])
    try:
        args._handler(args)
    except Exception as exc:  # noqa: BLE001 - what the dispatcher of hmp does
        fail(exc)


@pytest.mark.fast
def test_a_bad_row_is_named_by_its_line(tmp_path):
    root = _workspace(tmp_path)
    path = root / SITE_CATALOG_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text(",".join(SITE_ROW_COLUMNS) + "\nnan-con,,,,,,,\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"catalog\.csv:2: column site"):
        read_catalog(root)


@pytest.mark.fast
def test_nearest_site_measures_in_metres_across_crs():
    lon, lat = -1.19785, 48.37462  # the Nancon outlet in WGS84, to about a meter
    found = nearest_site([NANCON], x=lon, y=lat, crs="EPSG:4326")

    assert found is not None
    row, distance = found
    assert row.site == "nancon"
    assert distance < 5.0


@pytest.mark.fast
def test_a_declared_name_is_refused_without_force_and_replaced_with_it():
    renamed = SiteRow(site="nancon", label="other label")

    with pytest.raises(SiteConflictError, match="site nancon: already declared"):
        add_sites([NANCON], [renamed], near_site_m=500.0)

    assert add_sites([NANCON], [renamed], near_site_m=500.0, force=True) == [renamed]


@pytest.mark.fast
def test_one_conflict_writes_nothing(tmp_path):
    root = _workspace(tmp_path)
    write_catalog(root, [NANCON])
    fresh = SiteRow(site="aber", x_outlet=150000.0, y_outlet=6850000.0, crs="EPSG:2154")
    twin = SiteRow(site="twin", x_outlet=389300.0, y_outlet=6816520.0, crs="EPSG:2154")

    with pytest.raises(SiteConflictError) as refused:
        declare_sites(root, [fresh, twin])

    assert refused.value.conflicts == (
        "site twin: outlet 14 m from site nancon, under near_site_m = 500 m",
    )
    assert read_catalog(root) == [NANCON]


@pytest.mark.fast
def test_near_site_m_is_read_from_workspace_toml(tmp_path):
    root = _workspace(tmp_path, near_site_m="10 m")
    write_catalog(root, [NANCON])
    twin = SiteRow(site="twin", x_outlet=389300.0, y_outlet=6816520.0, crs="EPSG:2154")

    assert [row.site for row in declare_sites(root, [twin])] == ["nancon", "twin"]


@pytest.mark.fast
def test_hmp_site_add_ls_and_show_drive_the_catalog(tmp_path, capsys):
    root = _workspace(tmp_path)

    _hmp_site(
        [
            "add",
            "nancon",
            "--outlet",
            "389285.91",
            "6816518.75",
            "--gauge",
            "J001401001",
            "--uri",
            "hubeau:J0014010",
            "--tag",
            "bretagne",
            "-w",
            str(root),
        ]
    )
    _hmp_site(["ls", "--format", "json", "-w", str(root)])
    listed = json.loads(capsys.readouterr().out.split("\n", 1)[1])["data"]
    _hmp_site(["show", "nancon", "--format", "json", "-w", str(root)])
    shown = json.loads(capsys.readouterr().out)["data"]

    assert [record["site"] for record in listed] == ["nancon"]
    assert shown["gauge"] == "J001401001"
    assert shown["crs"] == "EPSG:2154"
    assert shown["tags"] == "bretagne"


@pytest.mark.fast
def test_hmp_site_add_refuses_a_close_outlet_with_the_write_conflict_code(tmp_path, capsys):
    root = _workspace(tmp_path)
    write_catalog(root, [NANCON])

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["add", "twin", "--outlet", "389300", "6816520", "-w", str(root)])

    assert stop.value.code == 12
    assert "--force" in capsys.readouterr().err
    assert read_catalog(root) == [NANCON]


@pytest.mark.fast
def test_hmp_site_show_names_the_declared_sites_when_one_is_missing(tmp_path, capsys):
    root = _workspace(tmp_path)
    write_catalog(root, [NANCON])

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["show", "aber", "-w", str(root)])

    assert stop.value.code == 10
    assert "Declared: nancon" in capsys.readouterr().err


@pytest.mark.fast
def test_hmp_site_without_a_workspace_stops_instead_of_writing_a_default(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["ls"])

    assert stop.value.code == 10
    assert "Name one with -w" in capsys.readouterr().err
