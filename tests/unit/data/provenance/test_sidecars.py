"""The JSON sidecar of a fetched file: its model, its writing, and the scan of a data folder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.provenance import sidecars
from hydromodpy.data.provenance.sidecars import (
    DETERMINISTIC_FETCHED_AT_ENV,
    IGNORED_DIRECTORIES,
    IGNORED_SUFFIXES,
    SIDECAR_SUFFIX,
    CacheRow,
    Sidecar,
    compute_sha256,
    empty_path_for,
    load_sidecar,
    resolve_fetched_at,
    scan,
    sidecar_path_for,
    write_sidecar,
)
from hydromodpy.schema.changes import migrations_of, read


def _make_sidecar() -> Sidecar:
    return Sidecar(
        source="IGN BD ALTI 25m",
        fetched_at=datetime(2025, 8, 12, 10, 30, tzinfo=UTC),
        sha256="abc123" + "0" * 58,
        license="etalab-2.0",
        crs="EPSG:2154",
        bbox=(200000.0, 6700000.0, 350000.0, 6850000.0),
        notes="Crop manuel sur le Massif Armoricain",
        variable="dem",
        bytes=11,
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
        variable="dem",
        bytes=1,
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
    """``fetched_at`` is optional so local sidecars stay deterministic."""
    target = tmp_path / "custom.csv"
    target.write_bytes(b"a,b\n1,2\n")
    sc = Sidecar(source="file", sha256="0" * 64, variable="recharge", bytes=8)
    assert sc.fetched_at is None
    sidecar_path = write_sidecar(target, sc)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["fetched_at"] is None
    restored = load_sidecar(target)
    assert restored.fetched_at is None


def test_resolve_fetched_at_user_file_is_none(monkeypatch: pytest.MonkeyPatch):
    """A user file always returns ``None``, in any case and regardless of the env var.

    ``custom`` is a 2.0.0 spelling the register of changes turns into ``file``
    before any sidecar is written, so it never reaches this function.
    """
    monkeypatch.delenv(DETERMINISTIC_FETCHED_AT_ENV, raising=False)
    assert resolve_fetched_at("FILE") is None
    assert resolve_fetched_at("file") is None
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "1")
    assert resolve_fetched_at("FILE") is None
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


_HEAD = 'schema = "hydromodpy.changes.v1"\n'
_ROWS = {
    "a value renamed": (
        '[[migration]]\ndocument = "sidecar"\nkey = "state"\nold_value = "kept"\n'
        'new_value = "cached"\nsince = "2.1.0"\n',
        {"state": "kept"},
        {"state": "cached"},
    ),
    "a value that is not the old one": (
        '[[migration]]\ndocument = "sidecar"\nkey = "state"\nold_value = "kept"\n'
        'new_value = "cached"\nsince = "2.1.0"\n',
        {"state": "fresh"},
        {"state": "fresh"},
    ),
    "a key moved": (
        '[[migration]]\ndocument = "sidecar"\nold = "note"\nnew = "notes"\nsince = "2.1.0"\n',
        {"note": "by hand"},
        {"notes": "by hand"},
    ),
    "a key moved while the new one is written": (
        '[[migration]]\ndocument = "sidecar"\nold = "note"\nnew = "notes"\nsince = "2.1.0"\n',
        {"note": "old", "notes": "new"},
        {"note": "old", "notes": "new"},
    ),
    "a key retired that the row drops": (
        '[[migration]]\ndocument = "sidecar"\nold = "note"\ninstead = "nothing"\n'
        'sealed = "drop"\nsince = "2.1.0"\n',
        {"note": "by hand"},
        {},
    ),
    "a key retired that the row keeps": (
        '[[migration]]\ndocument = "sidecar"\nold = "note"\ninstead = "nothing"\nsince = "2.1.0"\n',
        {"note": "by hand"},
        {"note": "by hand"},
    ),
    "a row of another document": (
        '[[migration]]\ndocument = "fields"\nold = "note"\nnew = "notes"\nsince = "2.1.0"\n',
        {"note": "by hand"},
        {"note": "by hand"},
    ),
}


@pytest.mark.parametrize(("rows", "written", "read_as"), _ROWS.values(), ids=_ROWS.keys())
def test_a_sidecar_is_read_under_the_names_the_register_gives(
    rows: str, written: dict, read_as: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    register = read(_HEAD + rows)
    monkeypatch.setattr(
        sidecars, "migrations_of", lambda document: migrations_of(document, register)
    )
    target = tmp_path / "data.csv"
    target.write_bytes(b"1,2,3")
    base = {"source": "ign", "sha256": "0" * 64}
    sidecar_path_for(target).write_text(json.dumps({**base, **written}), encoding="utf-8")

    loaded = load_sidecar(target)

    dumped = {**loaded.model_dump(), **(loaded.__pydantic_extra__ or {})}
    assert {key: dumped[key] for key in read_as} == read_as
    assert all(key not in dumped for key in written if key not in read_as)


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


# -- the fields the data cache reads ---------------------------------------


def _chronicle_sidecar(**fields: object) -> Sidecar:
    base = {
        "source": "hubeau",
        "sha256": "1" * 64,
        "bytes": 12,
        "variable": "hydrometry",
        "station_id": "J1",
        "product": "QmnJ",
        "asked_window": ("2020-01-01T00:00:00", "2020-12-31T00:00:00"),
        "fetch_metadata": {"typename": "x"},
    }
    return Sidecar(**{**base, **fields})


def test_the_cache_fields_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "hydrometry_hubeau_J1_20200101_20201231_D.csv"
    target.write_bytes(b"datetime,v\n")
    write_sidecar(target, _chronicle_sidecar())

    loaded = load_sidecar(target)

    assert loaded.station_id == "J1"
    assert loaded.product == "QmnJ"
    assert loaded.asked_window == ("2020-01-01T00:00:00", "2020-12-31T00:00:00")
    assert loaded.bytes == 12
    assert loaded.fetch_metadata == {"typename": "x"}
    assert loaded.empty is False


_OMITTED = {
    "a station": ("station_id", {"station_id": None}),
    "a product": ("product", {"product": None}),
    "a window": ("asked_window", {"asked_window": None}),
    "provider keys": ("fetch_metadata", {"fetch_metadata": None}),
    "the empty mark": ("empty", {}),
}


@pytest.mark.parametrize(("key", "fields"), _OMITTED.values(), ids=_OMITTED.keys())
def test_an_unset_cache_field_is_not_written(key: str, fields: dict, tmp_path: Path) -> None:
    target = tmp_path / "x.csv"
    target.write_bytes(b"x")
    payload = json.loads(write_sidecar(target, _chronicle_sidecar(**fields)).read_text())
    assert key not in payload


def test_an_empty_sidecar_carries_no_digest_and_no_size(tmp_path: Path) -> None:
    target = empty_path_for(tmp_path, "hydrometry_hubeau_J1")
    sidecar = _chronicle_sidecar(empty=True, sha256=None, bytes=None)

    payload = json.loads(write_sidecar(target, sidecar).read_text())

    assert target.name == "hydrometry_hubeau_J1_empty.csv"
    assert not target.exists()
    assert payload["empty"] is True
    assert "sha256" not in payload
    assert "bytes" not in payload


_INVALID = {
    "an empty sidecar with a digest": {"empty": True, "bytes": None},
    "an empty sidecar with a size": {"empty": True, "sha256": None},
    "a file without its digest": {"sha256": None},
}


@pytest.mark.parametrize("fields", _INVALID.values(), ids=_INVALID.keys())
def test_the_digest_and_the_size_follow_the_empty_mark(fields: dict) -> None:
    with pytest.raises(ValidationError):
        _chronicle_sidecar(**fields)


def test_a_row_reads_its_window_and_speaks_plain_values(tmp_path: Path) -> None:
    row = CacheRow.of(tmp_path / "x.csv", _chronicle_sidecar())

    assert row.window() == (datetime(2020, 1, 1), datetime(2020, 12, 31))
    shown = row.to_dict()
    assert shown["station_id"] == "J1"
    assert {"id", "file_mtime", "is_custom"}.isdisjoint(shown)
    assert "license" in shown


# -- the scan and its name rules -------------------------------------------


def _put(path: Path, sidecar: Sidecar | None = None, *, with_file: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if with_file:
        path.write_bytes(b"x" * 12)
    if sidecar is not None:
        write_sidecar(path, sidecar)
    return path


_IGNORED = {
    "a lock": "hydrometry/.hydrometry_hubeau_J1.lock",
    "a write in progress": "hydrometry/.x.csv.json.123.part",
    "a hidden folder": ".hmp/hydrometry/x.csv",
    "a hidden file": "hydrometry/.hidden.csv",
    "the blobs folder": "blobs/geology/file/mine_clip_1.gpkg",
    "the sites folder": "sites/catalog.csv",
    "tiles extracted from an archive": "dem/extracted_ign/D029/tile.asc",
}


@pytest.mark.parametrize("relative", _IGNORED.values(), ids=_IGNORED.keys())
def test_a_name_rule_keeps_a_file_out_of_the_rows(relative: str, tmp_path: Path) -> None:
    data = tmp_path / "data"
    _put(data / relative, _chronicle_sidecar())

    report = scan(data)

    assert report.rows == ()
    assert report.lines() == []


def test_the_name_rules_say_why() -> None:
    assert set(IGNORED_DIRECTORIES) == {"blobs", "sites", "extracted_ign"}
    assert set(IGNORED_SUFFIXES) == {".lock", ".part"}
    assert all(reason for reason in [*IGNORED_DIRECTORIES.values(), *IGNORED_SUFFIXES.values()])


def test_a_blobs_folder_below_a_variable_is_scanned(tmp_path: Path) -> None:
    # blobs/ and sites/ are top-level names; only extracted_ign/ is ignored at any depth.
    data = tmp_path / "data"
    _put(data / "dem" / "blobs" / "x.tif", _chronicle_sidecar(variable="dem"))
    assert len(scan(data).rows) == 1


def test_a_manifest_is_no_sidecar(tmp_path: Path) -> None:
    data = tmp_path / "data"
    manifest = data / "dem" / "processed" / "dem_ign_25m_9d64382e.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"tiles": []}', encoding="utf-8")
    (data / "hydrography" / "provider_replay_manifest.json").parent.mkdir(parents=True)
    (data / "hydrography" / "provider_replay_manifest.json").write_text("{}", encoding="utf-8")

    report = scan(data)

    assert report.rows == ()
    assert report.unreadable == ()


def test_the_scan_sorts_every_sidecar(tmp_path: Path) -> None:
    data = tmp_path / "data"
    fetched = _put(data / "hydrometry" / "fetched.csv", _chronicle_sidecar())
    empty = _put(
        empty_path_for(data / "hydrometry", "hydrometry_hubeau_J2"),
        _chronicle_sidecar(station_id="J2", empty=True, sha256=None, bytes=None),
        with_file=False,
    )
    user = _put(data / "dem" / "mine.tif")
    sidecar_path_for(user).write_text(
        json.dumps({"source": "custom", "sha256": "0" * 64}), encoding="utf-8"
    )
    old = _put(data / "recharge" / "recharge_sim2_x.nc")
    sidecar_path_for(old).write_text(
        json.dumps({"source": "sim2", "sha256": "0" * 64}), encoding="utf-8"
    )
    orphan = _put(data / "geology" / "gone.gpkg", _chronicle_sidecar(variable="geology"))
    orphan.unlink()
    broken = _put(data / "etp" / "broken.nc")
    sidecar_path_for(broken).write_text("{not json", encoding="utf-8")

    report = scan(data)

    assert sorted(row.path for row in report.rows) == sorted([fetched, empty])
    assert report.user_files == (user,)
    assert report.without_variable == (sidecar_path_for(old),)
    assert report.orphans == (sidecar_path_for(orphan),)
    assert [path for path, _ in report.unreadable] == [sidecar_path_for(broken)]
    assert len(report.lines()) == 3
    assert "2.0.0" in report.lines()[0]


def test_a_missing_data_folder_has_no_rows(tmp_path: Path) -> None:
    assert scan(tmp_path / "nowhere").rows == ()


def test_a_prune_needs_the_digests_it_keeps(tmp_path: Path) -> None:
    """``project`` computes what a run or a lockfile cites; a prune never runs without it."""
    with pytest.raises(TypeError):
        sidecars.prune(tmp_path)  # type: ignore[call-arg]


def test_the_minimal_sidecar_of_a_user_file_loads_and_is_counted_apart(tmp_path: Path) -> None:
    """The sidecar a user writes to give a licence says only its source and licence."""
    data_path = tmp_path / "data" / "geology" / "mine.gpkg"
    data_path.parent.mkdir(parents=True)
    data_path.write_bytes(b"gpkg")
    sidecar_path_for(data_path).write_text(
        json.dumps({"source": "file", "license": "CC-BY-4.0"}), encoding="utf-8"
    )

    assert load_sidecar(data_path).license == "CC-BY-4.0"
    report = sidecars.scan(tmp_path / "data")
    assert report.rows == () and report.unreadable == ()
    assert report.user_files == (data_path.resolve(),)


def test_a_fetched_file_sidecar_still_needs_its_digest() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        Sidecar(source="ign", variable="dem")
