"""``data-fetch`` invoked the way an orchestrator invokes it.

One directory in, one seal out. These tests read the directory the way a
stranger would -- with ``geopandas``, ``pandas``, ``xarray`` and ``json``, never
through the objects that wrote it -- because what the boundary promises is that
a third party can do exactly that.

**What is stubbed, and what is not.** The provider function of the source under
test is replaced by a recorder that returns a canned payload, which is the
layer-A stage the data-source conformance suite already works in: what these
tests hold is the capability's own plumbing -- resolution, refusal, artefact,
input set, seal, reuse -- and not that Hub'Eau answers. The two tests that do
*not* stub anything are the two that run the capability in a subprocess: the
confinement gate, which reads what it created on the filesystem, and the egress
gate, which reads what it resolved on a socket. Those two are meaningless
against a stub, so they run the real thing and tolerate its failing offline.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_USAGE, EXIT_VALIDATION
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.data.fetch.artefacts import FEATURES_LAYER, POINT_COLUMNS
from hydromodpy.data.fetch.capability import (
    DATA_FETCH,
    FEATURES_PATH,
    FIELDS_PATH,
    POINTS_PATH,
    RASTER_PATH,
    REPORT_PATH,
)
from hydromodpy.data.fetch.worker import run
from hydromodpy.schema.job import JobDirectory, read_document, verify_job
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES

gpd = pytest.importorskip("geopandas")
pd = pytest.importorskip("pandas")
xr = pytest.importorskip("xarray")
rasterio = pytest.importorskip("rasterio")

from hydromodpy.cli.helpers import exit_code_for  # noqa: E402

CALLER_BBOX = [-1.85, 48.05, -1.55, 48.25]
CALLER_CRS = "EPSG:4326"
PERIOD = {"start": "2020-01-01", "end": "2020-01-31"}


# --------------------------------------------------------------------------- #
# Staging
# --------------------------------------------------------------------------- #


def _request(source: dict, **overrides: object) -> dict:
    inputs: dict[str, object] = {
        "source": source,
        "extent": {"bbox": list(CALLER_BBOX), "crs": CALLER_CRS},
    }
    inputs.update(overrides.pop("inputs", {}))  # type: ignore[arg-type]
    for key in ("extent", "mask", "station_ids"):
        if inputs.get(key) is None:
            inputs.pop(key, None)
    document: dict[str, object] = {
        "process": {"id": "data-fetch", "version": "1.0.0"},
        "inputs": inputs,
    }
    document.update(overrides)
    return document


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


# --------------------------------------------------------------------------- #
# Canned payloads, one per family
# --------------------------------------------------------------------------- #


def _feature_frame(rows: int = 2):
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        {"name": [f"stream-{index}" for index in range(rows)]},
        geometry=[LineString([(-1.8, 48.1), (-1.7 + 0.01 * index, 48.2)]) for index in range(rows)],
        crs="EPSG:4326",
    )


def _point_records(stations: int = 2):
    from hydromodpy.data.contracts.location import StationLocation
    from hydromodpy.data.contracts.timeseries import PointRecord

    records = []
    for index in range(stations):
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", periods=3, freq="D"),
                "value": [10.0 + index, 11.0 + index, 12.0 + index],
            }
        )
        records.append(
            PointRecord(
                station_id=f"BSS{index:04d}",
                variable="groundwater_level",
                source="hubeau",
                unit="m NGF",
                frequency="D",
                data=frame,
                date_start=datetime(2020, 1, 1),
                date_end=datetime(2020, 1, 3),
                location=StationLocation(
                    id=f"BSS{index:04d}", x=-1.7 + 0.01 * index, y=48.1, crs="EPSG:4326"
                ),
            )
        )
    return records


def _field_records():
    from hydromodpy.data.contracts.spatial_field import FieldRecord

    times = pd.date_range("2020-01-01", periods=3, freq="D")
    dataset = xr.Dataset(
        {
            "precipitation_total": (
                ("time", "y", "x"),
                [[[1.0, 2.0], [3.0, 4.0]] for _ in range(3)],
            )
        },
        coords={"time": times, "y": [6780000.0, 6781000.0], "x": [350000.0, 351000.0]},
    )
    return [
        FieldRecord(
            variable="precipitation_total",
            source="sim2",
            unit="mm/day",
            data=dataset,
            bbox=(350000.0, 6780000.0, 351000.0, 6781000.0),
            crs="EPSG:2154",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 31),
            frequency="D",
        )
    ]


def _write_raster(path: Path) -> Path:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    transform = rasterio.transform.from_origin(350000.0, 6781000.0, 25.0, 25.0)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
    ) as handle:
        handle.write(np.arange(16, dtype="float32").reshape(4, 4), 1)
    return path


# --------------------------------------------------------------------------- #
# Provider stubs
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_bdtopage(monkeypatch):
    """Replace the WFS walker with a recorder that returns a canned frame."""
    import hydromodpy.data.variables.hydrography.apis.bdtopage as provider

    calls: list[dict] = []
    payload = {"frame": _feature_frame()}

    def _record(config, bbox):
        calls.append({"config": config, "bbox": bbox})
        return payload["frame"]

    monkeypatch.setattr(provider, "fetch", _record)
    return calls, payload


@pytest.fixture
def stub_hubeau(monkeypatch):
    import hydromodpy.data.variables.piezometry.apis.hubeau as provider

    calls: list[dict] = []
    payload = {"records": _point_records()}

    def _record(**kwargs):
        calls.append(kwargs)
        return payload["records"]

    monkeypatch.setattr(provider, "fetch", _record)
    return calls, payload


@pytest.fixture
def stub_sim2(monkeypatch):
    import hydromodpy.data.variables.precipitation.apis.sim2 as provider

    calls: list[dict] = []
    payload = {"records": _field_records()}

    def _record(config, *, bbox, project_period):
        calls.append({"bbox": bbox, "project_period": project_period})
        return payload["records"]

    monkeypatch.setattr(provider, "fetch", _record)
    return calls, payload


@pytest.fixture
def stub_ign(monkeypatch):
    """Land a raster and the provider's own junk in the directory it is given."""
    import hydromodpy.data.variables.dem.apis.ign_dem_fr as provider

    calls: list[dict] = []
    payload: dict = {"suffix": ".tif", "count": 1}

    def _record(*, output_dir, bbox, **kwargs):
        calls.append({"output_dir": Path(output_dir), "bbox": bbox, **kwargs})
        root = Path(output_dir)
        (root / "raw_ign").mkdir(parents=True, exist_ok=True)
        (root / "raw_ign" / "BDALTIV2_035.7z").write_bytes(b"archive")
        merged = root / "processed" / f"dem_merged{payload['suffix']}"
        if payload["suffix"] in (".tif", ".tiff"):
            _write_raster(merged)
        else:
            merged.parent.mkdir(parents=True, exist_ok=True)
            merged.write_bytes(b"not a raster")
        return merged

    monkeypatch.setattr(provider, "fetch_ign_dem", _record)
    return calls, payload


