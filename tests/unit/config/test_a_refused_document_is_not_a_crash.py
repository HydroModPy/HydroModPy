"""A document this process refuses is told apart from a bug in this process.

Every refusal of a configuration document leaves the config boundary as a
:class:`~hydromodpy.core.exceptions.ConfigValidationError`, which the CLI maps to
exit code 14. Before this, ``from_toml`` flattened Pydantic's structured failure
into a bare ``ValueError``, which falls through ``exit_code_for`` to exit code 1
— the code that means "a bug, report it". A caller outside this process could not
tell a typo in its own TOML from a crash in ours.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.cli.exit_codes import EXIT_CONFIG, exit_code_for
from hydromodpy.config.config_migration import PRERELEASE_FORMS
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

WORKSPACE = """\
[workspace]

"""

# The smallest document this repository loads. A malformed one is this plus one
# fault, so the refusal under test is the only thing wrong with it.
LOADABLE = (
    WORKSPACE
    + """\
[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

"""
)


def _write(tmp_path: Path, body: str, *, head: str = WORKSPACE) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(head.format(root=tmp_path.as_posix()) + textwrap.dedent(body), encoding="utf-8")
    return path


def _refusal(path: Path) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)
    return excinfo.value


# ---------------------------------------------------------------------------
# The exit code
# ---------------------------------------------------------------------------


def test_a_workspace_that_is_not_a_table_reaches_the_config_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(tomlkit.dumps({"workspace": 3}), encoding="utf-8")
    assert exit_code_for(_refusal(path)) == EXIT_CONFIG


def _written_by_a_pre_release(path: str) -> str:
    """Return a TOML text that writes the form of *path* of ``prerelease_forms.txt``."""
    assert path in {form.path for form in PRERELEASE_FORMS}
    document: dict = {"x": 1}
    for part in reversed(path.split(".")):
        document = {"x" if part == "{*}" else part: document}
    return tomlkit.dumps(document)


# ---------------------------------------------------------------------------
# The pointer
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The payload a caller outside this process reads
# ---------------------------------------------------------------------------


def test_the_refusal_renders_as_a_typed_problem_object(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[geographic]\ndem_correction_type = 'dinf'\n"))
    payload = error.to_dict()
    assert payload["type"] == "urn:hmp:error:HMPY.E101"
    assert payload["code"] == "HMPY.E101"
    assert payload["title"] == "The configuration document failed validation."
    assert payload["source"] == str(error.source)
    assert payload["details"][0]["pointer"] == "/geographic/dem_correction_type"
    json.dumps(payload)


def test_a_refusal_raised_before_the_model_runs_omits_no_details(tmp_path: Path) -> None:
    """Every refusal of this boundary carries at least one pointed fault.

    ``details`` is omitted rather than emitted empty, so an absent member means
    "nothing to point at", never "the list happens to be empty".
    """
    error = _refusal(_write(tmp_path, "[modflow]\nexe_name = 'mfnwt'\n"))
    assert error.to_dict()["details"]


# ---------------------------------------------------------------------------
# The rule, swept rather than sampled
# ---------------------------------------------------------------------------

MALFORMED = {
    "unknown key in a section": "[flow]\ntypo_runtime = true\n",
    "unknown key in a nested model": "[solver.modflow6.sgrid]\ntypo = 1\n",
    "a section that is a scalar": tomlkit.dumps({"flow": 3}),
    "a value outside its literal": "[flow]\nflow_regime = 'not_a_regime'\n",
    "a retired section": "[modflow]\nexe_name = 'mfnwt'\n",
    "a section that never existed": "[not_a_section]\nx = 1\n",
    "a nested table that is a scalar": "[flow]\nsinks_sources = 3\n",
    "a protocol nobody registered": "[calibration]\nprotocol = 'nope'\n",
    "an inference mode that is not one": "[data]\ninference_mode = 'nope'\n",
    "a sub-section that is a scalar": "[mesh]\nfamilies = 3\n",
    "a retired root section": "[analysis]\nbatch = 3\n",
}


@pytest.mark.parametrize("body", MALFORMED.values(), ids=list(MALFORMED))
def test_every_refusal_points_at_something(tmp_path: Path, body: str) -> None:
    error = _refusal(_write(tmp_path, body, head=LOADABLE))
    assert error.details
    for entry in error.details:
        assert entry["pointer"].startswith("/")
        assert entry["msg"]


# ---------------------------------------------------------------------------
# What the adversarial gate of F4a found
# ---------------------------------------------------------------------------


def test_the_pointer_does_not_invent_the_union_tag(tmp_path: Path) -> None:
    """Pydantic names the variant it selected; the document never wrote it.

    ``[flow.ic]`` is a flattened discriminated union: ``kind`` and the variant's
    own fields are siblings in one table. Pydantic reports the fault at
    ``("flow", "ic", "spinup_cyclic", "max_cycles")``. A pointer built from that
    addresses a table that does not exist, and a front end resolving it
    highlights nothing. The tag is the idiom the whole schema uses for every
    "kind" field, so this is not one field, it is fifteen unions.
    """
    error = _refusal(
        _write(
            tmp_path,
            "[flow.ic]\nkind = 'spinup_cyclic'\nmax_cycles = 'not_an_int'\n",
            head=LOADABLE,
        )
    )
    (entry,) = error.details
    assert entry["pointer"] == "/flow/ic/max_cycles"
    assert entry["loc"] == "flow.ic.max_cycles"
