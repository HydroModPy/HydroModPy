"""Round-trip test: the ``.hmp`` archive carries a RO-Crate at its root."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import zstandard as zstd

from hydromodpy.results.exporters.hmp_package import (
    HMP_FORMAT_VERSION,
    RO_CRATE_METADATA_NAME,
)
from tests.integration.exports.conftest import populate_simulation


def _extract(archive: Path) -> tarfile.TarFile:
    dctx = zstd.ZstdDecompressor()
    with open(archive, "rb") as fh:
        raw = dctx.decompress(fh.read())
    return tarfile.open(fileobj=io.BytesIO(raw), mode="r")


def test_hmp_archive_contains_ro_crate(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    out = tmp_path / "export.hmp"
    fair_catalog.export_package(sid, out)

    with _extract(out) as tar:
        names = tar.getnames()
        crate_name = f"{sid}/{RO_CRATE_METADATA_NAME}"
        assert crate_name in names

        crate_bytes = tar.extractfile(crate_name).read()
        crate = json.loads(crate_bytes)
        assert crate["@graph"]
        # ``manifest.json`` should still be present and bump format version.
        manifest_bytes = tar.extractfile(f"{sid}/manifest.json").read()
        manifest = json.loads(manifest_bytes)
        assert manifest["format_version"] == HMP_FORMAT_VERSION
        # Manifest must list the RO-Crate file too (so SHA-256 is captured).
        crate_entries = [e for e in manifest["files"] if e["path"] == RO_CRATE_METADATA_NAME]
        assert crate_entries, "manifest should list ro-crate-metadata.json"
        assert len(crate_entries[0]["sha256"]) == 64