BDTOPAGE = {"id": "bdtopage"}
HUBEAU = {"id": "hubeau-piezometry"}
IGN = {"id": "ign-bdalti"}
SIM2 = {"id": "sim2-precipitation"}


@pytest.fixture
def sealed_features(tmp_path, stub_bdtopage):
    job = _staged(tmp_path, _request(BDTOPAGE))
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job, outcome


# --------------------------------------------------------------------------- #
# The seal, and what a stranger finds in the directory
# --------------------------------------------------------------------------- #


def test_a_job_that_finished_is_sealed_and_verifies_against_its_own_seal(sealed_features):
    job, _ = sealed_features

    assert job.is_sealed
    assert verify_job(job).ok


def test_the_directory_carries_only_the_names_the_layout_allows(sealed_features):
    job, _ = sealed_features

    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES


def test_outputs_holds_the_report_and_the_one_payload_the_kind_names(sealed_features):
    job, _ = sealed_features

    assert {entry.name for entry in job.outputs_dir.iterdir()} == {"fetch.json", "features.gpkg"}


def test_the_seal_and_the_outcome_name_one_job(sealed_features):
    job, outcome = sealed_features
    manifest = read_document(job.manifest_path)

    assert manifest["job_id"] == outcome.job_id
    assert read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")


def test_a_stranger_opens_the_features_with_geopandas_alone(sealed_features):
    job, _ = sealed_features

    frame = gpd.read_file(job.outputs_dir / "features.gpkg", layer=FEATURES_LAYER)

    assert len(frame) == 2
    assert str(frame.crs) == "EPSG:4326"


