"""The verb ``check`` of ``hydromodpy/project/api.py``: a document or a file, every diagnostic."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project import api
from hydromodpy.project.api import check
from hydromodpy.project.environment import Environment

_CALIBRATION = """\
[workspace]

[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[calibration]
method = "grid"
max_trials = 4
method_options = { points_per_dim = 4 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"
"""


def _write(tmp_path: Path, text: str, name: str = "run.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _summary(found: list[Diagnostic]) -> list[tuple[str, str, str]]:
    return [(item.path, item.code, item.severity) for item in found]


@pytest.mark.parametrize("source", [3, None, b"run.toml", ["run.toml"]])
def test_a_source_that_is_neither_a_path_nor_a_mapping_is_refused(source: object) -> None:
    with pytest.raises(TypeError, match="path or a mapping"):
        check(source)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        (True, [("geographic", "to_fill", "to_fill")]),
        (False, [("geographic", "to_fill", "error")]),
    ],
    ids=["a draft", "to run"],
)
def test_an_empty_document_has_one_key_to_fill(
    tmp_path: Path, partial: bool, expected: list[tuple[str, str, str]]
) -> None:
    assert _summary(check({}, base=tmp_path, partial=partial)) == expected


@pytest.mark.parametrize("given", [{}, {"flow": {"flow_regime": "steady"}}], ids=["empty", "draft"])
def test_a_document_without_a_base_is_refused_as_the_loader_refuses_it(given: dict) -> None:
    from hydromodpy.config.loading import MEMORY_NEEDS_BASE

    [found] = check(given)

    assert (found.code, found.severity, found.detail) == (
        "refused_value",
        "error",
        MEMORY_NEEDS_BASE,
    )


def test_a_draft_is_the_default_for_a_document_and_for_a_file(tmp_path: Path) -> None:
    path = _write(tmp_path, '[flow]\nflow_regime = "steady"\n')

    by_default = check(path)

    assert ("geographic", "to_fill", "to_fill") in _summary(by_default)
    assert ("geographic", "to_fill", "error") in _summary(check(path, partial=False))


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("not = [valid", "bad_toml"),
        ('base_config = "run.toml"\n', "bad_chain"),
        ('base_config = "missing.toml"\n', "bad_chain"),
    ],
    ids=["syntax", "cycle", "missing parent"],
)
def test_a_file_that_cannot_be_read_is_one_diagnostic(tmp_path: Path, text: str, code: str) -> None:
    [found] = check(_write(tmp_path, text))

    assert (found.path, found.code, found.severity) == ("", code, "error")


def test_a_missing_file_is_a_diagnostic_of_the_chain(tmp_path: Path) -> None:
    [found] = check(tmp_path / "absent.toml")

    assert found.code == "bad_chain"


def test_a_workflow_name_no_run_knows_is_an_unknown_name(tmp_path: Path) -> None:
    [found] = check(_write(tmp_path, '[workflow]\nmode = "comparison"\n'))

    assert (found.path, found.code) == ("workflow", "unknown_name")
    assert "hmp report compare" in found.detail


def test_a_fault_of_a_file_carries_the_line_of_its_key(tmp_path: Path) -> None:
    path = _write(tmp_path, '[flow]\nflow_regime = "nope"\n')

    [found] = [item for item in check(path) if item.path == "flow.flow_regime"]

    assert found.line_number == 2


def test_a_document_given_in_memory_has_no_line(tmp_path: Path) -> None:
    found = check({"flow": {"flow_regime": "nope"}}, base=tmp_path)

    assert {item.line_number for item in found if item.path == "flow.flow_regime"} == {None}


def test_a_project_root_written_in_a_file_is_refused_at_its_key(tmp_path: Path) -> None:
    path = _write(tmp_path, f'[workspace]\nproject_root = "{tmp_path.as_posix()}"\n')

    found = [item for item in check(path) if item.parts == ("workspace", "project_root")]

    assert [(item.code, item.severity) for item in found] == [("unknown_key", "error")]
    assert "not a key of a file" in found[0].detail


def test_the_same_root_written_in_a_document_is_taken(tmp_path: Path) -> None:
    found = check({"workspace": {"project_root": str(tmp_path)}}, base=tmp_path)

    assert [item for item in found if item.parts == ("workspace", "project_root")] == []


def test_an_old_form_of_a_parent_is_told_under_the_parent(tmp_path: Path) -> None:
    parent = _write(tmp_path, "[modflownwt]\nheadtol = 1e-6\n", "project.toml")
    child = _write(tmp_path, 'base_config = "project.toml"\n')

    told = [item for item in check(child) if item.code == "old_key"]

    assert [item.severity for item in told] == ["warning"]
    assert told[0].detail.startswith(f"{parent}: modflownwt")
    assert told[0].path == "modflownwt"


def test_the_bounds_of_the_environment_and_the_project_root_reach_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake(document, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.update(kwargs)
        return []

    monkeypatch.setattr("hydromodpy.config.check.check", fake)
    bounds = Bounds(allowed_hosts=frozenset({"data.example.org"}))
    path = _write(tmp_path, '[workflow]\nmode = "simulation"\n')

    check(path, partial=False, inputs=True, environment=Environment(bounds=bounds))

    assert seen == {
        "partial": False,
        "inputs": True,
        "base": tmp_path.resolve(),
        "bounds": bounds,
    }


def test_the_default_environment_gives_the_default_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "hydromodpy.config.check.check", lambda document, **kwargs: seen.update(kwargs) or []
    )

    check({}, base=tmp_path, inputs=True)

    assert seen["bounds"] == Bounds()
    assert seen["base"] == tmp_path.resolve()


def test_a_base_named_for_a_file_wins_over_the_folder_of_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "hydromodpy.config.check.check", lambda document, **kwargs: seen.update(kwargs) or []
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = _write(tmp_path, '[workflow]\nmode = "simulation"\n')

    check(path, base=elsewhere)

    assert seen["base"] == elsewhere.resolve()


def test_a_check_that_fails_unexpectedly_is_a_finding_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(api, "_check_file", fail)

    [found] = check(tmp_path / "run.toml")

    assert (found.code, found.severity) == ("refused_value", "error")
    assert found.detail == "Config check failed: the disk went away"


def _preflight_that_says(monkeypatch: pytest.MonkeyPatch, calls: list[Path]) -> None:
    said = Diagnostic(
        path="calibration.parameters.K", code="calibration_preflight", severity="warning"
    )

    def preflight(config: object, *, source: Path) -> list[Diagnostic]:
        calls.append(Path(source))
        return [said]

    monkeypatch.setattr("hydromodpy.calibration.preflight.preflight_calibration", preflight)


def test_the_preflight_of_a_calibration_is_added_when_the_document_has_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    _preflight_that_says(monkeypatch, calls)
    path = _write(tmp_path, _CALIBRATION, "calib.toml")

    found = check(path)

    assert calls == [path.resolve()]
    assert ("calibration.parameters.K", "calibration_preflight", "warning") in _summary(found)


@pytest.mark.parametrize(
    "fault",
    ['\n[flow]\nflow_regime = "nope"\n', "\n[simulation]\nbogus = 1\n"],
    ids=["an error", "an unknown key"],
)
def test_the_preflight_waits_for_a_document_with_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    calls: list[Path] = []
    _preflight_that_says(monkeypatch, calls)
    path = _write(tmp_path, _CALIBRATION + fault, "calib.toml")

    found = check(path)

    assert calls == []
    assert any(item.severity == "error" for item in found)


def test_the_preflight_waits_for_a_key_to_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    _preflight_that_says(monkeypatch, calls)
    path = _write(tmp_path, _CALIBRATION.replace('[geographic]\nsource_mode = "synthetic"\n', ""))

    found = check(path)

    assert calls == []
    assert ("geographic", "to_fill", "to_fill") in _summary(found)


def test_a_sites_project_gives_its_issues_at_the_key_they_reach(tmp_path: Path) -> None:
    from tests.unit.project.launch.test_sites_plan import write_sites_project

    project = write_sites_project(tmp_path, k_cells=("5e-5", "not_a_number"))

    [found] = check(project / "project.toml")

    assert (found.path, found.code, found.severity) == (
        "flow.param.K.field.value",
        "sites_case",
        "error",
    )
    assert "sites.csv:3 column k -> flow.param.K.field.value" in found.detail


def test_a_sound_sites_project_has_no_error(tmp_path: Path) -> None:
    from tests.unit.project.launch.test_sites_plan import write_sites_project

    project = write_sites_project(tmp_path)

    assert [item for item in check(project / "project.toml") if item.severity == "error"] == []


def test_a_sites_project_reads_the_inputs_of_its_cases_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.project.launch.test_sites_plan import write_sites_project

    seen: list[dict[str, object]] = []
    unreachable = Diagnostic(
        path="data.dem.sources.0.path", code="input_unreachable", severity="error", detail="gone"
    )

    def fake(document, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.append(kwargs)
        return [unreachable, Diagnostic(path="flow", code="to_fill", severity="to_fill")]

    monkeypatch.setattr("hydromodpy.config.check.check", fake)
    bounds = Bounds(allowed_hosts=frozenset({"data.example.org"}))
    project = write_sites_project(tmp_path)

    found = check(project / "project.toml", inputs=True, environment=Environment(bounds=bounds))

    assert len(seen) > 1
    assert {(kwargs["inputs"], kwargs["bounds"]) for kwargs in seen} == {(True, bounds)}
    assert [item for item in found if item.code.startswith("input")] == [unreachable]
    assert all(item.code != "to_fill" for item in found)


def test_a_sites_project_without_inputs_reads_no_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.project.launch.test_sites_plan import write_sites_project

    monkeypatch.setattr(
        "hydromodpy.config.check.check", lambda *_a, **_k: pytest.fail("no case is checked")
    )
    project = write_sites_project(tmp_path)

    assert [item for item in check(project / "project.toml") if item.severity == "error"] == []
