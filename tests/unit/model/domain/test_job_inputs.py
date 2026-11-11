"""The checks a capability job makes on its input files, and the hashes of its outputs."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.exceptions import DataContractViolation, JobInputNotFoundError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.model.domain import job_inputs
from hydromodpy.model.domain.capability import DOMAIN_BUILD
from hydromodpy.schema.job.directory import JobDirectory

pytestmark = pytest.mark.fast


def test_a_pinned_digest_is_read_in_any_case_and_other_bytes_are_refused():
    refuse = job_inputs.refuse_a_file_that_is_not_the_one_asked_for
    refuse("AB12", digest="ab12", href="dem.tif", member="dem")
    match = "'dem.tif' hashes to ab12 and the request pinned cd34"
    with pytest.raises(DataContractViolation, match=match):
        refuse("CD34", digest="ab12", href="dem.tif", member="dem")


@pytest.mark.parametrize("href", ["absent.tif", "folder"])
def test_an_input_file_that_is_not_there_is_refused_as_not_found(tmp_path, href):
    job = JobDirectory.create(tmp_path / "job")
    (job.root / "folder").mkdir()
    job.request_path.write_text("{}", encoding="utf-8")

    with pytest.raises(JobInputNotFoundError, match=f"input dem names '{href}', and .+ is not a file") as caught:  # fmt: skip
        job_inputs.resolve_input_file(job, href, member="dem")

    assert (caught.value.code, exit_code_for(caught.value)) == ("HMPY.E211", EXIT_NOT_FOUND)
    assert job_inputs.resolve_input_file(job, "request.json", member="dem") == job.request_path


@pytest.mark.parametrize(
    ("opened", "match"),
    [
        (None, "input dem 'dem.tif' cannot be opened as a raster"),
        (PermissionError("no access"), "input dem 'dem.tif' cannot be read: no access"),
        (nullcontext(SimpleNamespace(count=0)), r"carries 0 band\(s\); an elevation model carries at least one"),
    ],
    ids=["prose", "unreadable", "no_band"],
)  # fmt: skip
def test_an_input_that_is_not_a_raster_with_a_band_is_refused(tmp_path, monkeypatch, opened, match):
    path = tmp_path / "dem.tif"
    path.write_text("this is prose", encoding="utf-8")
    if opened is not None:
        monkeypatch.setattr(job_inputs.rasterio, "open", Mock(side_effect=[opened]))

    with pytest.raises(DataContractViolation, match=match):
        job_inputs.read_raster_input("dem.tif", path=path, member="dem", read=lambda source: None)


def test_every_declared_output_but_the_outcome_is_hashed_in_declaration_order(tmp_path):
    job = JobDirectory.create(tmp_path / "job")
    job.ensure_workspace()
    declared = [output for output in DOMAIN_BUILD.outputs if output.path != "outcome.json"]
    for output in declared:
        job.resolve_output(output.path).write_text(output.id, encoding="utf-8")

    records = job_inputs.output_records(job, DOMAIN_BUILD)

    assert [(r.id, r.path, r.media_type, r.extra, (r.sha256, r.bytes)) for r in records] == [
        (o.id, o.path, o.media_type, o.extra, sha256_and_size(job.resolve_output(o.path)))
        for o in declared
    ]
