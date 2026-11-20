"""The seal model shared by a run and a job, and the check of what it lists.

A seal lists artifacts with their digests. It must stay inside its directory and
it is strict JSON, so a number that is not finite is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.schema.seal import ArtifactRecord, Seal, render_document, verify_artifacts

SEALED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_entry_outside_the_directory(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.json"
    outside.write_text("{}\n", encoding="utf-8")
    seal = Seal(
        profile="job",
        sealed_at=SEALED_AT,
        artifacts=[ArtifactRecord(path="../elsewhere.json", role="output")],
    )

    assert verify_artifacts(tmp_path / "job", seal) == (
        "../elsewhere.json is sealed and lies outside " + str(tmp_path / "job"),
    )


def test_directory_hashed_by_the_callers_tree_digest(tmp_path: Path) -> None:
    store = tmp_path / "fields.zarr"
    store.mkdir()
    (store / "zarr.json").write_text("{}\n", encoding="utf-8")
    seal = Seal(
        profile="run",
        sealed_at=SEALED_AT,
        artifacts=[ArtifactRecord(path="fields.zarr", role="fields", sha256="abc")],
    )

    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "abc") == ()
    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "def") == (
        "fields.zarr does not hash to what the seal recorded",
    )
    assert verify_artifacts(tmp_path, seal) == ()


def test_number_that_is_not_finite_is_refused() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        render_document({"max_abs": float("inf")})
