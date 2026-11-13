"""The check of a document gives every diagnostic at once, and agrees with the loader.

``check(document, partial=True)`` validates a document section by section. A
required key not written yet is ``to_fill``, found by the required fields of the
models, never by the type of a Pydantic error. A rule that reads several sections
waits until they are complete. ``partial=False`` is the validator the loader
walks, so a document it refuses is refused by ``from_toml`` at the same pointer.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
import typing
import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field, ValidationError
from pydantic_core.core_schema import ErrorType

from hydromodpy.config.check import CHECK_CODES, _said_by_the_sections, check, phrase
from hydromodpy.config.config_migration import migrate_config_doc
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.section_loader import PYDANTIC_CODES, code_of, severity_of
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, HydroModelBase
from hydromodpy.core.config_kit.said import Said, collecting
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.toml_io.loader import config_base_dir, merge_toml_chain, read_toml_chain
from hydromodpy.core.toml_io.paths import bare_name_refusal
from hydromodpy.schema.changes import prerelease_refusal
from hydromodpy.schema.phrases import LANGS
from tests._helpers.fake_solvers import fake_adapter

REPO = Path(__file__).resolve().parents[3]
EXAMPLE_04 = REPO / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
SYNTHETIC = {"source_mode": "synthetic"}
LAKE = {"bedleak": 1e-6, "initial_stage": 10.0}
K_PARAMETER = {
    "param_list": ["K"],
    "param": {"K": {"field": {"kind": "homogeneous", "value": 1e-5}}},
}


def _with(path: str, value: Any, **sections: Any) -> dict[str, Any]:
    """Return a synthetic document that writes *value* at the dotted *path*."""
    document: dict[str, Any] = {"geographic": dict(SYNTHETIC), **sections}
    *heads, leaf = path.split(".")
    node = document
    for head in heads:
        node = node.setdefault(head, {})
    node[leaf] = value
    return document


def _seen(found: list[Diagnostic]) -> list[tuple[str, str, str]]:
    return [(diagnostic.path, diagnostic.code, diagnostic.severity) for diagnostic in found]


def _errors(found: list[Diagnostic]) -> list[Diagnostic]:
    return [diagnostic for diagnostic in found if diagnostic.severity != "warning"]


# What a draft gives, partial or not

DOCUMENTS: dict[str, tuple[dict[str, Any], bool, list[tuple[str, str, str]]]] = {
    "the empty document has its required section to fill": (
        {},
        True,
        [("geographic", "to_fill", "to_fill")],
    ),
    "partial=False makes the hole an error at the same code": (
        {},
        False,
        [("geographic", "to_fill", "error")],
    ),
    "the workspace is implicit": ({"geographic": SYNTHETIC}, True, []),
    "an empty geographic section has its catchment to fill": (
        {"geographic": {}},
        True,
        [("geographic.catchment", "to_fill", "to_fill")],
    ),
    "a catchment without kind has its tag to fill, not a union error": (
        {"geographic": {"catchment": {"x_outlet": 1.0}}},
        True,
        [("geographic.catchment.kind", "to_fill", "to_fill")],
    ),
    "a field through a mapping of models has its tag to fill": (
        _with("flow.param.hk_bedrock.field.value", 1e-5),
        True,
        [("flow.param.hk_bedrock.field.kind", "to_fill", "to_fill")],
    ),
    "a lake has its required keys to fill": (
        _with("flow.sinks_sources.lakes.cheze.bedleak", 1e-6),
        True,
        [("flow.sinks_sources.lakes.cheze.initial_stage", "to_fill", "to_fill")],
    ),
    "a key a validator requires and the model does not stays a refused value": (
        _with("simulation.time", {"end_datetime": "2001-01-01", "step_value": "1 day"}),
        True,
        [("simulation.time", "refused_value", "error")],
    ),
    "an unknown key": (
        _with("domain.foo", 1),
        True,
        [("domain.foo", "unknown_key", "error")],
    ),
    "an unknown and a retired root section": (
        {"geographic": SYNTHETIC, "floww": {}, "modflow": {}},
        True,
        [("modflow", "retired_section", "error"), ("floww", "unknown_key", "error")],
    ),
    "a value out of range": (
        _with("solver.drain_bed_thickness_m", -1.0),
        True,
        [("solver.drain_bed_thickness_m", "out_of_range", "error")],
    ),
    "a value that is not a choice": (
        _with("solver.modflow6.runtime.mf6_ims_complexity", "x"),
        True,
        [("solver.modflow6.runtime.mf6_ims_complexity", "not_a_choice", "error")],
    ),
    "a table where a scalar is read": (
        _with("domain.supports.aquifer", 1.0),
        True,
        [("domain.supports.aquifer", "wrong_type", "error")],
    ),
    "a solver nobody serves": (
        _with("solver.backend", "nope"),
        True,
        [("solver.backend", "unknown_name", "error")],
    ),
    "a table of a solver nobody serves": (
        _with("solver.nope", {"a": 1}),
        True,
        [("solver.nope", "unknown_name", "error")],
    ),
    "an unknown key of a solver table": (
        _with("solver.modflow6.typo", 1),
        True,
        [("solver.modflow6.typo", "unknown_key", "error")],
    ),
    "two faulty sections give two diagnostics": (
        {"geographic": SYNTHETIC, "domain": {"foo": 1}, "flow": {"flow_regime": "x"}},
        True,
        [("domain.foo", "unknown_key", "error"), ("flow.flow_regime", "refused_value", "error")],
    ),
    "a rule runs when its sections are complete, the others still to fill": (
        {
            "geographic": {},
            "solver": {"backend": "modflow_nwt"},
            "flow": {"sinks_sources": {"lakes": {"lac": LAKE}}},
        },
        True,
        [("geographic.catchment", "to_fill", "to_fill"), ("", "incompatible", "error")],
    ),
    "a rule waits while a section it reads is incomplete": (
        {
            "geographic": SYNTHETIC,
            "solver": {"backend": "modflow_nwt"},
            "flow": {"sinks_sources": {"lakes": {"lac": {"bedleak": 1e-6}}}},
        },
        True,
        [("flow.sinks_sources.lakes.lac.initial_stage", "to_fill", "to_fill")],
    ),
    "every rule that refuses is told": (
        {
            "geographic": SYNTHETIC,
            "solver": {"backend": "modflow_nwt"},
            "flow": {
                "restart_from": "prior.hds",
                "ic": {"kind": "spinup_cyclic"},
                "sinks_sources": {"lakes": {"lac": LAKE}},
            },
        },
        True,
        [("", "incompatible", "error"), ("", "contamination", "error")],
    ),
    "an old form loads and says so": (
        {"geographic": SYNTHETIC, "modflow6": {"runtime": {"mf6_ims_complexity": "SIMPLE"}}},
        True,
        [("modflow6", "old_key", "warning")],
    ),
    "a key a release retired is refused by name": (
        _with("calibration.forward_model", "linear_reservoir", flow=K_PARAMETER),
        True,
        [("calibration.forward_model", "retired_key", "error")],
    ),
}


@pytest.mark.parametrize(
    ("document", "partial", "expected"), DOCUMENTS.values(), ids=list(DOCUMENTS)
)
def test_diagnostics_of_a_document(
    tmp_path: Path, document: dict[str, Any], partial: bool, expected: list[tuple[str, str, str]]
) -> None:
    found = check(document, partial=partial, base=tmp_path)

    assert _seen(_errors(found)) == [item for item in expected if item[2] != "warning"]
    for item in expected:
        assert item in _seen(found)


@pytest.mark.parametrize(
    ("document", "codes"),
    [
        ({"geographic": {"catchment": {"x_outlet": 1.0}}}, {"union_tag_not_found"}),
        (_with("flow.param.K.field.value", 1e-5), {"union_tag_not_found"}),
        ({"geographic": {}}, {"value_error"}),
    ],
)
def test_hole_folds_the_pydantic_fault(
    tmp_path: Path, document: dict[str, Any], codes: set[str]
) -> None:
    found = check(document, base=tmp_path)

    (hole,) = _errors(found)
    assert hole.code == "to_fill"
    assert hole.detail
    assert not codes & {diagnostic.error_type for diagnostic in found}


def test_thirty_unknown_keys(tmp_path: Path) -> None:
    document = {"geographic": SYNTHETIC, "domain": {f"bogus{index}": index for index in range(30)}}

    found = check(document, base=tmp_path)

    assert sorted(diagnostic.path for diagnostic in found) == sorted(
        f"domain.bogus{index}" for index in range(30)
    )
    assert {diagnostic.code for diagnostic in found} == {"unknown_key"}


def test_to_fill_phrase() -> None:
    assert "once it is filled" in phrase("to_fill")


def test_document_that_is_not_a_table(tmp_path: Path) -> None:
    found = check(["geographic"], base=tmp_path)  # type: ignore[arg-type]
    assert _seen(found) == [("", "wrong_type", "error")]


def test_check_needs_a_base() -> None:
    """A document has no folder of its own, so the current folder is never its base."""
    with pytest.raises(TypeError, match="base"):
        check({"geographic": SYNTHETIC})  # type: ignore[call-arg]


def test_document_is_not_changed(tmp_path: Path) -> None:
    document = {"geographic": SYNTHETIC, "modflow6": {"runtime": {"mf6_ims_complexity": "SIMPLE"}}}
    before = repr(document)

    check(document, base=tmp_path)

    assert repr(document) == before


# One field at a time, as a form writes it (the former per-field validator)

FIELD_CASES = (
    ("flow.flow_regime", "steady", None),
    ("flow.flow_regime", "permanent", "steady"),
    ("flow.flow_regime", "wrong_value", "steady"),
    ("flow.flow_regime", "sideways", "transient"),
    ("solver.backend", "modflow_nwt", None),
    ("solver.backend", " Boussinesq ", None),
    (
        "solver.backend",
        "nope",
        "solver.backend names 'nope', and this installation serves boussinesq, "
        "linear_reservoir, modflow6, modflow_nwt",
    ),
    ("mesh.engine", " triangle ", None),
    (
        "mesh.engine",
        "nope",
        "mesh.engine names 'nope', and this installation serves catchment, regular, triangle, voronoi",
    ),
    ("geographic.terrain_engine", None, None),
    ("geographic.terrain_engine", "nope", "geographic.terrain_engine names 'nope'"),
    ("calibration.evaluator", "nope", "calibration.evaluator names 'nope'"),
    ("solver.modflow6.runtime.mf6_ims_complexity", "SIMPLE", None),
    ("solver.modflow6.runtime.mf6_ims_complexity", "x", "Input should be"),
    ("solver.boussinesq.max_iterations", 40, None),
    ("solver.drain_bed_thickness_m", -1.0, "greater than 0"),
    ("flow.bc.drainage.value", 0.1, None),
    ("flow.bc.whatever_they_called_it.value", 1.0, None),
)


@pytest.mark.parametrize(("path", "value", "error"), FIELD_CASES)
def test_field_check(tmp_path: Path, path: str, value: object, error: str | None) -> None:
    """The checks of the annotation run: the registry, a bound, a choice, a named table."""
    document = _with(path, value)

    at_path = [
        diagnostic
        for diagnostic in _errors(check(document, base=tmp_path))
        if diagnostic.path == path and diagnostic.code != "to_fill"
    ]

    if error is None:
        assert at_path == []
    else:
        assert at_path, f"nothing refused at {path}"
        assert error in at_path[0].detail


def test_unknown_key_of_flow(tmp_path: Path) -> None:
    """``[flow]`` refuses its unknown keys itself, at the section, with their names."""
    (fault,) = _errors(check(_with("flow.does_not_exist", 42), base=tmp_path))

    assert (fault.path, fault.code) == ("flow", "refused_value")
    assert "does_not_exist" in fault.detail


@pytest.mark.parametrize(
    "path",
    [
        "flow.param.K.field.value",
        "flow.param.Sy.field.value",
        "flow.param.hk_bedrock.field.value",
        "flow.sinks_sources.lakes.cheze.bedleak",
    ],
)
def test_instance_key_is_a_name(tmp_path: Path, path: str) -> None:
    """A path crosses an instance: the segment after a mapping is a key, not a field."""
    found = check(_with(path, 1e-5), base=tmp_path)

    assert not [d for d in found if d.path == path], _seen(found)
    assert {d.code for d in _errors(found)} <= {"to_fill"}


@pytest.mark.parametrize(
    ("document", "path", "code"),
    [
        (
            _with("flow.param.K.field", {"kind": "homogeneous", "value": 1e-5, "no_such_leaf": 1}),
            "flow.param.K.field.no_such_leaf",
            "unknown_key",
        ),
        ({"geographic": SYNTHETIC, "nowhere": {"at": {"all": 1.0}}}, "nowhere", "unknown_key"),
        (_with("domain.supports.aquifer", 1.0), "domain.supports.aquifer", "wrong_type"),
    ],
)
def test_key_nothing_declares(
    tmp_path: Path, document: dict[str, Any], path: str, code: str
) -> None:
    assert (path, code, "error") in _seen(check(document, base=tmp_path))


def test_warm_check_is_fast(tmp_path: Path) -> None:
    """The bench of the lot measures the 10 ms of a whole document; this is the guard."""
    document = _with("flow.flow_regime", "steady")
    check(document, base=tmp_path)

    start = time.perf_counter()
    for _ in range(20):
        check(document, base=tmp_path)
    elapsed_ms = (time.perf_counter() - start) * 1000.0 / 20

    assert elapsed_ms < 50, f"mean per-call latency {elapsed_ms:.2f} ms"


# The help of a key


def test_fault_carries_the_field_description(tmp_path: Path) -> None:
    from hydromodpy.solver.base.solver_config import SolverConfig

    (fault,) = _errors(check(_with("solver.drain_bed_thickness_m", -1.0), base=tmp_path))

    assert fault.help == SolverConfig.model_fields["drain_bed_thickness_m"].description


class _PluginSettings(HydroModelBase):
    """Settings of the solver a test registers as a plugin."""

    relaxation: float = Field(
        default=0.5,
        gt=0.0,
        description="How far each iteration moves the heads, above zero.",
    )


def test_plugin_fault_help(tmp_path: Path, isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("pluginflow", options=_PluginSettings))
    document = _with("solver.pluginflow", {"relaxation": -1.0}, solver={"backend": "pluginflow"})

    found = [d for d in check(document, base=tmp_path) if d.path == "solver.pluginflow.relaxation"]

    assert [(d.code, d.help) for d in found] == [
        ("out_of_range", "How far each iteration moves the heads, above zero.")
    ]


# The files of example 04, and what a check of [display] imports


def _as_written(path: Path) -> dict[str, Any]:
    return merge_toml_chain(read_toml_chain(path, root=None), root=None)


@pytest.mark.parametrize(
    "name",
    [
        "project.toml",
        "step6_soil_reservoir.toml",
        "run_calibration_api_daily.toml",
        "run_calibration_bdtopage.toml",
    ],
)
def test_example_04_files_have_no_error(name: str) -> None:
    """The two calibration files leave their station to [site] gauge: no false error."""
    path = EXAMPLE_04 / name

    found = check(_as_written(path), partial=False, base=config_base_dir(path))

    assert _errors(found) == []


@pytest.mark.allow_subprocess
def test_display_check_imports_no_figure_module(tmp_path: Path) -> None:
    """A fresh process, since another test may have drawn a figure in this one."""
    script = textwrap.dedent(
        f"""
        import sys
        from hydromodpy.config.check import check
        found = check(
            {{"geographic": {SYNTHETIC!r}, "display": {{"figure": [{{"variable": "head"}}]}}}},
            base={str(tmp_path)!r},
        )
        assert [d for d in found if d.severity != "warning"] == [], found
        loaded = [name for name in sys.modules if name.startswith(("hydromodpy.display.frames.", "hydromodpy.display.special."))]
        assert loaded == [], loaded
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]


