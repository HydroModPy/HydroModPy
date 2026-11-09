"""Unit tests for the JSON sidecar Pydantic model and helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.provenance.sidecars import (
    DETERMINISTIC_FETCHED_AT_ENV,
    SIDECAR_SUFFIX,
    Sidecar,
    compute_sha256,
    load_sidecar,
    resolve_fetched_at,
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


def test_sidecar_accepts_omitted_fetched_at(tmp_path: Path):
    """``fetched_at`` is optional so custom-source sidecars stay deterministic."""
    target = tmp_path / "custom.csv"
    target.write_bytes(b"a,b\n1,2\n")
    sc = Sidecar(source="file", sha256="0" * 64)
    assert sc.fetched_at is None
    sidecar_path = write_sidecar(target, sc)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["fetched_at"] is None
    restored = load_sidecar(target)
    assert restored.fetched_at is None


def test_resolve_fetched_at_custom_source_is_none(monkeypatch: pytest.MonkeyPatch):
    """Custom local inputs always return ``None`` regardless of env var."""
    monkeypatch.delenv(DETERMINISTIC_FETCHED_AT_ENV, raising=False)
    assert resolve_fetched_at("custom") is None
    assert resolve_fetched_at("file") is None
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "1")
    assert resolve_fetched_at("custom") is None
    assert resolve_fetched_at("file") is None


def test_resolve_fetched_at_remote_source_returns_timestamp(monkeypatch: pytest.MonkeyPatch):
    """Real remote sources keep a UTC timestamp by default for audit."""
    monkeypatch.delenv(DETERMINISTIC_FETCHED_AT_ENV, raising=False)
    fetched = resolve_fetched_at("hubeau")
    assert isinstance(fetched, datetime)
    assert fetched.tzinfo is not None


def test_resolve_fetched_at_env_var_forces_none(monkeypatch: pytest.MonkeyPatch):
    """``HMP_DETERMINISTIC_FETCHED_AT=1`` forces ``None`` for every source."""
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "1")
    assert resolve_fetched_at("hubeau") is None
    assert resolve_fetched_at("ign") is None
    assert resolve_fetched_at("brgm") is None
    assert resolve_fetched_at("custom") is None


def test_resolve_fetched_at_env_var_other_values_keep_timestamp(
    monkeypatch: pytest.MonkeyPatch,
):
    """Only ``"1"`` activates the deterministic toggle, not ``"0"`` or empty."""
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "0")
    assert isinstance(resolve_fetched_at("hubeau"), datetime)
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "")
    assert isinstance(resolve_fetched_at("hubeau"), datetime)


def test_resolve_fetched_at_explicit_now_is_passed_through(
    monkeypatch: pytest.MonkeyPatch,
):
    """An explicit ``now`` argument lets callers pin the timestamp."""
    monkeypatch.delenv(DETERMINISTIC_FETCHED_AT_ENV, raising=False)
    fixed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert resolve_fetched_at("ign", now=fixed) == fixed
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "1")
    assert resolve_fetched_at("ign", now=fixed) is None


def test_sidecar_new_optional_fields():
    sc = Sidecar(
        source="url",
        origin="https://example.com/data.tif",
        sha256="a" * 64,
        etag='"etag123"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        product_version="v1.0",
        state="clean",
    )
    assert sc.origin == "https://example.com/data.tif"
    assert sc.etag == '"etag123"'
    assert sc.last_modified == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert sc.product_version == "v1.0"
    assert sc.state == "clean"


def test_sidecar_sha256_is_required():
    with pytest.raises(ValidationError):
        Sidecar(source="url", origin="https://example.com/data.tif")
    sc = Sidecar(source="url", sha256="0" * 64, origin="https://example.com/data.tif")
    assert sc.sha256 == "0" * 64


def test_load_sidecar_migrates_custom_to_file(tmp_path: Path):
    target = tmp_path / "legacy.csv"
    target.write_bytes(b"1,2,3")
    sidecar_path = target.with_name(target.name + SIDECAR_SUFFIX)
    sidecar_path.write_text(
        json.dumps(
            {
                "source": "custom",
                "sha256": "80b7524471f901b167de8bc7c9718d825eb8ca537b4c6205ec187997995759f3",
                "license": "LicenseRef-undetermined",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_sidecar(target)
    assert loaded.source == "file"
    assert loaded.sha256 == "80b7524471f901b167de8bc7c9718d825eb8ca537b4c6205ec187997995759f3"


def test_load_sidecar_from_v2_corpus_read_only():
    corpus_root = Path(__file__).resolve().parents[3] / "regression" / "frozen_documents" / "v2.0.0"
    piezo = (
        corpus_root / "current" / "island" / "data" / "piezometry" / "piezometry_custom_W1_D.csv"
    )
    if not piezo.is_file():
        pytest.skip("Corpus file not found")
    loaded = load_sidecar(piezo)
    assert loaded.source == "file"
    assert loaded.sha256 == "80b7524471f901b167de8bc7c9718d825eb8ca537b4c6205ec187997995759f3"

    dem = corpus_root / "current" / "island" / "data" / "dem" / "dem_ign.tif"
    if dem.is_file():
        loaded_dem = load_sidecar(dem)
        assert loaded_dem.source == "ign"
