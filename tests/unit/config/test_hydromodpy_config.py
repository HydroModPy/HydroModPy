"""Loading a configuration document refuses what the check refuses, with a typed error.

Every refusal of a document leaves the config boundary as a ``ConfigValidationError``, which the
CLI maps to exit code 14, so a typo in a TOML is told apart from a crash (exit code 1). The
refusal points at the key that is wrong, and ``check(partial=False)`` gives the same pointer.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.cli.exit_codes import EXIT_CONFIG, exit_code_for
from hydromodpy.config.check import check
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import ConfigValidationError, HydroModPyError
from hydromodpy.core.state.result_dirs import is_sealed_run_config
from hydromodpy.core.toml_io.loader import config_base_dir, merge_toml_chain, read_toml_chain

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = "[workspace]\n\n"

# The smallest document this repository loads. A malformed one is this plus one fault,
# so the refusal under test is the only thing wrong with it.
LOADABLE = (
    WORKSPACE + '[workflow]\nmode = "simulation"\n\n[geographic]\nsource_mode = "synthetic"\n\n'
)

MALFORMED = [
    pytest.param("[flow]\ntypo_runtime = true\n", id="unknown key in a section"),
    pytest.param("[solver.modflow6.sgrid]\ntypo = 1\n", id="unknown key in a nested model"),
    pytest.param(tomlkit.dumps({"flow": 3}), id="a section that is a scalar"),
    pytest.param("[flow]\nflow_regime = 'not_a_regime'\n", id="a value outside its literal"),
    pytest.param("[modflow]\nexe_name = 'mfnwt'\n", id="a retired section"),
    pytest.param("[not_a_section]\nx = 1\n", id="a section that never existed"),
    pytest.param("[flow]\nsinks_sources = 3\n", id="a nested table that is a scalar"),
    pytest.param("[calibration]\nprotocol = 'nope'\n", id="a protocol nobody registered"),
    pytest.param("[data]\ninference_mode = 'nope'\n", id="an inference mode that is not one"),
    pytest.param("[mesh]\nfamilies = 3\n", id="a sub-section that is a scalar"),
    pytest.param("[analysis]\nbatch = 3\n", id="a retired root section"),
]


def _write(tmp_path: Path, body: str, *, head: str = WORKSPACE) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(head.format(root=tmp_path.as_posix()) + textwrap.dedent(body), encoding="utf-8")
    return path


def _refusal(path: Path) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)
    return excinfo.value


def _as_written(path: Path) -> dict[str, Any]:
    return merge_toml_chain(read_toml_chain(path, root=None), root=None)


def _errors(found: list[Diagnostic]) -> list[Diagnostic]:
    return [diagnostic for diagnostic in found if diagnostic.severity != "warning"]


def _seen(found: list[Diagnostic]) -> list[tuple[str, str, str]]:
    return [(diagnostic.path, diagnostic.code, diagnostic.severity) for diagnostic in found]


def _holds(document: Any, loc: list[str | int]) -> bool:
    """Whether *document* holds a value at *loc*, a key or an index at each step."""
    for part in loc:
        if isinstance(document, dict) and part in document:
            document = document[part]
        elif isinstance(document, list) and isinstance(part, int) and part < len(document):
            document = document[part]
        else:
            return False
    return True


def _same_refusal(path: Path) -> None:
    """Hold the loader and ``check(partial=False)`` to the same answer on one file."""
    try:
        document = _as_written(path)
    except (ValueError, OSError):
        return  # an unreadable file or chain is refused before any section is read
    try:
        base = config_base_dir(path)
    except HydroModPyError as exc:
        # A file that anchors no project root is refused before it is validated.
        with pytest.raises(type(exc)):
            HydroModPyConfig.from_toml(path)
        return
    found = _errors(check(document, partial=False, base=base))
    if is_sealed_run_config(path):
        # The loader reads the frozen config of a run in silence under the old names it
        # recorded, unless a pre-release of 2.0 wrote them. A document checked as written
        # is not such a copy, so the old forms the check refuses in it are compared only
        # with a refusal of the pre-release forms.
        written = [item for item in found if item.code not in {"old_key", "retired_key"}]
    else:
        written = found
    try:
        HydroModPyConfig.from_toml(path)
    except HydroModPyError as error:
        assert found, f"{path}: the loader refuses ({error}) and the check finds nothing"
        prerelease = bool(error.details) and all(
            item.get("type") == "prerelease_form" for item in error.details
        )
        found = found if prerelease else written
        if prerelease:
            # A chain is refused layer by layer and the check reads it merged: the
            # check names every key of the refusal that the merged document holds.
            held = {item["pointer"] for item in error.details if _holds(document, item["loc"])}
            assert held, (path, error.details)
            assert {item.pointer for item in found if item.code == "retired_key"} >= held, (
                path,
                _seen(found),
                error.details,
            )
        elif error.details:
            assert found[0].pointer == error.details[0]["pointer"], (
                path,
                _seen(found),
                error.details[0],
            )
        if not isinstance(error, ConfigValidationError):
            assert found[0].code == "incompatible", (path, type(error), _seen(found))
        return
    assert written == [], f"{path}: the loader reads it and the check refuses {_seen(found)}"


def _documents_of_the_tree() -> list[Path]:
    corpus = sorted((REPO / "tests" / "unit" / "config" / "corpus").rglob("*.toml"))
    examples = sorted((REPO / "examples" / "projects").rglob("*.toml"))
    return [*corpus, *examples]


def test_workspace_that_is_not_a_table_gives_the_config_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(tomlkit.dumps({"workspace": 3}), encoding="utf-8")
    assert exit_code_for(_refusal(path)) == EXIT_CONFIG


def test_refusal_renders_as_a_typed_problem_object(tmp_path: Path) -> None:
    error = _refusal(_write(tmp_path, "[geographic]\ndem_correction_type = 'dinf'\n"))
    payload = error.to_dict()
    assert payload["type"] == "urn:hmp:error:HMPY.E101"
    assert payload["code"] == "HMPY.E101"
    assert payload["title"] == "The configuration document failed validation."
    assert payload["source"] == str(error.source)
    assert payload["details"][0]["pointer"] == "/geographic/dem_correction_type"
    json.dumps(payload)


def test_refusal_before_the_model_runs_keeps_its_details(tmp_path: Path) -> None:
    # `details` is omitted rather than emitted empty, so an absent member means
    # "nothing to point at", never "the list happens to be empty".
    error = _refusal(_write(tmp_path, "[modflow]\nexe_name = 'mfnwt'\n"))
    assert error.to_dict()["details"]


@pytest.mark.parametrize("body", MALFORMED)
def test_every_refusal_points_at_something(tmp_path: Path, body: str) -> None:
    error = _refusal(_write(tmp_path, body, head=LOADABLE))
    assert error.details
    for entry in error.details:
        assert entry["pointer"].startswith("/")
        assert entry["msg"]


def test_pointer_does_not_invent_the_union_tag(tmp_path: Path) -> None:
    # [flow.ic] is a flattened discriminated union: kind and the variant's own fields are
    # siblings in one table. Pydantic reports the fault at ("flow", "ic", "spinup_cyclic",
    # "max_cycles"), a table the document never wrote.
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


def test_document_with_two_faulty_sections_is_refused_with_both(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[geographic]\nsource_mode = "synthetic"\n\n[domain]\nfoo = 1\n\n'
        "[flow]\nflow_regime = 'x'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)

    pointers = [entry["pointer"] for entry in excinfo.value.details]
    assert pointers == ["/domain/foo", "/flow/flow_regime"]
    assert [d.pointer for d in _errors(check(_as_written(path), base=tmp_path))] == pointers
    assert "foo" in str(excinfo.value) and "flow_regime" in str(excinfo.value)


@pytest.mark.parametrize("body", [pytest.param("", id="loadable"), *MALFORMED])
def test_loader_and_check_refuse_a_document_alike(tmp_path: Path, body: str) -> None:
    path = tmp_path / "project.toml"
    path.write_text(LOADABLE + body, encoding="utf-8")

    _same_refusal(path)


@pytest.mark.parametrize(
    "path", _documents_of_the_tree(), ids=lambda path: str(path.relative_to(REPO))
)
def test_file_of_the_tree_is_refused_or_read_alike(path: Path) -> None:
    _same_refusal(path)
