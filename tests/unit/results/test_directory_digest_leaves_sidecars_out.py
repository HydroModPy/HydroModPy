"""The digest of a folder of inputs covers the data files, not their provenance sidecars.

A loader writes ``<file>.json`` beside a user file the first time it reads it.
The bytes the run reads are unchanged, so the digest the seal and the run
identity record must be too; a changed data file still changes it.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.storage.digests import sha256_directory


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "hydrometry"
    folder.mkdir()
    (folder / "hydrometry_custom_NANCON_D.csv").write_text("datetime,value\n2000-01-01,1\n")
    (folder / "README.md").write_text("Station files.\n")
    return folder


def test_a_sidecar_written_beside_a_file_leaves_the_digest_alone(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    before = sha256_directory(folder)

    (folder / "hydrometry_custom_NANCON_D.csv.json").write_text('{"source": "custom"}')

    assert sha256_directory(folder) == before


def test_a_changed_data_file_or_a_lone_json_changes_the_digest(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    before = sha256_directory(folder)

    (folder / "stations.json").write_text("{}")
    with_json = sha256_directory(folder)
    (folder / "hydrometry_custom_NANCON_D.csv").write_text("datetime,value\n2000-01-01,2\n")

    assert len({before, with_json, sha256_directory(folder)}) == 3