# The codes and their phrases


def test_phrase_in_each_language() -> None:
    assert len(CHECK_CODES) == 22
    for code in CHECK_CODES:
        for lang in LANGS:
            assert phrase(code, lang).strip(), (code, lang)


def test_phrase_in_another_language() -> None:
    with pytest.raises(ValueError, match="en, fr"):
        phrase("to_fill", "de")


@pytest.mark.parametrize("error_type", typing.get_args(ErrorType))
def test_pydantic_error_type_has_a_code(error_type: str) -> None:
    """A Pydantic that adds a type never gives a code outside the closed set."""
    assert code_of(error_type) in CHECK_CODES


def test_pydantic_table_names_check_codes() -> None:
    assert set(PYDANTIC_CODES.values()) <= CHECK_CODES


@pytest.mark.parametrize(
    ("error_type", "detail", "code"),
    [
        ("missing", "", "to_fill"),
        ("union_tag_not_found", "", "to_fill"),
        ("greater_than_equal", "", "out_of_range"),
        ("float_parsing", "", "wrong_type"),
        ("dict_type", "", "wrong_type"),
        (
            "value_error",
            "solver.backend names 'x', and this installation serves a, b",
            "unknown_name",
        ),
        ("value_error", "'budget' is not accepted any more: write max_trials", "retired_key"),
        ("value_error", "a plain refusal", "refused_value"),
        ("a_type_pydantic_adds_tomorrow", "", "refused_value"),
    ],
)
def test_code_of_a_fault(error_type: str, detail: str, code: str) -> None:
    assert code_of(error_type, detail) == code


