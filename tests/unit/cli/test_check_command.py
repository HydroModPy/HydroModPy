"""``hmp check``: the wiring of the command to the verb ``check``."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers.cli_runner import CliRunner

pytestmark = pytest.mark.fast


def test_a_missing_file_exits_not_found(tmp_path: Path) -> None:
    result = CliRunner().invoke(["check", str(tmp_path / "gone.toml")])

    assert result.exit_code == 10
    assert "File not found" in result.stderr
