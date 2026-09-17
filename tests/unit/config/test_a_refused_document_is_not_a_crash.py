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

from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

WORKSPACE = """\
[workspace]
project_root = "{root}"

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


def test_the_baseline_document_loads(tmp_path: Path) -> None:
    """Guards every sweep below: a baseline that stopped loading would make each
    case pass on a fault it did not inject."""
    HydroModPyConfig.from_toml(_write(tmp_path, "", head=LOADABLE))


def _refusal(path: Path) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)
    return excinfo.value


# ---------------------------------------------------------------------------
# The exit code
# ---------------------------------------------------------------------------


def test_an_unknown_key_reaches_the_config_exit_code(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[geographic]\ndem_correction_type = 'dinf'\n"))
    assert exit_code_for(error) == EXIT_CONFIG


def test_a_missing_project_root_reaches_the_config_exit_code(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[simulation]\nname = 'probe'\n", head=""))
    assert exit_code_for(error) == EXIT_CONFIG


def test_a_retired_section_reaches_the_config_exit_code(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[modflow]\nexe_name = 'mfnwt'\n"))
    assert exit_code_for(error) == EXIT_CONFIG


def test_an_unknown_top_level_section_reaches_the_config_exit_code(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[not_a_section]\nx = 1\n"))
    assert exit_code_for(error) == EXIT_CONFIG


def test_a_bad_workflow_mode_reaches_the_config_exit_code(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[workflow]\nmode = 'not_a_mode'\n"))
    assert exit_code_for(error) == EXIT_CONFIG


def test_a_workspace_that_is_not_a_table_reaches_the_config_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text("workspace = 3\n", encoding="utf-8")
    assert exit_code_for(_refusal(path)) == EXIT_CONFIG


# ---------------------------------------------------------------------------
# The pointer
# ---------------------------------------------------------------------------


def test_the_pointer_names_the_key_the_document_wrote(tmp_path: Path) -> None:
    """A section validates against its own model, so Pydantic reports a
    section-relative ``loc``. Emitted as-is the pointer would name a root key
    that does not exist, and a front end would highlight nothing."""
    error = _refusal(_write(tmp_path, "[geographic]\ndem_correction_type = 'dinf'\n"))
    pointers = [entry["pointer"] for entry in error.details]
    assert pointers == ["/geographic/dem_correction_type"]


def test_the_pointer_of_a_retired_section_names_that_section(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[modflow]\nexe_name = 'mfnwt'\n"))
    assert [entry["pointer"] for entry in error.details] == ["/modflow"]


def test_every_unknown_section_gets_its_own_pointer(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[zulu]\nx = 1\n\n[alpha]\ny = 2\n"))
    assert sorted(entry["pointer"] for entry in error.details) == ["/alpha", "/zulu"]


def test_a_missing_project_root_points_at_the_key_it_wants(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[simulation]\nname = 'probe'\n", head=""))
    assert [entry["pointer"] for entry in error.details] == ["/workspace/project_root"]


def test_the_detail_carries_the_line_when_the_source_is_readable(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[geographic]\ndem_correction_type = 'dinf'\n"))
    (entry,) = error.details
    line = entry["line"]
    assert (
        Path(error.source)
        .read_text(encoding="utf-8")
        .splitlines()[line - 1]
        .startswith("dem_correction_type")
    )


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


def test_a_typed_error_without_details_omits_the_member() -> None:
    payload = ConfigValidationError("nothing structured to say").to_dict()
    assert "details" not in payload
    assert "source" not in payload
    assert payload["detail"] == "nothing structured to say"


# ---------------------------------------------------------------------------
# The rule, swept rather than sampled
# ---------------------------------------------------------------------------

MALFORMED = {
    "unknown key in a section": "[flow]\ntypo_runtime = true\n",
    "unknown key in a nested model": "[modflow6.sgrid]\ntypo = 1\n",
    "a section that is a scalar": "flow = 3\n",
    "a value outside its literal": "[flow]\nflow_regime = 'not_a_regime'\n",
    "a retired section": "[modflow]\nexe_name = 'mfnwt'\n",
    "a section that never existed": "[not_a_section]\nx = 1\n",
    "a nested table that is a scalar": "[flow]\nsinks_sources = 3\n",
    "a protocol nobody registered": "[calibration]\nprotocol = 'nope'\n",
    "an inference mode that is not one": "[data]\ninference_mode = 'nope'\n",
    "a sub-section that is a scalar": "[analysis]\nbatch = 3\n",
}


@pytest.mark.parametrize("body", MALFORMED.values(), ids=list(MALFORMED))
def test_every_shape_of_bad_document_reaches_the_same_exit_code(tmp_path: Path, body: str) -> None:
    """Sampled once per shape, because the shapes fail on different code paths.

    A Pydantic fault, a refusal written by hand before the model runs, and a
    ``ValueError`` from a section loader are three different mechanisms. Only the
    first was typed; the other two reached exit code 1, which says "a bug in
    HydroModPy" to whoever ran it.
    """
    assert exit_code_for(_refusal(_write(tmp_path, body, head=LOADABLE))) == EXIT_CONFIG


@pytest.mark.parametrize("body", MALFORMED.values(), ids=list(MALFORMED))
def test_every_refusal_points_at_something(tmp_path: Path, body: str) -> None:
    error = _refusal(_write(tmp_path, body, head=LOADABLE))
    assert error.details
    for entry in error.details:
        assert entry["pointer"].startswith("/")
        assert entry["msg"]


def test_the_refused_value_is_named_by_the_message(tmp_path: Path) -> None:
    """A message that says what the field should be without saying what it got
    makes the reader diff their own file against a sentence."""
    error = _refusal(_write(tmp_path, "[flow]\nflow_regime = 'not_a_regime'\n", head=LOADABLE))
    assert "not_a_regime" in str(error)


def test_a_value_too_large_to_help_is_not_repeated_back(tmp_path: Path) -> None:
    long_value = "x" * 400
    error = _refusal(_write(tmp_path, f"[flow]\nflow_regime = '{long_value}'\n", head=LOADABLE))
    assert long_value not in str(error)
    assert "flow.flow_regime" in str(error)


# ---------------------------------------------------------------------------
# What the adversarial gate of F4a found
# ---------------------------------------------------------------------------


def test_the_pointer_does_not_invent_the_union_tag(tmp_path: Path) -> None:
    """Pydantic names the variant it selected; the document never wrote it.

    ``[flow.ic]`` is a flattened discriminated union: ``type`` and the variant's
    own fields are siblings in one table. Pydantic reports the fault at
    ``("flow", "ic", "spinup_cyclic", "max_cycles")``. A pointer built from that
    addresses a table that does not exist, and a front end resolving it
    highlights nothing. The tag is the idiom the whole schema uses for every
    "kind" field, so this is not one field, it is fifteen unions.
    """
    error = _refusal(
        _write(
            tmp_path,
            "[flow.ic]\ntype = 'spinup_cyclic'\nmax_cycles = 'not_an_int'\n",
            head=LOADABLE,
        )
    )
    (entry,) = error.details
    assert entry["pointer"] == "/flow/ic/max_cycles"
    assert entry["loc"] == "flow.ic.max_cycles"


def test_a_missing_key_still_points_at_where_it_belongs(tmp_path: Path) -> None:
    """The counterweight to the test above: a segment the document lacks is
    dropped only when the next one resolves in its place. A ``missing`` fault
    names a key that is by definition absent, and its pointer must survive."""
    error = _refusal(_write(tmp_path, "[simulation]\nname = 'probe'\n", head=""))
    assert [entry["pointer"] for entry in error.details] == ["/workspace/project_root"]


def test_a_protocol_option_is_pointed_at_and_typed(tmp_path: Path) -> None:
    """A registered protocol given a bad option validates its own Pydantic model.

    ``pydantic.ValidationError`` is a subclass of ``ValueError``, so a lone
    ``except ValueError`` around the expander swallowed it: the pointer
    collapsed to ``/calibration``, the type was reported as ``value_error``
    where Pydantic had said ``literal_error``, and the message became a raw
    Pydantic dump carrying a pydantic.dev URL.
    """
    error = _refusal(
        _write(
            tmp_path,
            """
            [calibration.protocol]
            name = "matching_hydrographic_network"
            steady_metric = "not_a_real_metric"

            [calibration.parameters.K]
            kind = "log_uniform"
            lower = 1e-6
            upper = 1e-2
            """,
            head=LOADABLE,
        )
    )
    (entry,) = error.details
    assert entry["pointer"] == "/calibration/protocol/steady_metric"
    assert entry["type"] == "literal_error"
    assert "errors.pydantic.dev" not in str(error)
    assert "not_a_real_metric" in str(error)


def test_an_unregistered_protocol_keeps_its_own_refusal(tmp_path: Path) -> None:
    """The neighbour of the case above, and it must not be typed the same way:
    an unknown name is refused by the registry itself, not by a model."""
    error = _refusal(_write(tmp_path, "[calibration]\nprotocol = 'nope'\n", head=LOADABLE))
    (entry,) = error.details
    assert entry["pointer"] == "/calibration"
    assert entry["type"] == "value_error"
