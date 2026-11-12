"""The report of a chain reads under its version window like a job document."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY
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
