"""The job directory is the only thing a capability process may touch.

Two facts are asserted here, because everything an orchestrator trusts rests
on them: a path the request declares relative is resolved inside the job
directory or refused, and a job directory that cannot be used at all is
refused as a usage error, which exits 2 rather than 1. A shim retries a usage
error by fixing its own call, never by running the job again.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_USAGE, exit_code_for
from hydromodpy.core.exceptions import ConfigValidationError, JobUsageError
from hydromodpy.schema.job import ALLOWED_JOB_ENTRIES, JobDirectory
from hydromodpy.schema.job.layout import JOB_WRITE_ORDER, REQUEST_FILENAME


def _staged(tmp_path: Path) -> JobDirectory:
    """A job directory as a caller hands it over: one file, nothing else."""
    root = tmp_path / "job_4711"
    root.mkdir()
    (root / REQUEST_FILENAME).write_text("{}", encoding="utf-8")
    return JobDirectory.open(root)


def test_a_missing_job_directory_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(JobUsageError) as excinfo:
        JobDirectory.open(tmp_path / "absent")
    assert exit_code_for(excinfo.value) == EXIT_USAGE


def test_a_job_directory_without_a_request_is_a_usage_error(tmp_path: Path) -> None:
    root = tmp_path / "job_4712"
    root.mkdir()
    with pytest.raises(JobUsageError) as excinfo:
        JobDirectory.open(root)
    assert REQUEST_FILENAME in str(excinfo.value)
    assert exit_code_for(excinfo.value) == EXIT_USAGE


def test_the_root_is_resolved_once_so_containment_is_decidable(tmp_path: Path) -> None:
    """A symlinked root would otherwise make every containment check disagree."""
    real = tmp_path / "real"
    real.mkdir()
    (real / REQUEST_FILENAME).write_text("{}", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    job = JobDirectory.open(link)

    assert job.root == real.resolve()
    assert job.contains(job.outputs_dir / "watershed.gpkg")


def test_every_document_of_the_job_is_named_from_the_root(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    for path in (
        job.request_path,
        job.inputset_path,
        job.provenance_path,
        job.outcome_path,
        job.manifest_path,
        job.outputs_dir,
        job.logs_dir,
        job.log_path,
        job.progress_path,
    ):
        assert job.contains(path)
    assert not job.is_sealed


def test_the_top_level_names_a_job_uses_are_the_allowed_ones(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    job.ensure_workspace()
    job.outcome_path.write_text("{}", encoding="utf-8")
    job.progress_path.write_text("", encoding="utf-8")

    entries = {entry.name for entry in job.root.iterdir()}

    assert entries <= ALLOWED_JOB_ENTRIES
    assert set(JOB_WRITE_ORDER) <= ALLOWED_JOB_ENTRIES


def test_a_relative_input_is_resolved_inside_the_job(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    (job.root / "inputs").mkdir()
    dem = job.root / "inputs" / "dem.tif"
    dem.write_bytes(b"II*\x00")

    assert job.resolve_input("inputs/dem.tif", loc=("inputs", "dem", "href")) == dem


def test_an_absolute_input_is_read_where_the_caller_staged_it(tmp_path: Path) -> None:
    """An orchestrator stages one DEM and points several jobs at it."""
    job = _staged(tmp_path)
    shared = tmp_path / "shared" / "dem.tif"
    shared.parent.mkdir()
    shared.write_bytes(b"II*\x00")

    resolved = job.resolve_input(str(shared), loc=("inputs", "dem", "href"))

    assert resolved == shared.resolve()
    assert not job.contains(resolved)


def test_a_relative_input_that_walks_out_is_refused_and_pointed_at(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    secret = tmp_path / "secret.tif"
    secret.write_bytes(b"II*\x00")

    with pytest.raises(ConfigValidationError) as excinfo:
        job.resolve_input("../secret.tif", loc=("inputs", "dem", "href"))

    refusal = excinfo.value
    assert exit_code_for(refusal) == EXIT_CONFIG
    assert refusal.details[0]["pointer"] == "/inputs/dem/href"


def test_a_symlink_inside_the_job_that_points_out_is_refused(tmp_path: Path) -> None:
    """Containment is decided on the resolved path, not on the spelling."""
    job = _staged(tmp_path)
    secret = tmp_path / "secret.tif"
    secret.write_bytes(b"II*\x00")
    (job.root / "dem.tif").symlink_to(secret)

    with pytest.raises(ConfigValidationError):
        job.resolve_input("dem.tif", loc=("inputs", "dem", "href"))


@pytest.mark.parametrize(
    "href",
    ["https://data.geopf.fr/dem.tif", "s3://bucket/dem.tif", "file://elsewhere/dem.tif"],
)
def test_an_input_this_process_would_have_to_fetch_is_refused(tmp_path: Path, href: str) -> None:
    """A capability never opens the network, so it never accepts a URL."""
    job = _staged(tmp_path)
    with pytest.raises(ConfigValidationError) as excinfo:
        job.resolve_input(href, loc=("inputs", "dem", "href"))
    assert excinfo.value.details[0]["pointer"] == "/inputs/dem/href"


def test_a_local_file_uri_names_the_same_path_as_the_path_itself(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    dem = tmp_path / "shared dem.tif"
    dem.write_bytes(b"II*\x00")

    from_uri = job.resolve_input(dem.as_uri(), loc=("inputs", "dem", "href"))

    assert from_uri == dem.resolve()


def test_an_empty_input_path_is_refused(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    with pytest.raises(ConfigValidationError):
        job.resolve_input("", loc=("inputs", "dem", "href"))


def test_an_output_path_that_escapes_is_a_bug_here_not_bad_input(tmp_path: Path) -> None:
    """Output paths come from a declaration this repository ships."""
    job = _staged(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        job.resolve_output("../watershed.gpkg")


def test_a_path_is_rendered_the_way_the_seal_names_it(tmp_path: Path) -> None:
    job = _staged(tmp_path)
    job.ensure_workspace()
    produced = job.outputs_dir / "watershed.gpkg"
    produced.write_bytes(b"")

    assert job.relative(produced) == "outputs/watershed.gpkg"
    with pytest.raises(ValueError):
        job.relative(tmp_path / "elsewhere.gpkg")


def test_created_directories_are_the_two_a_running_job_appends_into(tmp_path: Path) -> None:
    job = JobDirectory.create(tmp_path / "job_4713")
    job.ensure_workspace()

    assert job.outputs_dir.is_dir()
    assert job.logs_dir.is_dir()
    assert job.root == (tmp_path / "job_4713").resolve()
    assert os.path.realpath(job.root) == str(job.root)
