"""A run states the licence its inputs allow, and says once what it lacks.

The Zarr attributes and the Parquet footers used to carry a licence nobody
chose. They now carry the roll-up of the inputs' sidecars. The warning about a
missing identity or licence is said once per workspace, not once per run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.core.workspace.workspace_toml import load_workspace_toml, write_workspace_toml
from hydromodpy.results.catalog import Catalog, lifecycle
from hydromodpy.results.catalog.writes_helpers import run_licence
from hydromodpy.results.export.context import build_context
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, RUN_CONFIG_FILENAME
from hydromodpy.results.storage.parquet_io import read_kv_metadata


@pytest.fixture(autouse=True)
def _fresh_warning_memory() -> Iterator[None]:
    lifecycle._WARNED_WORKSPACES.clear()
    yield
    lifecycle._WARNED_WORKSPACES.clear()


def _input(root: Path, name: str, **sidecar: object) -> Path:
    path = root / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    if sidecar:
        path.with_name(path.name + ".json").write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def _register(catalog: Catalog, inputs: list[Path]) -> str:
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=f"run_{sid[:6]}",
        flow_regime="steady",
        n_cells=4,
        n_layers=1,
        bbox=[0.0, 0.0, 10.0, 10.0],
        crs="EPSG:2154",
        config={"flow": {"hk": 1e-5}},
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.register_tracked_files(
        sid,
        [
            TrackedFileEntry(
                role=path.stem,
                category="data",
                original_path=str(path),
                canonical_path=path,
                portable=True,
            )
            for path in inputs
        ],
    )
    return sid


def _seal(catalog: Catalog, sid: str) -> dict:
    (catalog.run_dir_for(sid) / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n")
    catalog.finalize(sid, status="completed")
    return dict(zarr.open_group(str(catalog.fields_path_for(sid)), mode="r").attrs)


def test_inputs_with_a_stated_licence_give_it_to_the_run(tmp_path: Path) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    geology = _input(tmp_path, "geology.gpkg", source="brgm_1m", license=None)
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem, geology])
        assert run_licence(catalog.backend, sid, tmp_path) == "etalab-2.0"
        attrs = _seal(catalog, sid)
        footer = read_kv_metadata(catalog.tables_dir_for(sid) / f"simulation{PARQUET_FILE_SUFFIX}")
    assert attrs["license"] == "etalab-2.0"
    assert footer["license"] == "etalab-2.0"


def test_one_unknown_input_leaves_the_run_undetermined(tmp_path: Path) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    recharge = _input(tmp_path, "recharge.csv", source="custom", license=UNDETERMINED_LICENSE)
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem, recharge])
        assert run_licence(catalog.backend, sid, tmp_path) == UNDETERMINED_LICENSE


def test_a_run_with_no_recorded_input_is_undetermined(tmp_path: Path) -> None:
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [])
        assert run_licence(catalog.backend, sid, tmp_path) == UNDETERMINED_LICENSE


def test_the_workspace_toml_identity_is_stamped(tmp_path: Path) -> None:
    write_workspace_toml(
        tmp_path, project_name="ws", creator_name="Ada Lovelace", creator_email="a@b.c"
    )
    toml_path = tmp_path / "workspace.toml"
    toml_path.write_text(
        toml_path.read_text().replace(
            'creator_institution = ""', 'creator_institution = "Univ Rennes"'
        )
    )
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    with Catalog(project) as catalog:
        attrs = _seal(catalog, _register(catalog, []))
    assert attrs["creator_name"] == "Ada Lovelace"
    assert attrs["creator_institution"] == "Univ Rennes"


def test_the_unix_account_is_never_the_creator(tmp_path: Path) -> None:
    with Catalog(tmp_path) as catalog:
        attrs = _seal(catalog, _register(catalog, []))
    assert "creator_name" not in attrs


def test_the_warning_is_said_once_per_workspace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    with Catalog(tmp_path) as catalog:
        for _ in range(3):
            _seal(catalog, _register(catalog, []))
    records = [r for r in caplog.records if "is sealed without" in r.getMessage()]
    warnings = [r for r in records if r.levelno == logging.WARNING]
    infos = [r for r in records if r.levelno == logging.INFO]
    assert len(warnings) == 1
    assert len(infos) == 2
    message = warnings[0].getMessage()
    assert "creator_name and creator_institution under [workspace]" in message
    assert "workspace.toml" in message
    assert "'license' key of the sidecar" in message


def test_a_determined_licence_drops_out_of_the_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    dem = _input(tmp_path, "dem.tif", source="osm", license="ODbL-1.0")
    with Catalog(tmp_path) as catalog:
        _seal(catalog, _register(catalog, [dem]))
    (warning,) = [r for r in caplog.records if "is sealed without" in r.getMessage()]
    assert "a determined license" not in warning.getMessage()
    assert "sidecar" not in warning.getMessage()


def test_another_workspace_is_told_too(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        with Catalog(root) as catalog:
            _seal(catalog, _register(catalog, []))
    warnings = [r for r in caplog.records if "is sealed without" in r.getMessage()]
    assert len(warnings) == 2


def _record(catalog: Catalog, sid: str, variable: str, source: str, digest: str | None) -> None:
    catalog.write_provenance(
        sid,
        variable=variable,
        source_ref=source,
        data=np.array([1.0]),
        source_type="data_manager",
        source_sha256=digest,
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_custom_record_no_tracked_file_holds_leaves_the_run_undetermined(
    tmp_path: Path,
) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    recharge = _input(tmp_path, "recharge.csv")
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem])
        _record(catalog, sid, "dem", "ign_geoplateforme_dem", _digest(dem))
        _record(catalog, sid, "recharge", "custom", _digest(recharge))
        assert run_licence(catalog.backend, sid, tmp_path) == UNDETERMINED_LICENSE


def test_a_custom_record_without_a_digest_leaves_the_run_undetermined(tmp_path: Path) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem])
        _record(catalog, sid, "recharge", "custom", None)
        assert run_licence(catalog.backend, sid, tmp_path) == UNDETERMINED_LICENSE


def test_a_custom_record_counts_through_the_tracked_file_that_holds_it(tmp_path: Path) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    recharge = _input(tmp_path, "recharge.csv", source="custom", license="etalab-2.0")
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem, recharge])
        _record(catalog, sid, "recharge", "custom", _digest(recharge))
        assert run_licence(catalog.backend, sid, tmp_path) == "etalab-2.0"


def test_a_custom_record_counts_through_a_tracked_directory(tmp_path: Path) -> None:
    folder = tmp_path / "data" / "recharge"
    folder.mkdir(parents=True)
    member = folder / "recharge.csv"
    member.write_bytes(b"1,2,3\n")
    member.with_name(member.name + ".json").write_text(
        json.dumps({"source": "custom", "license": "etalab-2.0", "sha256": _digest(member)}),
        encoding="utf-8",
    )
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [folder])
        _record(catalog, sid, "recharge", "custom", _digest(member))
        assert run_licence(catalog.backend, sid, tmp_path) == "etalab-2.0"
        _record(catalog, sid, "rain", "custom", "0" * 64)
        assert run_licence(catalog.backend, sid, tmp_path) == UNDETERMINED_LICENSE


def test_an_unreadable_index_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    class _Broken:
        def fetch_all(self, *_: object) -> list:
            raise RuntimeError("no such table")

    caplog.set_level(logging.DEBUG, logger="hydromodpy")
    assert run_licence(_Broken(), "sid") == UNDETERMINED_LICENSE
    assert any("no such table" in r.getMessage() for r in caplog.records)


def test_the_fair_export_context_carries_the_derived_licence(tmp_path: Path) -> None:
    dem = _input(tmp_path, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [dem])
        context = build_context(catalog, sid)
    assert context.license_url == "https://spdx.org/licenses/etalab-2.0"


def test_the_fair_export_context_never_defaults_to_cc_by(tmp_path: Path) -> None:
    with Catalog(tmp_path) as catalog:
        sid = _register(catalog, [])
        context = build_context(catalog, sid)
    assert context.license_url == UNDETERMINED_LICENSE


def test_a_creator_name_with_a_quote_still_loads(tmp_path: Path) -> None:
    write_workspace_toml(
        tmp_path, project_name="ws", creator_name='Ada "A." Lo\\ve', creator_email="a@b.c"
    )
    parsed = load_workspace_toml(tmp_path)
    assert parsed.workspace.creator_name == 'Ada "A." Lo\\ve'