class _RefusesAKey(HydroModelBase):
    model_refused_keys: typing.ClassVar[dict[str, str]] = {"budget": "write max_trials"}


def _refusal_of_the_model_base() -> str:
    with pytest.raises(ValidationError) as err:
        _RefusesAKey.model_validate({"budget": 3})
    return err.value.errors()[0]["msg"]


def _refusal_of_the_registry() -> str:
    with pytest.raises(ValueError, match="serves") as err:
        check_registered_name("x", ["a", "b"], key="solver.backend")
    return str(err.value)


def _move_of_the_migration() -> str:
    (change,) = migrate_config_doc({"geographic": {"catchment": {"dem_init_path": "dem.tif"}}})
    return change


# The code of these refusals is read from their words, so each one is asked of
# its own raiser: a refusal reworded where it is raised turns this table red.
RAISERS: dict[str, tuple[typing.Callable[[], str], str]] = {
    "a key the model base refuses": (_refusal_of_the_model_base, "retired_key"),
    "a key the migration moves": (_move_of_the_migration, "retired_key"),
    "an input written as a bare name": (
        lambda: bare_name_refusal("dem.tif", former=None),
        "retired_key",
    ),
    "a key only a pre-release wrote": (
        lambda: prerelease_refusal("run.toml", ["steady_engine_options"]),
        "retired_key",
    ),
    "a name no registry serves": (_refusal_of_the_registry, "unknown_name"),
}


