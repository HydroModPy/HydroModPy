"""A finished directory is re-reported or refused, and never written into.

``job_id`` is a content address, so "the same request" and "the same id" are
one thing. What this module pins is the decision that follows from it, and the
one place the two channels of the boundary are allowed to differ: the document
on disk says what the **job** did, stdout says what **this invocation** did.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, render_document, write_document
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord, now
from hydromodpy.schema.job.reuse import REUSED_MEMBER, reuse_sealed_outcome, reused_outcome_text

JOB_ID = "sha256:" + "7" * 64
OTHER_JOB_ID = "sha256:" + "8" * 64


def _outcome(**overrides: object) -> JobOutcome:
    """A successful outcome carrying one artefact and one warning."""
    started = now()
    payload: dict[str, object] = {
        "job_id": JOB_ID,
        "process_id": "demo-delineate",
        "process_version": "1.2.3",
        "status": "successful",
        "exit_code": 0,
        "started_at": started,
        "finished_at": now(),
        "outputs": (
            OutputRecord(
                id="watershed_vector",
                path="outputs/watershed.gpkg",
                media_type="application/geopackage+sqlite3",
                bytes=17,
                sha256="a" * 64,
                extra={"hmp:conformsTo": ["GeoParquet-1.1"]},
            ),
        ),
        "warnings": ("outlet 'north' was not delineated: outside the DEM",),
    }
    payload.update(overrides)
    return JobOutcome(**payload)  # type: ignore[arg-type]


@pytest.fixture
def sealed(tmp_path: Path) -> JobDirectory:
    """A directory holding a finished job, sealed under :data:`JOB_ID`."""
    job = JobDirectory.create(tmp_path / "job")
    job.request_path.write_text("{}", encoding="utf-8")
    _outcome().write(job)
    write_document(job.manifest_path, {"schema": "hmp-manifest/v2", "job_id": JOB_ID})
    return job


class TestTheDecision:
    def test_the_same_id_comes_back_as_the_stored_outcome(self, sealed):
        reused = reuse_sealed_outcome(sealed, job_id=JOB_ID)

        assert reused.reused is True
        assert reused.exit_code == 0
        assert reused.status == "successful"
        assert reused.job_id == JOB_ID

    def test_everything_but_the_flag_is_what_the_job_wrote(self, sealed):
        stored = JobOutcome.from_document(read_document(sealed.outcome_path))

        reused = reuse_sealed_outcome(sealed, job_id=JOB_ID)

        assert stored.reused is False
        assert reused.to_document() == {**stored.to_document(), REUSED_MEMBER: True}

    def test_another_id_is_refused_rather_than_re_reported(self, sealed):
        with pytest.raises(JobUsageError) as caught:
            reuse_sealed_outcome(sealed, job_id=OTHER_JOB_ID)

        assert JOB_ID in str(caught.value)
        assert OTHER_JOB_ID in str(caught.value)

    def test_nothing_is_written_by_either_answer(self, sealed):
        before = {path.name: path.read_bytes() for path in sealed.root.iterdir() if path.is_file()}

        reuse_sealed_outcome(sealed, job_id=JOB_ID)
        with pytest.raises(JobUsageError):
            reuse_sealed_outcome(sealed, job_id=OTHER_JOB_ID)

        after = {path.name: path.read_bytes() for path in sealed.root.iterdir() if path.is_file()}
        assert after == before


class TestADirectoryThatCannotBeRead:
    """A sealed directory nobody here wrote is a usage error, never a crash."""

    def test_a_seal_that_is_not_json_is_a_usage_error(self, sealed):
        sealed.manifest_path.write_text("{oh dear", encoding="utf-8")

        with pytest.raises(JobUsageError, match="manifest.json"):
            reuse_sealed_outcome(sealed, job_id=JOB_ID)

    def test_a_seal_that_is_not_an_object_is_a_usage_error(self, sealed):
        sealed.manifest_path.write_text("[]", encoding="utf-8")

        with pytest.raises(JobUsageError, match="not a JSON object"):
            reuse_sealed_outcome(sealed, job_id=JOB_ID)

    def test_an_outcome_the_seal_matches_but_nobody_can_parse_is_a_usage_error(self, sealed):
        document = read_document(sealed.outcome_path)
        del document["status"]
        write_document(sealed.outcome_path, document)

        with pytest.raises(JobUsageError, match="cannot be read as an outcome"):
            reuse_sealed_outcome(sealed, job_id=JOB_ID)

    def test_a_status_a_capability_never_writes_is_refused(self, sealed):
        """``accepted`` and ``running`` describe a job before the process starts.

        Left to the self-consistency check alone, ``accepted`` exiting 130 would
        have been read as a dismissed job and served as one.
        """
        document = read_document(sealed.outcome_path)
        document["status"] = "accepted"
        document["exit_code"] = 130
        write_document(sealed.outcome_path, document)

        with pytest.raises(JobUsageError, match="cannot be read as an outcome"):
            reuse_sealed_outcome(sealed, job_id=JOB_ID)


class TestTheBytesOnStdout:
    def test_the_text_is_the_file_with_one_member_changed(self, sealed):
        on_disk = sealed.outcome_path.read_text(encoding="utf-8")

        text = reused_outcome_text(sealed)

        assert json.loads(text) == {**json.loads(on_disk), REUSED_MEMBER: True}
        differing = [
            (before, after)
            for before, after in zip(on_disk.splitlines(), text.splitlines(), strict=True)
            if before != after
        ]
        assert len(differing) == 1
        assert f'"{REUSED_MEMBER}"' in differing[0][0]

    def test_the_file_itself_is_left_alone(self, sealed):
        before = sealed.outcome_path.read_bytes()

        reused_outcome_text(sealed)

        assert sealed.outcome_path.read_bytes() == before


class TestReadingAnOutcomeBack:
    def test_a_written_outcome_reads_back_into_itself(self):
        original = _outcome()

        assert JobOutcome.from_document(original.to_document()) == original

    def test_an_extra_member_of_an_output_record_survives_the_round_trip(self, sealed):
        record = JobOutcome.from_document(read_document(sealed.outcome_path)).outputs[0]

        assert dict(record.extra) == {"hmp:conformsTo": ["GeoParquet-1.1"]}

    def test_the_stored_duration_is_derived_again_and_not_trusted(self, sealed):
        """A number that can disagree with its own inputs eventually does."""
        document = read_document(sealed.outcome_path)
        document["duration_s"] = 9999.0

        assert JobOutcome.from_document(document).duration_s < 9999.0

    def test_the_rendering_of_a_document_is_stable_through_a_round_trip(self, sealed):
        """What makes the one-member substitution of stdout safe to promise."""
        on_disk = sealed.outcome_path.read_text(encoding="utf-8")

        assert render_document(read_document(sealed.outcome_path)) == on_disk
