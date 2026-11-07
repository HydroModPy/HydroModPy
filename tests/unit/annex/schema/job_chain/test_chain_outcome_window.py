"""The report of a chain reads under its version window like a job document."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import FOREIGN_REMEDY, NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.schema.job.documents import read_versioned
from hydromodpy_annex.schema.job_chain.chain import (
    CHAIN_OUTCOME_FILENAME,
    CHAIN_OUTCOME_VERSIONS,
    read_chain_outcome,
)

FUTURE_KEY = "added_by_a_later_version"
WRITER = "2.0.0a1"


def _shifted(version: str, step: int) -> str:
    """Return the schema id ``step`` versions away from ``version``."""
    match = re.search(r"(\d+)$", version)
    assert match is not None, version
    return f"{version[: match.start()]}{int(match.group(1)) + step}"


def test_the_report_of_a_chain_inside_its_window_reads_with_a_future_key(
    tmp_path: Path,
) -> None:
    target = tmp_path / "document.json"
    target.write_text(
        json.dumps({"schema": CHAIN_OUTCOME_VERSIONS.current, FUTURE_KEY: 1}), encoding="utf-8"
    )

    assert read_versioned(target, CHAIN_OUTCOME_VERSIONS)[FUTURE_KEY] == 1


def test_the_report_of_a_chain_outside_its_window_is_refused_by_what_it_is(
    tmp_path: Path,
) -> None:
    target = tmp_path / "document.json"
    (tmp_path / "provenance.json").write_text(
        json.dumps({"tool": {"version": WRITER}}), encoding="utf-8"
    )
    current = str(CHAIN_OUTCOME_VERSIONS.current)
    for payload, remedy in (
        ({"schema": _shifted(current, 1)}, NEWER_REMEDY),
        ({"schema": _shifted(current, -1)}, OLDER_REMEDY),
        ({}, OLDER_REMEDY),
        ([], OLDER_REMEDY),
        ({"schema": "hmp-another/v1"}, FOREIGN_REMEDY),
    ):
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SchemaVersionMismatchError) as refused:
            read_versioned(target, CHAIN_OUTCOME_VERSIONS)
        assert remedy in str(refused.value)
        assert f"written by HydroModPy {WRITER}" in str(refused.value)


def test_the_report_of_a_chain_reads_under_its_window(tmp_path: Path) -> None:
    target = tmp_path / CHAIN_OUTCOME_FILENAME
    target.write_text(json.dumps({"schema": CHAIN_OUTCOME_VERSIONS.current}), encoding="utf-8")
    assert read_chain_outcome(tmp_path)["schema"] == CHAIN_OUTCOME_VERSIONS.current

    target.write_text(
        json.dumps({"schema": _shifted(str(CHAIN_OUTCOME_VERSIONS.current), 1)}),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatchError, match=NEWER_REMEDY):
        read_chain_outcome(tmp_path)
