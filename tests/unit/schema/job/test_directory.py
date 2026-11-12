"""The job directory, the only place a capability process may touch.

A path the request declares is resolved inside the directory or refused. A
directory that cannot be used at all is a usage error, which exits 2 and not 1,
so a shim fixes its own call instead of running the job again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_USAGE, exit_code_for
from hydromodpy.core.exceptions import ConfigValidationError, JobUsageError
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES, JOB_WRITE_ORDER, REQUEST_FILENAME

DEM_LOC = ("inputs", "dem", "href")
DEM_POINTER = "/inputs/dem/href"
TIFF_HEADER = b"II*\x00"


def staged_job(tmp_path: Path) -> JobDirectory:
    """A job directory as a caller hands it over, with only its request."""
    root = tmp_path / "job_4711"
    root.mkdir()
    (root / REQUEST_FILENAME).write_text("{}", encoding="utf-8")
    return JobDirectory.open(root)


def test_a_missing_directory_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(JobUsageError) as excinfo:
        JobDirectory.open(tmp_path / "absent")
    assert exit_code_for(excinfo.value) == EXIT_USAGE


def test_a_directory_without_a_request_is_a_usage_error(tmp_path: Path) -> None:
    root = tmp_path / "job_4712"
    root.mkdir()
    with pytest.raises(JobUsageError) as excinfo:
        JobDirectory.open(root)
    assert REQUEST_FILENAME in str(excinfo.value)
    assert exit_code_for(excinfo.value) == EXIT_USAGE


def test_documents_are_named_from_the_root(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    paths = (
        job.request_path,
        job.inputset_path,
        job.provenance_path,
        job.outcome_path,
        job.manifest_path,
        job.outputs_dir,
        job.logs_dir,
        job.log_path,
        job.progress_path,
    )
    assert all(job.contains(path) for path in paths)
    assert not job.is_sealed


def test_top_level_names_are_the_allowed_ones(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    job.ensure_workspace()
    job.outcome_path.write_text("{}", encoding="utf-8")
    job.progress_path.write_text("", encoding="utf-8")

    entries = {entry.name for entry in job.root.iterdir()}

    assert entries <= ALLOWED_JOB_ENTRIES
    assert set(JOB_WRITE_ORDER) <= ALLOWED_JOB_ENTRIES


def test_relative_input_is_resolved_inside_the_job(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    (job.root / "inputs").mkdir()
    dem = job.root / "inputs" / "dem.tif"
    dem.write_bytes(TIFF_HEADER)

    assert job.resolve_input("inputs/dem.tif", loc=DEM_LOC) == dem


def test_absolute_input_is_read_where_it_was_staged(tmp_path: Path) -> None:
    # An orchestrator stages one DEM and points several jobs at it.
    job = staged_job(tmp_path)
    shared = tmp_path / "shared" / "dem.tif"
    shared.parent.mkdir()
    shared.write_bytes(TIFF_HEADER)

    resolved = job.resolve_input(str(shared), loc=DEM_LOC)

    assert resolved == shared.resolve()
    assert not job.contains(resolved)


def test_file_uri_names_the_path_itself(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    dem = tmp_path / "shared dem.tif"
    dem.write_bytes(TIFF_HEADER)

    assert job.resolve_input(dem.as_uri(), loc=DEM_LOC) == dem.resolve()


def test_relative_input_that_walks_out_is_pointed_at(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    (tmp_path / "secret.tif").write_bytes(TIFF_HEADER)

    with pytest.raises(ConfigValidationError) as excinfo:
        job.resolve_input("../secret.tif", loc=DEM_LOC)

    assert exit_code_for(excinfo.value) == EXIT_CONFIG
    assert excinfo.value.details[0]["pointer"] == DEM_POINTER


def test_symlink_pointing_out_is_refused(tmp_path: Path) -> None:
    # Containment is decided on the resolved path, not on the spelling.
    job = staged_job(tmp_path)
    secret = tmp_path / "secret.tif"
    secret.write_bytes(TIFF_HEADER)
    (job.root / "dem.tif").symlink_to(secret)

    with pytest.raises(ConfigValidationError):
        job.resolve_input("dem.tif", loc=DEM_LOC)


# A capability never opens the network, so it never accepts a URL.
FETCHED_INPUTS = [
    pytest.param("https://data.geopf.fr/dem.tif", id="https"),
    pytest.param("s3://bucket/dem.tif", id="s3"),
    pytest.param("file://elsewhere/dem.tif", id="file on another host"),
]


@pytest.mark.parametrize("href", FETCHED_INPUTS)
def test_input_to_fetch_is_refused(tmp_path: Path, href: str) -> None:
    job = staged_job(tmp_path)
    with pytest.raises(ConfigValidationError) as excinfo:
        job.resolve_input(href, loc=DEM_LOC)
    assert excinfo.value.details[0]["pointer"] == DEM_POINTER


def test_empty_input_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError):
        staged_job(tmp_path).resolve_input("", loc=DEM_LOC)


def test_output_path_that_escapes_is_a_bug(tmp_path: Path) -> None:
    # Output paths come from a declaration this repository ships, so this is not bad input.
    with pytest.raises(ValueError, match="outside"):
        staged_job(tmp_path).resolve_output("../watershed.gpkg")


def test_relative_name_of_an_output(tmp_path: Path) -> None:
    job = staged_job(tmp_path)
    job.ensure_workspace()
    produced = job.outputs_dir / "watershed.gpkg"
    produced.write_bytes(b"")

    assert job.relative(produced) == "outputs/watershed.gpkg"
    with pytest.raises(ValueError):
        job.relative(tmp_path / "elsewhere.gpkg")
