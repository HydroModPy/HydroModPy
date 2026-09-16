"""A broken calibration TOML must be repairable from its own error message.

The people who run a calibration read TOML, not Python. A raw Pydantic
``ValidationError`` reaching the terminal gives them the model class names, the
nested field the validator happened to build, and a link to the pydantic error
reference: nothing that says which line of which file to open.

``core/toml_io/error_locator`` already maps a validation error back to a file and
a line. It had no call site on this path, so the config load raised raw.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.core.exceptions import ConfigError

_BROKEN = """\
[calibration]
method = "grid"
objective = "nse_lo"

[calibration.parameters.K]
bounds = [1e-8, 1e-2]
transform = "log"
"""


@pytest.fixture
def broken_toml(tmp_path: Path) -> Path:
    target = tmp_path / "calibration.toml"
    target.write_text(_BROKEN, encoding="utf-8")
    return target


def test_the_message_names_the_file_the_line_and_the_key(broken_toml: Path) -> None:
    """Everything needed to fix the file, without opening a .py."""
    with pytest.raises(ConfigError) as failure:
        load_toml_calibration(broken_toml)

    message = str(failure.value)
    assert broken_toml.name in message
    assert ":3:" in message, f"the line carrying the bad value is not named: {message}"
    assert "objective" in message


def test_the_message_does_not_send_the_reader_to_pydantic(broken_toml: Path) -> None:
    """A hydrogeologist has no use for the pydantic error reference."""
    with pytest.raises(ConfigError) as failure:
        load_toml_calibration(broken_toml)

    assert "errors.pydantic.dev" not in str(failure.value)


def test_a_valid_file_still_loads(tmp_path: Path) -> None:
    """The guard only shapes the failure; it does not touch the success path."""
    target = tmp_path / "calibration.toml"
    target.write_text(_BROKEN.replace("nse_lo", "nse_log"), encoding="utf-8")

    cfg, raw = load_toml_calibration(target)

    assert cfg.objective == "nse_log"
    assert "calibration" in raw