def test_a_stranger_opens_the_points_with_pandas_alone(tmp_path, stub_hubeau):
    job = _staged(tmp_path, _request(HUBEAU, inputs={"period": dict(PERIOD)}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    table = pd.read_parquet(job.resolve_output(POINTS_PATH))
    assert list(table.columns) == list(POINT_COLUMNS)
    assert len(table) == 6
    assert sorted(set(table["station_id"])) == ["BSS0000", "BSS0001"]
    assert set(table["station_crs"]) == {"EPSG:4326"}


def test_a_stranger_opens_the_fields_with_xarray_alone(tmp_path, stub_sim2):
    job = _staged(tmp_path, _request(SIM2, inputs={"period": dict(PERIOD)}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    with xr.open_dataset(job.resolve_output(FIELDS_PATH)) as dataset:
        assert list(dataset.data_vars) == ["precipitation_total"]
        assert dataset["precipitation_total"].attrs["units"] == "mm/day"
        assert dataset.attrs["crs"] == "EPSG:2154"


def test_a_stranger_opens_the_raster_with_rasterio_alone(tmp_path, stub_ign):
    job = _staged(tmp_path, _request(IGN))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    with rasterio.open(job.resolve_output(RASTER_PATH)) as handle:
        assert handle.count == 1
        assert str(handle.crs) == "EPSG:2154"


def test_the_provider_junk_stays_out_of_the_sealed_directory(tmp_path, stub_ign):
    """The source writes an archive tree beside its raster, and only one is sealed."""
    job = _staged(tmp_path, _request(IGN))

    run(job, exit_code_for=exit_code_for)

    assert {entry.name for entry in job.outputs_dir.iterdir()} == {"fetch.json", "raster.tif"}
    manifest = read_document(job.manifest_path)
    assert not [entry for entry in manifest["artifacts"] if "raw_ign" in entry["path"]], (
        "the provider's archive tree reached the seal"
    )


# --------------------------------------------------------------------------- #
# The report, and the extent that was really queried
# --------------------------------------------------------------------------- #


def test_the_report_names_the_payload_and_the_artefact_it_wrote(sealed_features):
    job, _ = sealed_features
    report = read_document(job.resolve_output(REPORT_PATH))

    assert report["source"] == "bdtopage"
    assert report["payload_kind"] == "features"
    assert report["empty"] is False
    assert report["artifacts"] == [FEATURES_PATH]
    assert report["counts"] == {"features": 2}


def test_the_report_carries_the_extent_in_the_crs_the_source_was_queried_in(tmp_path, stub_ign):
    """The caller passes WGS84; the Geoplateforme is asked in Lambert-93 metres.

    This is the port's central claim, and the report is the only place on disk
    where a caller can read it back: the raster carries the CRS of the tiles, not
    the CRS the query was expressed in.
    """
    calls, _ = stub_ign
    job = _staged(tmp_path, _request(IGN))

    run(job, exit_code_for=exit_code_for)

    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["queried_extent"]["crs"] == "EPSG:2154"
    assert report["queried_extent"]["bbox"] == pytest.approx(list(calls[0]["bbox"]))
    assert max(report["queried_extent"]["bbox"]) > 1e5, "these are not metres"


def test_the_report_names_the_host_the_run_really_contacted(tmp_path, stub_bdtopage):
    """The declaration is the union of four providers; the report is the one.

    Without this the only place a host appeared was ``provenance.json``, and a
    reader of the report had to hold the source-to-host table of this repository
    to turn ``"bdtopage"`` into something a firewall log can be compared to.
    """
    from hydromodpy.data.source.bdtopage import BdTopageSource

    job = _staged(tmp_path, _request(BDTOPAGE))

    run(job, exit_code_for=exit_code_for)

    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["hosts"] == list(BdTopageSource.hosts)
    assert set(report["hosts"]) < set(DATA_FETCH.reaches_network), (
        "one run reaches one provider, and the declaration covers all four"
    )


def test_the_report_carries_the_period_a_timed_source_was_asked_for(tmp_path, stub_hubeau):
    job = _staged(tmp_path, _request(HUBEAU, inputs={"period": dict(PERIOD)}))

    run(job, exit_code_for=exit_code_for)

    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["queried_period"]["start"].startswith("2020-01-01")
    assert report["queried_period"]["end"].startswith("2020-01-31")


def test_an_empty_answer_is_a_success_that_seals_the_report_and_no_data(tmp_path, stub_bdtopage):
    """A box over the sea holds no river, and that is an answer, not a failure."""
    _, payload = stub_bdtopage
    payload["frame"] = _feature_frame(rows=0)
    job = _staged(tmp_path, _request(BDTOPAGE))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful"
    assert verify_job(job).ok
    assert {entry.name for entry in job.outputs_dir.iterdir()} == {"fetch.json"}
    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["empty"] is True
    assert report["artifacts"] == []
    assert any("empty" in warning for warning in outcome.warnings)


def test_a_station_list_is_a_selector_of_its_own_and_reaches_the_provider(tmp_path, stub_hubeau):
    """The one source that selects by station, asked that way end to end."""
    calls, _ = stub_hubeau
    job = _staged(
        tmp_path,
        _request(
            HUBEAU,
            inputs={"extent": None, "station_ids": ["BSS0000", "BSS0001"], "period": dict(PERIOD)},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert calls[0]["station_ids"] == ["BSS0000", "BSS0001"]
    assert calls[0]["bbox"] is None
    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["queried_extent"] is None


def test_a_station_asked_for_twice_is_refused_before_the_job_is_touched(tmp_path, stub_hubeau):
    """The refusal used to land after ``outputs/`` and ``logs/`` had been made.

    The port refuses a repeated station id too, but it does so inside the fetch,
    which is after ``ensure_workspace``. The promise this file holds is that a
    refused document leaves the directory exactly as the caller staged it, so
    the refusal belongs in the model.
    """
    calls, _ = stub_hubeau
    job = _staged(
        tmp_path,
        _request(
            HUBEAU,
            inputs={"extent": None, "station_ids": ["BSS0000", "BSS0000"], "period": dict(PERIOD)},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert not calls
    assert {entry.name for entry in job.root.iterdir()} == {"request.json", "outcome.json"}


def test_two_stations_that_disagree_about_the_clock_are_refused_by_name(tmp_path, stub_hubeau):
    """One table carries one datetime column, and mixing the two crashed it.

    Before the refusal, ``sort_values`` raised a bare ``TypeError`` out of its
    lexsort path and the process answered ``HMPY.E000`` and exit 1 -- the code
    whose whole meaning is "this is a bug in HydroModPy" -- for what is an
    ordinary quirk of a provider that paginates.
    """
    _, payload = stub_hubeau
    naive, aware = _point_records()
    aware.data["datetime"] = aware.data["datetime"].dt.tz_localize("UTC")
    payload["records"] = [naive, aware]
    job = _staged(tmp_path, _request(HUBEAU, inputs={"period": dict(PERIOD)}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.errors[0]["code"] == "HMPY.E209"
    assert "BSS0000" in json.dumps(outcome.errors)
    assert not job.is_sealed


def test_fields_on_grids_that_do_not_align_are_refused_instead_of_padded(tmp_path, stub_sim2):
    """The outer join xarray defaults to publishes a field nobody asked for.

    Measured before the fix: two 2x2 grids a megametre apart merged into one 4x4
    grid, three quarters of it NaN, sealed without a word.
    """
    _, payload = stub_sim2
    first = _field_records()[0]
    second = _field_records()[0]
    second.variable = "precipitation_liquid"
    second.data = second.data.rename({"precipitation_total": "precipitation_liquid"}).assign_coords(
        x=[1_350_000.0, 1_351_000.0], y=[7_780_000.0, 7_781_000.0]
    )
    payload["records"] = [first, second]
    job = _staged(tmp_path, _request(SIM2, inputs={"period": dict(PERIOD)}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.errors[0]["code"] == "HMPY.E209"
    assert not job.is_sealed
    assert not job.resolve_output(FIELDS_PATH).exists()


def test_the_outcome_declares_the_input_set_the_seal_also_carries(tmp_path, stub_bdtopage):
    """Two documents of one directory may not disagree about what was produced.

    ``inputset.json`` is a declared output. A version of ``_output_records``
    that walked the payload list alone left it out of ``outcome.json`` while the
    seal still carried it, and nothing read the two together.
    """
    job = _staged(tmp_path, _request(BDTOPAGE))

    outcome = run(job, exit_code_for=exit_code_for)

    manifest = read_document(job.manifest_path)
    sealed = {entry["path"]: entry["sha256"] for entry in manifest["artifacts"]}
    declared = {record.path: record.sha256 for record in outcome.outputs}
    assert "inputset.json" in declared
    assert declared["inputset.json"] == sealed["inputset.json"]
    assert set(declared) == set(sealed) - {"provenance.json", "outcome.json"}


# --------------------------------------------------------------------------- #
# The mask: what makes two capabilities chain through a directory
# --------------------------------------------------------------------------- #


def _mask_file(tmp_path: Path, name: str = "watershed.gpkg") -> Path:
    from shapely.geometry import box

    frame = gpd.GeoDataFrame(
        {"site_id": ["valley"]},
        geometry=[box(347000.0, 6778000.0, 352000.0, 6783000.0)],
        crs="EPSG:2154",
    )
    target = tmp_path / name
    frame.to_file(str(target), driver="GPKG", layer="watershed")
    return target


def test_a_mask_is_the_extent_and_reaches_the_provider_reprojected(tmp_path, stub_bdtopage):
    calls, _ = stub_bdtopage
    mask = _mask_file(tmp_path)
    job = _staged(
        tmp_path,
        _request(BDTOPAGE, inputs={"extent": None, "mask": {"href": str(mask)}}),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    report = read_document(job.resolve_output(REPORT_PATH))
    assert report["queried_extent"]["crs"] == "EPSG:4326"
    assert report["queried_extent"]["bbox"] == pytest.approx(list(calls[0]["bbox"]))
    assert -3.0 < report["queried_extent"]["bbox"][0] < 0.0, "these are not degrees"


def test_the_input_set_records_the_mask_by_its_digest(tmp_path, stub_bdtopage):
    from hydromodpy.schema.job.digest import sha256_file

    mask = _mask_file(tmp_path)
    job = _staged(
        tmp_path,
        _request(BDTOPAGE, inputs={"extent": None, "mask": {"href": str(mask)}}),
    )

    run(job, exit_code_for=exit_code_for)

    inputset = read_document(job.inputset_path)
    resource = next(one for one in inputset["resources"] if one["name"] == "mask")
    digest, size = sha256_file(mask)
    assert resource["sha256"] == digest
    assert resource["bytes"] == size


def test_a_mask_whose_bytes_are_not_the_pinned_ones_is_refused(tmp_path, stub_bdtopage):
    mask = _mask_file(tmp_path)
    job = _staged(
        tmp_path,
        _request(
            BDTOPAGE,
            inputs={"extent": None, "mask": {"href": str(mask), "sha256": "00" * 32}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert not job.is_sealed


def test_a_mask_that_is_not_a_vector_file_is_refused_as_bad_input(tmp_path, stub_bdtopage):
    """Without the check it surfaced as HMPY.E000 and exit 1: a bug in HydroModPy."""
    mask = tmp_path / "not_a_mask.gpkg"
    mask.write_text("this is prose", encoding="utf-8")
    job = _staged(
        tmp_path,
        _request(BDTOPAGE, inputs={"extent": None, "mask": {"href": str(mask)}}),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert outcome.errors[0]["code"] == "HMPY.E207"


def test_a_mask_that_is_not_there_is_refused_as_not_found(tmp_path, stub_bdtopage):
    job = _staged(
        tmp_path,
        _request(BDTOPAGE, inputs={"extent": None, "mask": {"href": str(tmp_path / "gone.gpkg")}}),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_NOT_FOUND


# --------------------------------------------------------------------------- #
# Identity and reuse
# --------------------------------------------------------------------------- #


def test_two_submissions_that_differ_only_by_an_omitted_default_carry_one_job_id(
    tmp_path, stub_bdtopage
):
    from hydromodpy.data.source.bdtopage import DEFAULT_PAGE_SIZE

    bare = _staged(tmp_path, _request(BDTOPAGE), name="bare")
    spelled = _staged(
        tmp_path,
        _request({"id": "bdtopage", "page_size": DEFAULT_PAGE_SIZE}),
        name="spelled",
    )

    first = run(bare, exit_code_for=exit_code_for)
    second = run(spelled, exit_code_for=exit_code_for)

    assert first.job_id == second.job_id


def test_a_sealed_directory_under_the_same_id_is_re_reported_and_not_re_run(
    tmp_path, stub_bdtopage
):
    calls, _ = stub_bdtopage
    job = _staged(tmp_path, _request(BDTOPAGE))
    first = run(job, exit_code_for=exit_code_for)
    assert len(calls) == 1

    second = run(job, exit_code_for=exit_code_for)

    assert second.reused is True
    assert second.job_id == first.job_id
    assert second.exit_code == 0
    assert len(calls) == 1, "the provider was asked again for a job that was already sealed"


def test_a_sealed_directory_under_another_id_is_refused(tmp_path, stub_bdtopage):
    job = _staged(tmp_path, _request(BDTOPAGE))
    run(job, exit_code_for=exit_code_for)
    job.request_path.write_text(
        json.dumps(_request({"id": "bdtopage", "page_size": 7})), encoding="utf-8"
    )

    with pytest.raises(JobUsageError, match="sealed under"):
        run(job, exit_code_for=exit_code_for)


# --------------------------------------------------------------------------- #
# Refusals, before a provider is reached
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("inputs", "fragment"),
    [
        ({"extent": None}, "selects nothing"),
        ({"station_ids": ["BSS0000"]}, "at once"),
        ({"mask": {"href": "watershed.gpkg"}}, "at once"),
        ({"extent": {"bbox": [1.0, 2.0, 1.0, 3.0], "crs": "EPSG:4326"}}, "empty or inverted"),
        ({"extent": {"bbox": list(CALLER_BBOX), "crs": "lambert93"}}, "crs"),
    ],
    ids=["nothing", "extent-and-stations", "extent-and-mask", "inverted", "bad-crs"],
)
def test_a_request_the_model_refuses_never_reaches_a_provider(
    tmp_path, stub_bdtopage, inputs, fragment
):
    calls, _ = stub_bdtopage
    job = _staged(tmp_path, _request(BDTOPAGE, inputs=inputs))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert not calls
    assert not job.is_sealed
    assert fragment in json.dumps(outcome.errors)


def test_an_unknown_source_id_is_refused_by_the_discriminator(tmp_path):
    job = _staged(tmp_path, _request({"id": "nobody-serves-this"}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG


def test_a_period_handed_to_a_source_without_a_time_axis_is_refused(tmp_path, stub_bdtopage):
    calls, _ = stub_bdtopage
    job = _staged(tmp_path, _request(BDTOPAGE, inputs={"period": dict(PERIOD)}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.errors[0]["code"] == "HMPY.E208"
    assert not calls


def test_a_source_that_needs_a_period_refuses_a_request_without_one(tmp_path, stub_hubeau):
    calls, _ = stub_hubeau
    job = _staged(tmp_path, _request(HUBEAU))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.errors[0]["code"] == "HMPY.E207"
    assert not calls


def test_an_output_name_nobody_declares_is_refused_before_the_run(tmp_path, stub_bdtopage):
    calls, _ = stub_bdtopage
    job = _staged(tmp_path, _request(BDTOPAGE, outputs={"watershed_vector": {}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert not calls


def test_a_request_for_another_capability_is_refused(tmp_path, stub_bdtopage):
    document = _request(BDTOPAGE)
    document["process"] = {"id": "terrain-delineate", "version": "1.0.0"}
    job = _staged(tmp_path, document)

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG


def test_a_files_payload_that_is_not_a_raster_is_refused(tmp_path, stub_ign, monkeypatch):
    """A name the artefact would not describe is worse than a refusal."""
    _, payload = stub_ign
    payload["suffix"] = ".asc"
    job = _staged(tmp_path, _request(IGN))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert not job.is_sealed
    assert "GeoTIFF" in json.dumps(outcome.errors)


def test_a_files_payload_of_more_than_one_file_is_refused(tmp_path, stub_ign, monkeypatch):
    """The declaration names one artefact for that kind, and says so out loud.

    ``PayloadKind`` allows a source to return several files; this capability
    declares a single ``raster.tif`` because the one ``files`` source of this
    tree merges its tiles into one. A second file has no declared name, and
    sealing it under the first one's would describe neither.
    """
    from dataclasses import replace

    import hydromodpy.data.source.ign_dem as adapter

    real = adapter.IgnDemSource.fetch

    def _twice(self, request):
        result = real(self, request)
        return replace(result, files=(*result.files, *result.files))

    monkeypatch.setattr(adapter.IgnDemSource, "fetch", _twice)
    job = _staged(tmp_path, _request(IGN))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert not job.is_sealed
    assert "2 file(s)" in json.dumps(outcome.errors)


def test_a_files_payload_holding_nothing_is_an_empty_answer_and_not_a_refusal(
    tmp_path, stub_ign, monkeypatch
):
    """Zero files is the sea, not a malformed payload.

    ``FetchResult.is_empty`` is what decides, and it decides the same way for the
    four kinds: the run succeeds, the report says so, and no data artefact is
    sealed. Refusing here would make ``files`` the one kind where "the provider
    holds nothing here" is an error.
    """
    from dataclasses import replace

    import hydromodpy.data.source.ign_dem as adapter

    real = adapter.IgnDemSource.fetch
    monkeypatch.setattr(
        adapter.IgnDemSource, "fetch", lambda self, request: replace(real(self, request), files=())
    )
    job = _staged(tmp_path, _request(IGN))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert {entry.name for entry in job.outputs_dir.iterdir()} == {"fetch.json"}
    assert read_document(job.resolve_output(REPORT_PATH))["empty"] is True


def test_an_unknown_capability_id_is_an_invocation_error() -> None:
    from hydromodpy.cli._workers.process import capability

    with pytest.raises(JobUsageError) as caught:
        capability("data-fetch-typo")
    assert exit_code_for(caught.value) == EXIT_USAGE


# --------------------------------------------------------------------------- #
# The two gates that run the real thing in a subprocess
# --------------------------------------------------------------------------- #

_STUB_PROVIDER = (
    "import hydromodpy.data.variables.hydrography.apis.bdtopage as provider\n"
    "import geopandas as gpd\n"
    "from shapely.geometry import LineString\n"
    "provider.fetch = lambda config, bbox: gpd.GeoDataFrame(\n"
    "    {'name': ['a']},\n"
    "    geometry=[LineString([(-1.8, 48.1), (-1.7, 48.2)])],\n"
    "    crs='EPSG:4326',\n"
    ")\n"
)


_WRITE_SPIES = (
    "import builtins, io, os, tempfile\n"
    "seen = []\n"
    "def _note(target):\n"
    "    try:\n"
    "        seen.append(os.fspath(target))\n"
    "    except TypeError:\n"
    # A file descriptor, not a path: whatever it names was opened by a call
    # this spy already saw, or by a C library no spy of this kind can see.
    "        pass\n"
    "real_mkdtemp, real_mkstemp = tempfile.mkdtemp, tempfile.mkstemp\n"
    "real_bopen, real_ioopen, real_osopen = builtins.open, io.open, os.open\n"
    "real_mkdir, real_makedirs = os.mkdir, os.makedirs\n"
    "real_rename, real_replace = os.rename, os.replace\n"
    "WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND\n"
    "def spy_mkdtemp(*a, **k):\n"
    "    path = real_mkdtemp(*a, **k)\n"
    "    _note(path)\n"
    "    return path\n"
    "def spy_mkstemp(*a, **k):\n"
    "    handle, path = real_mkstemp(*a, **k)\n"
    "    _note(path)\n"
    "    return handle, path\n"
    "def _spy_open(real):\n"
    "    def opener(file, mode='r', *a, **k):\n"
    "        if any(flag in mode for flag in 'wax+'):\n"
    "            _note(file)\n"
    "        return real(file, mode, *a, **k)\n"
    "    return opener\n"
    "def spy_osopen(path, flags, *a, **k):\n"
    "    if flags & WRITE_FLAGS:\n"
    "        _note(path)\n"
    "    return real_osopen(path, flags, *a, **k)\n"
    "def spy_mkdir(path, *a, **k):\n"
    "    _note(path)\n"
    "    return real_mkdir(path, *a, **k)\n"
    "def spy_makedirs(name, *a, **k):\n"
    "    _note(name)\n"
    "    return real_makedirs(name, *a, **k)\n"
    "def spy_rename(src, dst, *a, **k):\n"
    "    _note(dst)\n"
    "    return real_rename(src, dst, *a, **k)\n"
    "def spy_replace(src, dst, *a, **k):\n"
    "    _note(dst)\n"
    "    return real_replace(src, dst, *a, **k)\n"
    "tempfile.mkdtemp, tempfile.mkstemp = spy_mkdtemp, spy_mkstemp\n"
    # ``io.open`` as well as ``builtins.open``: they are one function object, but
    # ``pathlib`` reaches it through the ``io`` module, so rebinding only the
    # builtin leaves ``Path.write_text`` invisible -- which is exactly the hole
    # the adversarial gate walked through.
    "builtins.open, io.open = _spy_open(real_bopen), _spy_open(real_ioopen)\n"
    "os.open, os.mkdir, os.makedirs = spy_osopen, spy_mkdir, spy_makedirs\n"
    "os.rename, os.replace = spy_rename, spy_replace\n"
)
"""Every Python-level way this tree creates something on disk, recorded.

The ceiling is stated rather than hidden: a C extension that opens its own
descriptors -- GDAL under ``to_file``, netCDF4 under ``to_netcdf``, pyarrow
under ``write_table`` -- is not seen here, the same way a child process is not
seen by a socket spy. The controlled ``HOME`` below is what covers that gap for
the one location it matters at, and the job directory listing covers the rest.
"""


@pytest.mark.allow_subprocess
def test_it_writes_nowhere_but_the_job_directory_and_the_tmpdir_it_declares(tmp_path):
    """The declaration is a promise an orchestrator mounts the filesystem on.

    The provider is stubbed here because what is under test is where the
    *capability* writes: the scratch it makes, and nothing else. The egress gate
    below is the one that runs the provider for real.

    Two observations, because one is not enough. The spies record every
    Python-level creation, which caught nothing when they watched ``tempfile``
    alone -- a plain ``Path.write_text`` into ``$HOME`` went through the gate
    green. And ``HOME`` is pointed at an empty directory that must still be
    empty afterwards, which holds whatever the spies cannot see: "it registers
    nothing in the user's state directory" has been in the worker's docstring
    since it was written, and this is what checks it.
    """
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    created = tmp_path / "created.json"
    job = _staged(tmp_path, _request(BDTOPAGE))

    script = (
        _WRITE_SPIES
        + "import json, sys\n"
        + _STUB_PROVIDER
        + "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.data.fetch.worker import run\n"
        "try:\n"
        "    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "finally:\n"
        "    real_bopen(sys.argv[2], 'w').write(json.dumps(seen))\n"
        "sys.exit(outcome.exit_code)\n"
    )
    env = dict(os.environ, TMPDIR=str(scratch), HOME=str(home), HMP_NO_PROGRESS="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(created)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    paths = [Path(entry).resolve() for entry in json.loads(created.read_text(encoding="utf-8"))]

    # Derived from the declaration: with ``writes_outside_jobdir`` emptied,
    # ``allowed`` shrinks to the job directory and this test goes red.
    known = {"$TMPDIR": scratch.resolve()}
    unknown = set(DATA_FETCH.writes_outside_jobdir) - set(known)
    assert not unknown, f"this test cannot point at the declared location(s) {sorted(unknown)}"
    allowed = [job.root.resolve()] + [known[name] for name in DATA_FETCH.writes_outside_jobdir]

    # The null device is not the filesystem, and it is reached for a measured
    # reason: ``platform.platform()`` shells out to ``uname -p`` through
    # ``subprocess``, which opens ``os.devnull`` O_RDWR for the child's stderr.
    # It is the same call the child-process pin below accounts for.
    paths = [path for path in paths if path != Path(os.devnull)]
    outside = [path for path in paths if not any(path.is_relative_to(root) for root in allowed)]
    assert not outside, f"it writes into {outside}, which it does not declare"
    assert any(path.is_relative_to(scratch.resolve()) for path in paths), (
        "nothing landed under TMPDIR, so declaring it over-claims"
    )
    assert list(scratch.iterdir()) == [], "the scratch survived the job"
    assert list(home.iterdir()) == [], (
        "it left something in the user's home directory, which it declares it does not"
    )


@pytest.mark.allow_subprocess
def test_the_write_spies_of_the_confinement_gate_catch_a_plain_path_write(tmp_path):
    """Anti-vacuity, and it is not hypothetical: this hole was real.

    The gate used to watch ``tempfile.mkdtemp`` and ``tempfile.mkstemp`` alone,
    so a ``Path.write_text`` outside the job directory passed it green with the
    file sitting on disk. Rather than trusting the widened spies by reading
    them, this runs them over a script that writes the four ways the production
    code can -- ``Path.write_text``, ``open``, ``os.open``, ``os.makedirs`` --
    and asserts each one was recorded.
    """
    created = tmp_path / "created.json"
    target = tmp_path / "leak"

    script = (
        _WRITE_SPIES + "import json, os, sys\n"
        "from pathlib import Path\n"
        "root = Path(sys.argv[1])\n"
        "Path(root / 'by_pathlib.txt').write_text('{}', encoding='utf-8')\n"
        "open(root / 'by_builtin.txt', 'w').close()\n"
        "os.close(os.open(root / 'by_osopen.txt', os.O_WRONLY | os.O_CREAT))\n"
        "os.makedirs(root / 'by_makedirs', exist_ok=True)\n"
        "real_bopen(sys.argv[2], 'w').write(json.dumps(seen))\n"
    )
    target.mkdir()
    completed = subprocess.run(
        [sys.executable, "-c", script, str(target), str(created)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    recorded = {Path(entry).name for entry in json.loads(created.read_text(encoding="utf-8"))}
    assert {
        "by_pathlib.txt",
        "by_builtin.txt",
        "by_osopen.txt",
        "by_makedirs",
    } <= recorded, f"a write escaped the spies; they recorded {sorted(recorded)}"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
"""Names of the local machine. Not egress: reachable with no route out at all."""

CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", "uname")
"""The executables the capability runs, and the ceiling of the two socket spies.

The same two ``terrain-delineate`` spawns, and for the same reasons: ``git``
twice from ``schema/job/provenance.py``, and ``uname -p`` from the standard
library, ``platform.platform()`` unpacking a ``uname_result`` whose ``processor``
member falls back to ``subprocess.check_output``. A capability that shelled out
to ``curl`` would land in this assertion by name.
"""


def _is_local(value: object) -> bool:
    """True when *value* names this machine, in any of its spellings."""
    text = str(value).casefold().rstrip(".")
    if text in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(int(text, 0)).is_loopback
    except (ValueError, TypeError):
        return False


@pytest.mark.allow_subprocess
def test_the_only_hosts_it_contacts_are_the_ones_it_declares(tmp_path):
    """Nothing is stubbed here, and the run is allowed to fail.

    This is the one test of the file that reaches the wire, and it has to: a
    stubbed provider resolves no name, so a gate run against one would pass for
    a capability that contacted anything at all. What is asserted is therefore
    about what was *recorded*, not about the outcome -- offline, the spy records
    the name before ``getaddrinfo`` raises, which is exactly the observation the
    gate needs. The anti-vacuity assertion is that a non-local name was reached
    at all.

    Three angles, because two are not enough: a host resolved by name, a
    connection opened straight to a literal address that resolves nothing, and a
    child process doing its networking in an interpreter this one cannot patch.
    """
    seen = tmp_path / "seen.json"
    # A box a few hundred metres across, and page_size 1: online, the WFS is
    # really walked and answers in a moment; offline, the name is recorded
    # before getaddrinfo raises. Either way the gate reads the same thing.
    job = _staged(
        tmp_path,
        _request(
            {"id": "bdtopage", "page_size": 1},
            inputs={"extent": {"bbox": [-1.681, 48.111, -1.679, 48.113], "crs": "EPSG:4326"}},
        ),
    )

    script = (
        "import json, socket, subprocess, sys\n"
        "names, addrs, spawned = [], [], []\n"
        "real_addrinfo, real_connect = socket.getaddrinfo, socket.socket.connect\n"
        "real_popen = subprocess.Popen.__init__\n"
        "def spy_addrinfo(host, port, *a, **k):\n"
        "    record = [host, port, []]\n"
        "    names.append(record)\n"
        "    answer = real_addrinfo(host, port, *a, **k)\n"
        "    record[2] = sorted({str(entry[4][0]) for entry in answer})\n"
        "    return answer\n"
        "def spy_connect(self, address, *a, **k):\n"
        "    addrs.append(list(address) if isinstance(address, tuple) else [address])\n"
        "    return real_connect(self, address, *a, **k)\n"
        "def spy_popen(self, args, *a, **k):\n"
        "    spawned.append(args if isinstance(args, str) else list(args))\n"
        "    return real_popen(self, args, *a, **k)\n"
        "socket.getaddrinfo, socket.socket.connect = spy_addrinfo, spy_connect\n"
        "subprocess.Popen.__init__ = spy_popen\n"
        # The sentinel. Loopback only, so it needs no route off the machine.
        "socket.getaddrinfo('localhost', 9)\n"
        "probe = socket.socket()\n"
        "try:\n"
        "    probe.connect(('127.0.0.1', 9))\n"
        "except OSError:\n"
        "    pass\n"  # Refused is the expected answer and proves the spy fired.
        "finally:\n"
        "    probe.close()\n"
        "subprocess.run([sys.executable, '-c', ''], capture_output=True)\n"
        "sentinel = {'names': list(names), 'addrs': list(addrs), 'spawned': list(spawned)}\n"
        "names.clear()\n"
        "addrs.clear()\n"
        "spawned.clear()\n"
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.data.fetch.worker import run\n"
        "outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "open(sys.argv[2], 'w').write(\n"
        "    json.dumps(\n"
        "        {\n"
        "            'sentinel': sentinel,\n"
        "            'names': names,\n"
        "            'addrs': addrs,\n"
        "            'spawned': spawned,\n"
        "            'status': outcome.status,\n"
        "        }\n"
        "    )\n"
        ")\n"
    )
    env = dict(os.environ, HMP_NO_PROGRESS="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(seen)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert seen.is_file(), completed.stderr[-4000:]
    recorded = json.loads(seen.read_text(encoding="utf-8"))
    sentinel = recorded["sentinel"]
    assert sentinel["names"] and sentinel["addrs"] and sentinel["spawned"], (
        "a spy caught nothing of the harness's own, so it is not installed"
    )
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"]), (
        "the locality filter does not recognise the local machine it was handed"
    )

    declared = set(DATA_FETCH.reaches_network)
    reached = {str(entry[0]) for entry in recorded["names"] if not _is_local(entry[0])}
    assert reached, (
        "the capability resolved no name at all, so this gate proved nothing; "
        "it is meant to run the real provider"
    )
    assert not sorted(reached - declared), f"it resolves {sorted(reached - declared)}, undeclared"
    # An address is read apart from a name: a connection to a literal address
    # resolves nothing, so the set above would stay empty while the process
    # reached the network anyway. What a *declared* name resolved to is not
    # undeclared egress, and this is the one capability where the distinction
    # shows up -- a socket connects to 195.220.97.40, never to the name. The
    # addresses a declared host answered with are therefore allowed, and an
    # address obtained any other way is not.
    from_declared = {
        address for entry in recorded["names"] if str(entry[0]) in declared for address in entry[2]
    }
    egress = sorted(
        {str(entry[0]) for entry in recorded["addrs"] if not _is_local(entry[0])}
        - declared
        - from_declared
    )
    assert not egress, f"it connects to {egress}, which it does not declare"
    children = sorted(
        {Path(argv[0] if isinstance(argv, list) else argv).name for argv in recorded["spawned"]}
    )
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), (
        f"it spawns {children}, and only {sorted(CHILD_PROCESSES_THE_JOB_SPAWNS)} is accounted for"
    )
