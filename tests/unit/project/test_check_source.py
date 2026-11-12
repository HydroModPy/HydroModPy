"""What ``check`` reads, ``hydromodpy/project/check_source.py``: a document or a file, every diagnostic.

The cases go through the verb ``check``, which turns a source into one call of
``check_document`` or ``check_file``.
"""

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
def test_other_sources_refused(source: object) -> None:
    with pytest.raises(TypeError, match="path or a mapping"):
        check(source)  # type: ignore[arg-type]


@pytest.mark.parametrize("given", [{}, {"flow": {"flow_regime": "steady"}}], ids=["empty", "draft"])
def test_document_without_base(given: dict) -> None:
    from hydromodpy.config.loading import MEMORY_NEEDS_BASE

    [found] = check(given)

    assert (found.code, found.severity, found.detail) == (
        "refused_value",
        "error",
        MEMORY_NEEDS_BASE,
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("not = [valid", "bad_toml"),
        ('base_config = "run.toml"\n', "bad_chain"),
        ('base_config = "missing.toml"\n', "bad_chain"),
    ],
    ids=["syntax", "cycle", "missing parent"],
)
def test_unreadable_file(tmp_path: Path, text: str, code: str) -> None:
    [found] = check(_write(tmp_path, text))

    assert (found.path, found.code, found.severity) == ("", code, "error")


def test_missing_file(tmp_path: Path) -> None:
    [found] = check(tmp_path / "absent.toml")

    assert found.code == "bad_chain"


def test_project_root_in_file(tmp_path: Path) -> None:
    path = _write(tmp_path, f'[workspace]\nproject_root = "{tmp_path.as_posix()}"\n')

    found = [item for item in check(path) if item.parts == ("workspace", "project_root")]

    assert [(item.code, item.severity) for item in found] == [("unknown_key", "error")]
    assert "not a key of a file" in found[0].detail


def test_old_key_in_parent(tmp_path: Path) -> None:
    parent = _write(tmp_path, "[modflownwt]\nheadtol = 1e-6\n", "project.toml")
    child = _write(tmp_path, 'base_config = "project.toml"\n')

    told = [item for item in check(child) if item.code == "old_key"]

    assert [item.severity for item in told] == ["warning"]
    assert told[0].detail.startswith(f"{parent}: modflownwt")
    assert told[0].path == "modflownwt"


def test_unexpected_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(api, "check_file", fail)

    [found] = check(tmp_path / "run.toml")

    assert (found.code, found.severity) == ("refused_value", "error")
    assert found.detail == "Config check failed: the disk went away"


def test_sites_project_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.project.launch.test_plan import write_sites_project

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
