"""The data layer refuses a request, a file or a call outside its bounds before it reaches a source.

Each table is a family of refusals. A row gives the input that is wrong, the class that
refuses it and a fragment of the sentence that says what to change.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import (
    BoundsError,
    CredentialsError,
    DataCacheError,
    DataCapabilityError,
    DataContractViolation,
    DataProductError,
    DataRequestError,
    FrozenDataError,
    SchemaVersionMismatchError,
)
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.provenance.lockfile import (
    LockedInputs,
    project_lockfile_path,
    read_locked_inputs,
    read_lockfile_inputs,
    reject_frozen_download,
    reject_frozen_user_file,
    user_file_input,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    Sidecar,
    empty_path_for,
    load_sidecar,
    write_sidecar,
)
from hydromodpy.data.source.port import (
    Extent,
    FetchRequest,
    FetchResult,
    Period,
    Selector,
    require_declared_variables,
    require_selectors,
)
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.hydrography.custom import load_file
from hydromodpy.project.credentials import load_credentials

GEO = "api.geosas.fr"
GEOPF = "data.geopf.fr"
NOWHERE = "EPSG:4326"
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 3, 31))
BOX = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs=NOWHERE)

# --- an extent and a period ----------------------------------------------------------------

EXTENTS = [
    pytest.param({"crs": "  "}, "carries the CRS", id="no CRS"),
    pytest.param({"xmin": 1.0, "xmax": 0.0}, "empty or inverted", id="x inverted"),
    pytest.param({"ymin": 1.0, "ymax": 0.0}, "empty or inverted", id="y inverted"),
    pytest.param({"xmin": 0.0, "xmax": 0.0}, "empty or inverted", id="x degenerate"),
    pytest.param({"xmin": "0"}, "not a number", id="a string"),
    pytest.param({"xmin": False}, "boolean", id="a boolean"),
    pytest.param({"xmin": float("nan")}, "not finite", id="not finite"),
]


@pytest.mark.parametrize(("changes", "said"), EXTENTS)
def test_an_extent_that_means_nothing_is_refused(changes: dict[str, Any], said: str) -> None:
    fields: dict[str, Any] = {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs": NOWHERE}

    with pytest.raises(DataRequestError, match=said):
        Extent(**{**fields, **changes})


def test_an_extent_with_no_image_in_the_target_crs_is_refused() -> None:
    far_side = Extent(xmin=100.0, ymin=-40.0, xmax=140.0, ymax=-20.0, crs=NOWHERE)

    with pytest.raises(DataRequestError, match="no image in"):
        far_side.to_crs("+proj=ortho +lat_0=48 +lon_0=-2 +datum=WGS84")


@pytest.mark.parametrize(
    ("start", "end", "said"),
    [
        pytest.param(
            datetime(2020, 2, 1), datetime(2020, 1, 1), "ends", id="ends before it starts"
        ),
        pytest.param(
            datetime(2020, 1, 1), datetime(2020, 2, 1, tzinfo=UTC), "aware", id="aware and naive"
        ),
    ],
)
def test_a_period_that_means_nothing_is_refused(start: datetime, end: datetime, said: str) -> None:
    with pytest.raises(DataRequestError, match=said):
        Period(start=start, end=end)


# --- a request and the selectors of a source -----------------------------------------------------


class _Source:
    """The minimum a source that selects by extent is asked for."""

    source_id = "selecting-double"
    section = "double"
    payload_kind = "features"
    extent_crs = NOWHERE
    selectors: tuple[Selector, ...] = ("extent",)
    period_need = "refused"
    writes_out_dir = False
    hosts: tuple[str, ...] = ()
    variables: tuple[str, ...] = ("double",)


class _TwoSelectors(_Source):
    selectors: tuple[Selector, ...] = ("extent", "station_ids")


REQUESTS = [
    pytest.param(
        lambda out: require_selectors(_Source(), FetchRequest(out_dir=out)),
        DataRequestError,
        "selects nothing",
        id="a request that selects nothing",
    ),
    pytest.param(
        lambda out: require_selectors(_Source(), FetchRequest(out_dir=out, station_ids=("BSS1",))),
        DataCapabilityError,
        "does not select by",
        id="a selector the source does not declare",
    ),
    pytest.param(
        lambda out: require_selectors(
            _TwoSelectors(), FetchRequest(out_dir=out, extent=BOX, station_ids=("BSS1",))
        ),
        DataCapabilityError,
        "at once",
        id="two selectors at once",
    ),
    pytest.param(
        lambda out: FetchRequest(out_dir=out, station_ids="BSS1"),
        DataRequestError,
        "single string",
        id="one string of station ids",
    ),
    pytest.param(
        lambda out: FetchRequest(out_dir=out, station_ids=("A", "B", "A")),
        DataRequestError,
        "repeat",
        id="a station twice",
    ),
    pytest.param(
        lambda out: FetchRequest(out_dir=out, extent=(-2.0, 48.0, -1.5, 48.4)),
        DataRequestError,
        "which CRS",
        id="a bare tuple for an extent",
    ),
    pytest.param(lambda out: FetchRequest(out_dir=42), DataRequestError, "", id="nowhere to write"),
    pytest.param(
        lambda out: require_declared_variables(_Source(), ("other",)),
        DataProductError,
        "does not name",
        id="a variable the source does not declare",
    ),
]


@pytest.mark.parametrize(("ask", "error", "said"), REQUESTS)
def test_a_request_is_refused_before_a_source_is_asked(
    tmp_path: Path, ask: Callable[[Path], object], error: type[Exception], said: str
) -> None:
    with pytest.raises(error, match=said or None):
        ask(tmp_path)


RESULTS = [
    pytest.param(
        lambda: FetchResult(source_id="x", kind="files", variables=(), files=()),
        "names no variable",
        id="no variable",
    ),
    pytest.param(
        lambda: FetchResult(
            source_id="x",
            kind="points",
            variables=("v",),
            files=(FileRecord.of(Path(__file__), state="raw", origin="test"),),
        ),
        "declares kind",
        id="a payload the kind does not name",
    ),
    pytest.param(
        lambda: FetchResult(source_id="x", kind="files", variables=("v",), files=(Path("a.tif"),)),
        "FileRecord",
        id="files that are not sealed records",
    ),
]


@pytest.mark.parametrize(("build", "said"), RESULTS)
def test_a_result_that_contradicts_its_kind_is_refused(
    build: Callable[[], object], said: str
) -> None:
    with pytest.raises(DataProductError, match=said):
        build()


# --- the bounds of a call -------------------------------------------------------------------------

BOUNDS = [
    pytest.param({"max_download_bytes": 0}, id="zero bytes"),
    pytest.param({"max_download_bytes": -5}, id="negative bytes"),
    pytest.param({"max_download_bytes": 1.5}, id="float bytes"),
    pytest.param({"max_download_bytes": True}, id="bool bytes"),
    pytest.param({"timeout_s": 0}, id="zero delay"),
    pytest.param({"timeout_s": -0.5}, id="negative delay"),
    pytest.param({"timeout_s": "30"}, id="string delay"),
    pytest.param({"allowed_hosts": {""}}, id="empty host"),
    pytest.param({"allowed_hosts": {"   "}}, id="blank host"),
    pytest.param({"allowed_hosts": {"http://api.geosas.fr"}}, id="host with a scheme"),
    pytest.param({"allowed_hosts": {"api.geosas.fr/hydro"}}, id="host with a path"),
    pytest.param({"allowed_roots": ("relative/one",)}, id="relative root"),
    pytest.param({"allowed_roots": (3.5,)}, id="root that is not a path"),
    pytest.param({"allowed_roots": ("",)}, id="empty root"),
]


@pytest.mark.parametrize("kwargs", BOUNDS)
def test_bounds_that_mean_nothing_are_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(BoundsError):
        Bounds(**kwargs)


def test_a_host_outside_the_list_is_named_with_the_list_and_the_option() -> None:
    with pytest.raises(BoundsError) as raised:
        Bounds(allowed_hosts=frozenset({GEOPF})).require_host(GEO, why="asking hydrometry_hubeau")

    message = str(raised.value)
    assert "asking hydrometry_hubeau" in message
    assert GEO in message and GEOPF in message
    assert "--allow-host" in message and "Bounds(allowed_hosts=...)" in message


def test_every_host_refused_is_named_at_once() -> None:
    bounds = Bounds(allowed_hosts=frozenset({GEOPF}))

    with pytest.raises(BoundsError) as raised:
        bounds.require_hosts((GEO, GEOPF, "overpass-api.de"), why="asking crossings_bdtopo")

    assert "overpass-api.de" in str(raised.value) and GEO in str(raised.value)


def test_a_path_outside_the_roots_is_named_with_the_roots(tmp_path: Path) -> None:
    root, other = tmp_path / "allowed", tmp_path / "elsewhere"
    root.mkdir()
    other.mkdir()

    with pytest.raises(BoundsError) as raised:
        Bounds(allowed_roots=(root,)).require_path(other / "exports", why="delivering a copy")

    assert str(other / "exports") in str(raised.value)
    assert str(root) in str(raised.value)
    assert "Bounds(allowed_roots=...)" in str(raised.value)


# --- the file of credentials -----------------------------------------------------------------------

PREFIX = "ftps://depot.example.org/hydromodpy/"
BLOCK = f'prefix = "{PREFIX}"\nuser = "bastien"\npassword = "s3cr3t"\n'
CREDENTIAL_FILES = [
    pytest.param('[[host]]\nuser = "b"\n', 0o600, "prefix", id="a block without a prefix"),
    pytest.param(
        f'[[host]]\nprefix = "{PREFIX}"\npassword = "a"\npassword_file = "secret"\n',
        0o600,
        "together",
        id="a password and a file together",
    ),
    pytest.param(
        '[[host]]\nprefix = "file:///data/raster.tif"\nuser = "b"\n',
        0o600,
        "ftp, ftps, sftp, http or https",
        id="a prefix of another scheme",
    ),
    pytest.param(
        f'[[host]]\nprefix = "{PREFIX}"\nuser = "b"\norganisation = "nope"\n',
        0o600,
        "organisation",
        id="an unknown key",
    ),
    pytest.param(f"[[host]]\n{BLOCK}", 0o644, "chmod 600", id="a file others can read"),
    pytest.param("[[host]]\nprefix = \n", 0o600, "not a valid TOML file", id="not TOML"),
]


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
@pytest.mark.parametrize(("body", "mode", "said"), CREDENTIAL_FILES)
def test_a_credentials_file_that_breaks_a_rule_is_refused(
    tmp_path: Path, body: str, mode: int, said: str
) -> None:
    path = tmp_path / "credentials.toml"
    path.write_text(body)
    path.chmod(mode)

    with pytest.raises(CredentialsError, match=said):
        load_credentials(path, forbidden_roots=())


def test_a_credentials_file_named_and_absent_is_a_configuration_refusal(tmp_path: Path) -> None:
    with pytest.raises(CredentialsError) as raised:
        load_credentials(tmp_path / "absent.toml")

    assert "does not exist" in str(raised.value) and "absent.toml" in str(raised.value)
    assert not isinstance(raised.value, FileNotFoundError)


# --- a user file without a CRS ----------------------------------------------------------------------


def _raster(path: Path) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        transform=Affine(25.0, 0.0, 350000.0, 0.0, -25.0, 6790000.0),
        crs=None,
        nodata=-9999.0,
    ) as target:
        target.write(np.ones((1, 4, 4), dtype="float32"))
    return path


def _vector(path: Path, geometry: Any) -> Path:
    gpd.GeoDataFrame({"code": [1]}, geometry=[geometry]).to_file(path)
    return path


def _a_dem(folder: Path) -> object:
    return load_custom_dem(SimpleNamespace(path=_raster(folder / "dem.tif")))


def _a_geology_raster(folder: Path) -> object:
    return load_custom_geology(SimpleNamespace(path=_raster(folder / "geology.tif")))


def _a_geology_vector(folder: Path) -> object:
    path = _vector(folder / "geology.gpkg", box(0, 0, 10, 10))
    return load_custom_geology(SimpleNamespace(path=path), code_field="code")


def _a_river_vector(folder: Path) -> object:
    return load_file(
        SimpleNamespace(path=_vector(folder / "rivers.gpkg", LineString([(0, 0), (9, 9)])))
    )


def _a_river_raster(folder: Path) -> object:
    return load_file(SimpleNamespace(path=_raster(folder / "rivers.tif")))


FILES_WITHOUT_A_CRS = [
    pytest.param(_a_dem, "dem", id="a DEM"),
    pytest.param(_a_geology_raster, "geology", id="a geology raster"),
    pytest.param(_a_geology_vector, "geology", id="a geology vector"),
    pytest.param(_a_river_vector, "hydrography", id="a river vector"),
    pytest.param(_a_river_raster, "hydrography", id="a river raster"),
]


@pytest.mark.parametrize(("read", "variable"), FILES_WITHOUT_A_CRS)
def test_a_user_file_without_a_crs_is_refused_by_name(
    tmp_path: Path, read: Callable[[Path], object], variable: str
) -> None:
    with pytest.raises(DataContractViolation, match=rf"{variable}: .*declares no CRS"):
        read(tmp_path)


# --- the data cache ---------------------------------------------------------------------------------


@pytest.fixture
def frozen(tmp_path: Path) -> tuple[Path, LockedInputs]:
    """A project whose lockfile pins station A and the user file ``inputs/dem.tif``."""
    project = tmp_path / "project"
    data_root = project / "data"
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True)
    chronicle = folder / "hydrometry_hubeau_A_2000.csv"
    chronicle.write_text("datetime,value\n2000-01-01,1.0\n")
    CacheIndex(data_root).record(chronicle, variable="hydrometry", source="hubeau", station_id="A")
    mine = project / "inputs" / "dem.tif"
    mine.parent.mkdir()
    mine.write_bytes(b"dem")
    user = user_file_input(mine, variable="dem", project_root=project, sha256=sha256_of(mine))
    write_lockfile(project_lockfile_path(project), data_root, user_files=[user])
    return data_root, read_locked_inputs(project)


def _find(root: Path, locked: LockedInputs, station: str) -> object:
    return CacheIndex(root, locked=locked).find("hydrometry", "hubeau", station_id=station)


def _record(root: Path, locked: LockedInputs | None, station: str) -> None:
    other = root / "hydrometry" / f"hydrometry_hubeau_{station}_2000.csv"
    other.write_text("datetime,value\n")
    CacheIndex(root, locked=locked).record(
        other, variable="hydrometry", source="hubeau", station_id=station
    )


def _a_row_the_lockfile_does_not_pin(root: Path, locked: LockedInputs) -> None:
    _record(root, None, "B")
    _find(root, locked, "B")


def _other_bytes(root: Path, locked: LockedInputs) -> None:
    path = root / "hydrometry" / "hydrometry_hubeau_A_2000.csv"
    path.write_text("datetime,value\n2000-01-01,2.0\n")
    write_sidecar(path, load_sidecar(path).model_copy(update={"sha256": sha256_of(path)}))
    _find(root, locked, "A")


def _an_empty_answer(root: Path, locked: LockedInputs) -> None:
    CacheIndex(root, locked=locked).record_empty(
        empty_path_for(root / "hydrometry", "hydrometry_hubeau_C"),
        variable="hydrometry",
        source="hubeau",
        station_id="C",
    )


def _a_user_file_of_other_bytes(root: Path, locked: LockedInputs) -> None:
    mine = root.parent / "inputs" / "dem.tif"
    mine.write_bytes(b"other dem")
    reject_frozen_user_file(locked, variable="dem", path=mine)


def _a_user_file_nobody_pinned(root: Path, locked: LockedInputs) -> None:
    other = root.parent / "inputs" / "other.tif"
    other.write_bytes(b"other")
    reject_frozen_user_file(locked, variable="dem", path=other)


FROZEN_REFUSALS = [
    pytest.param(
        lambda root, locked: _find(root, locked, "Z"),
        "forbids cache misses: hydrometry/hubeau/Z is absent from the data cache",
        id="a miss",
    ),
    pytest.param(
        _a_row_the_lockfile_does_not_pin,
        "forbids data cache rows absent from hydromodpy.lock",
        id="a row the lockfile does not pin",
    ),
    pytest.param(_other_bytes, "SHA-256 mismatch", id="a row of other bytes"),
    pytest.param(
        lambda root, locked: _record(root, locked, "B"),
        "forbids registering a downloaded artefact absent",
        id="a new record",
    ),
    pytest.param(
        _an_empty_answer,
        "forbids registering a downloaded artefact absent",
        id="a new empty answer",
    ),
    pytest.param(
        lambda root, locked: reject_frozen_download(
            locked, variable="hydrometry", source="hubeau", station_id="A", detail="is asked"
        ),
        "forbids a download: hydrometry/hubeau/A is asked",
        id="a download",
    ),
    pytest.param(
        _a_user_file_of_other_bytes,
        "user file whose SHA-256 does not match",
        id="a user file of other bytes",
    ),
    pytest.param(
        _a_user_file_nobody_pinned,
        "user file absent from hydromodpy.lock",
        id="a user file nobody pinned",
    ),
]


@pytest.mark.parametrize(("act", "said"), FROZEN_REFUSALS)
def test_a_frozen_project_refuses_what_its_lockfile_does_not_pin(
    frozen: tuple[Path, LockedInputs],
    act: Callable[[Path, LockedInputs], object],
    said: str,
) -> None:
    root, locked = frozen

    with pytest.raises(FrozenDataError, match=said):
        act(root, locked)


SIDECARS = [
    pytest.param(
        {"source": "hubeau", "sha256": "0" * 64, "bytes": 1}, "names no variable", id="no variable"
    ),
    pytest.param(
        {"source": "hubeau", "sha256": "0" * 64, "variable": "hydrometry"},
        "carries no bytes",
        id="no size",
    ),
]


@pytest.mark.parametrize(("fields", "said"), SIDECARS)
def test_a_sidecar_is_refused_at_writing(tmp_path: Path, fields: dict[str, Any], said: str) -> None:
    target = tmp_path / "x.csv"
    target.write_bytes(b"x")

    with pytest.raises(DataCacheError, match=said):
        write_sidecar(target, Sidecar(**fields))

    assert not (tmp_path / "x.csv.json").exists()


def test_a_lockfile_of_a_later_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "hydromodpy.lock"
    path.write_text('schema = "hydromodpy.lock.v3"\n')

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.lock.v3"):
        read_lockfile_inputs(path)