@pytest.mark.parametrize(("raiser", "code"), RAISERS.values(), ids=list(RAISERS))
def test_raiser_gives_its_code(raiser: typing.Callable[[], str], code: str) -> None:
    assert code_of("value_error", raiser()) == code


@pytest.mark.parametrize(
    ("code", "severity"),
    [
        ("to_fill", "to_fill"),
        ("old_key", "warning"),
        ("cross_warning", "warning"),
        ("section_warning", "warning"),
        ("experimental_key", "warning"),
        ("cross_rule", "error"),
        ("unknown_key", "error"),
    ],
)
def test_severity_of_a_code(code: str, severity: str) -> None:
    assert severity_of(code) == severity


def test_codes_given_are_known(tmp_path: Path) -> None:
    given = {
        diagnostic.code
        for document, _, _ in DOCUMENTS.values()
        for diagnostic in check(document, base=tmp_path)
    }
    for path in sorted(EXAMPLE_04.glob("*.toml")):
        given |= {d.code for d in check(_as_written(path), base=config_base_dir(path))}

    assert given <= CHECK_CODES
    assert len(given) >= 12


# The warnings of the validators are collected per call, never by the process filters

LAYERS_WITH_A_COUNT = {"layers": {"genmtd_lay": "list", "lay_proportions": [0.5, 0.5], "nlay": 5}}


