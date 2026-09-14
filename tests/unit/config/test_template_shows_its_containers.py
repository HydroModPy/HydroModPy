"""A template has to show the tables a section is actually configured with.

The calibration section is the case that made this visible: its three
indispensable tables reached the reader as three dead comment lines, so a user
starting from ``hmp config template`` could not tell that a staged calibration
exists, let alone what a phase carries.
"""

from __future__ import annotations

import tomllib

import pytest

from hydromodpy.core.toml_io.generator import generate_toml


@pytest.fixture(scope="module")
def calibration_template() -> str:
    return generate_toml(modules=["calibration"])


def test_the_mapping_of_parameters_shows_one_entry(calibration_template: str) -> None:
    assert "# [calibration.parameters.<id>]" in calibration_template
    # The fields a parameter needs, not just the pointer line.
    assert "# bounds = " in calibration_template
    assert "# transform = " in calibration_template


def test_the_mapping_of_outputs_lists_every_support(calibration_template: str) -> None:
    assert "# [calibration.outputs.<id>]" in calibration_template
    for support in ("point", "boundary", "cell", "lake", "network"):
        assert f'support = "{support}"' in calibration_template


def test_the_staged_table_shows_what_a_phase_carries(calibration_template: str) -> None:
    assert "# [[calibration.phases]]" in calibration_template
    for field in ("name", "method", "parameters", "depends_on", "freeze_on_success"):
        assert f"# {field} = " in calibration_template


def test_the_staged_table_stays_commented_out(calibration_template: str) -> None:
    # Writing this table is what switches the runner to staged mode, so a
    # template must not turn it on for a reader who only wanted a starting
    # point.
    assert "\n[[calibration.phases]]" not in calibration_template
    parsed = tomllib.loads(calibration_template)
    assert "phases" not in parsed["calibration"]


def test_the_whole_template_stays_parseable() -> None:
    # Every skeleton is commented, so adding them must not cost validity.
    parsed = tomllib.loads(generate_toml())

    assert "workflow" in parsed
