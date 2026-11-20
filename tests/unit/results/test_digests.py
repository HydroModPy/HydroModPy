"""The digest of a folder of inputs covers the data files, not their provenance sidecars.

A loader writes ``<file>.json`` beside a user file the first time it reads it.
The bytes the run reads are unchanged, so the digest the seal and the run
identity record must be too.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.storage.digests import sha256_directory


def test_sidecar_leaves_the_digest_alone(tmp_path: Path) -> None:
    folder = tmp_path / "hydrometry"
    folder.mkdir()
    (folder / "hydrometry_custom_NANCON_D.csv").write_text("datetime,value\n2000-01-01,1\n")
    (folder / "README.md").write_text("Station files.\n")
    before = sha256_directory(folder)

    (folder / "hydrometry_custom_NANCON_D.csv.json").write_text('{"source": "file"}')

    assert sha256_directory(folder) == before