def test_validator_warning_is_a_diagnostic(tmp_path: Path) -> None:
    document = {"geographic": dict(SYNTHETIC), "domain": LAYERS_WITH_A_COUNT}
    filters = list(warnings.filters)
    with warnings.catch_warnings(record=True) as heard:
        warnings.simplefilter("always")
        inside = list(warnings.filters)
        found = check(document, base=tmp_path)
        assert warnings.filters == inside
    assert heard == []
    assert filters == warnings.filters
    texts = [d.detail for d in found if d.code == "section_warning"]
    assert len(texts) == 1
    assert "nlay must not be provided" in texts[0]


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ([], []),
        ([Said("a", UserWarning)], [("section_warning", "a")]),
        ([Said("a", UserWarning), Said("a", UserWarning)], [("section_warning", "a")]),
        ([Said("a", ConfigKeyRenamedWarning)], [("old_key", "a")]),
        (
            [Said("a", UserWarning), Said("a", ConfigKeyRenamedWarning)],
            [("section_warning", "a"), ("old_key", "a")],
        ),
        ([Said("a", DeprecationWarning), Said("b", ResourceWarning)], []),
        ([Said("a", FutureWarning)], [("section_warning", "a")]),
    ],
)
def test_said_texts_become_warnings_once_each(said, expected) -> None:
    found = _said_by_the_sections(said)
    assert [(d.code, d.detail) for d in found] == expected
    assert {d.severity for d in found} <= {"warning"}


def test_two_checks_each_warn(tmp_path: Path) -> None:
    quiet = {"geographic": dict(SYNTHETIC)}
    loud = {**quiet, "domain": LAYERS_WITH_A_COUNT}
    seen = [
        [d.code for d in check(document, base=tmp_path) if d.code == "section_warning"]
        for document in (loud, quiet, loud)
    ]
    assert seen == [["section_warning"], [], ["section_warning"]]


def test_unknown_parameter_unit(tmp_path: Path) -> None:
    """The loader resolves the parameters, so the file the CLI reads keeps quiet under a sink."""
    path = tmp_path / "run.toml"
    path.write_text(
        textwrap.dedent(
            """
            [geographic]
            source_mode = "synthetic"
            [flow]
            param_list = ["K"]
            [flow.param.K.field]
            kind = "homogeneous"
            value = 1e-5
            [calibration.parameters.x]
            bounds = [1.0, 2.0]
            path = "flow.nowhere.value"
            """
        ),
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as heard:
        warnings.simplefilter("always")
        with collecting() as said:
            HydroModPyConfig.from_toml(path)
    assert heard == []
    assert [(s.category, "unit is unknown" in s.text) for s in said] == [(UserWarning, True)]
