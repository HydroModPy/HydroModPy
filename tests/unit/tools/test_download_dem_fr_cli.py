from __future__ import annotations

import pytest

from hydromodpy.data.variables.dem.apis.geoplateforme_download import DownloadFile
from tools.download_dem_fr import download_dem_fr


@pytest.mark.fast
def test_download_dem_fr_default_output_dir_uses_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path / "workspace"))

    assert download_dem_fr.default_output_dir() == (
        tmp_path / "workspace" / "data" / "dem" / "raw_ign"
    )


@pytest.mark.fast
def test_download_dem_fr_dry_run_lists_files_and_md5(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_discover(**kwargs):
        captured.update(kwargs)
        return [
            DownloadFile(
                "BDALTI",
                "sub",
                "archive.7z",
                "https://example.test/archive.7z",
                checksum="abc123",
                department="D029",
            )
        ]

    monkeypatch.setattr(download_dem_fr, "discover_ign_dem_files", fake_discover)

    code = download_dem_fr.main(
        [
            "--departements",
            "29",
            "--dataset",
            "bd-alti",
            "--resolution",
            "25",
            "--format",
            "ASC",
            "--dry-run",
            "--include-md5",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert captured["departments"] == ["D029"]
    assert captured["dataset"] == "bd-alti"
    assert captured["resolution_m"] == 25.0
    assert "Found 1 file(s)." in output
    assert "D029 archive.7z https://example.test/archive.7z md5=abc123" in output


@pytest.mark.fast
def test_download_dem_fr_regions_are_resolved_before_discovery(monkeypatch):
    captured: dict[str, object] = {}

    def fake_find_departments(regions):
        assert list(regions) == ["Bretagne"]
        return ["022", "029"]

    def fake_discover(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "hydromodpy.data.common.administrative.france.find_departments_in_regions",
        fake_find_departments,
    )
    monkeypatch.setattr(download_dem_fr, "discover_ign_dem_files", fake_discover)

    code = download_dem_fr.main(
        [
            "--regions",
            "Bretagne",
            "--dataset",
            "bd-alti",
            "--resolution",
            "25",
            "--dry-run",
        ]
    )

    assert code == 0
    assert captured["departments"] == ["D022", "D029"]


@pytest.mark.fast
def test_download_dem_fr_download_path_uses_cli_options(monkeypatch, tmp_path, capsys):
    captured: dict[str, object] = {}
    output_path = tmp_path / "raw" / "bd-alti" / "25m" / "D029" / "archive.7z"

    def fake_download(**kwargs):
        captured.update(kwargs)
        return [output_path]

    monkeypatch.setattr(download_dem_fr, "download_ign_dem_departments", fake_download)

    code = download_dem_fr.main(
        [
            "--departements",
            "29",
            "--dataset",
            "bd-alti",
            "--resolution",
            "25",
            "--format",
            "ASC",
            "--output-dir",
            str(tmp_path / "raw"),
            "--max-files",
            "1",
            "--timeout",
            "5",
            "--rate-limit",
            "2",
            "--overwrite",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert captured["output_dir"] == tmp_path / "raw"
    assert captured["departments"] == ["D029"]
    assert captured["dataset"] == "bd-alti"
    assert captured["resolution_m"] == 25.0
    assert captured["file_format"] == "ASC"
    assert captured["dry_run"] is False
    assert captured["max_files"] == 1
    assert captured["timeout"] == 5.0
    assert captured["requests_per_second"] == 2.0
    assert captured["overwrite"] is True
    assert "Downloaded or reused 1 file(s)." in output
    assert str(output_path) in output


@pytest.mark.fast
def test_download_dem_fr_requires_department_or_region():
    with pytest.raises(SystemExit):
        download_dem_fr.main(["--dataset", "bd-alti"])
