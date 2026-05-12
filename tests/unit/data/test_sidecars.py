"""Unit tests for the JSON sidecar Pydantic model and helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.sidecars import (
    SIDECAR_SUFFIX,
    Sidecar,
    compute_sha256,
    load_sidecar,
    sidecar_path_for,
    write_sidecar,
)


def _make_sidecar() -> Sidecar:
    return Sidecar(
        source="IGN BD ALTI 25m",
        fetched_at=datetime(2025, 8, 12, 10, 30, tzinfo=UTC),
        sha256="abc123" + "0" * 58,
        license="etalab-2.0",
        crs="EPSG:2154",
        bbox=(200000.0, 6700000.0, 350000.0, 6850000.0),
        notes="Crop manuel sur le Massif Armoricain",
    )


def test_sidecar_model_is_frozen_and_rejects_extra_fields():
    sc = _make_sidecar()
    assert sc.model_config["frozen"] is True
    assert sc.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        Sidecar(
            source="x",
            fetched_at=datetime.now(UTC),
            sha256="0" * 64,
            unknown_field="boom",
        )


def test_write_sidecar_creates_json_next_to_file(tmp_path: Path):
    target = tmp_path / "data" / "dem" / "raw" / "DEM.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake-raster")

    sc = _make_sidecar()
    sidecar_path = write_sidecar(target, sc)

    assert sidecar_path == target.with_name(target.name + SIDECAR_SUFFIX)
    assert sidecar_path.is_file()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["source"] == "IGN BD ALTI 25m"
    assert payload["license"] == "etalab-2.0"


def test_load_sidecar_round_trip(tmp_path: Path):
    target = tmp_path / "data" / "dem" / "raw" / "DEM.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"raster")

    original = _make_sidecar()
    write_sidecar(target, original)

    restored = load_sidecar(target)
    assert restored == original


def test_compute_sha256_matches_known_digest(tmp_path: Path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"hello")
    digest = compute_sha256(target)
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_sidecar_path_for_uses_full_filename_suffix(tmp_path: Path):
    target = tmp_path / "DEM.tif"
    assert sidecar_path_for(target).name == "DEM.tif.json"
    target_zip = tmp_path / "vectors.gpkg.zip"
    assert sidecar_path_for(target_zip).name == "vectors.gpkg.zip.json"


def test_sidecar_bbox_tuple_round_trip(tmp_path: Path):
    target = tmp_path / "raster.tif"
    target.write_bytes(b"r")
    sc = Sidecar(
        source="X",
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
        sha256="0" * 64,
        bbox=(0.0, 1.0, 2.0, 3.0),
    )
    write_sidecar(target, sc)
    loaded = load_sidecar(target)
    assert loaded.bbox == (0.0, 1.0, 2.0, 3.0)


def test_load_sidecar_missing_file_raises(tmp_path: Path):
    target = tmp_path / "no_sidecar.tif"
    target.write_bytes(b"r")
    with pytest.raises(FileNotFoundError):
        load_sidecar(target)
