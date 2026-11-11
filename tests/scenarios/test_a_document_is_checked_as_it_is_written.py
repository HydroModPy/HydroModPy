"""A document is checked as it is written, on the permanent island, with no solve.

Three games. From Python, ``hmp.check`` says what an empty document and a draft
without ``[geographic]`` still lack, finds nothing to say of the whole island, and
loads no figure module. From the command line, ``hmp check`` passes the
island and lists both faults of a copy with two faulty sections, with code 14.
Then ``hmp run`` refuses that copy with code 14 at the pointers of its check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

EXIT_CONFIG = 14

API = """\
import json, sys, tomllib
from pathlib import Path

import hydromodpy as hmp

def said(found):
    return [[d.path, d.code, d.severity] for d in found]

document = tomllib.loads(Path("project.toml").read_text(encoding="utf-8"))
draft = {name: table for name, table in document.items() if name != "geographic"}
# A document in memory has no folder: the check is told where its paths are read from.
base = Path(".").resolve()
result = {
    "empty": said(hmp.check({}, base=base)),
    "draft": said(hmp.check(draft, partial=True, base=base)),
    "whole": said(hmp.check(document, base=base)),
    "no_base": said(hmp.check(document)),
    "figures": sorted(m for m in sys.modules if m.startswith("hydromodpy.display.figures")),
}
Path("check.json").write_text(json.dumps(result), encoding="utf-8")
"""


def _island() -> dict[str, str]:
    """The permanent island with a copy, ``broken.toml``, that holds two faulty sections."""
    files = dict(island_files("calage"))
    del files["calib.toml"]
    text = files["project.toml"]
    broken = text.replace("keep_solver_files = false", 'keep_solver_files = "maybe"')
    broken = broken.replace('flow_regime = "steady"', 'flow_regime = "sometimes"')
    assert broken.count('"maybe"') == 1 and broken.count('"sometimes"') == 1
    files["broken.toml"] = broken
    return files


def _printed(played: Any) -> dict[str, Any]:
    """Return the JSON document a command printed, read from the log of the scenario."""
    log = played.log.read_text(encoding="utf-8")
    start = log.find("{\n")
    assert start >= 0, log[-2000:]
    document, _ = json.JSONDecoder().raw_decode(log[start:])
    return document["data"]


def _command(tmp_path: Path, env: dict[str, str], cache: Path, name: str, *argv: str) -> Any:
    scenario = Scenario(
        name=name,
        covers=f"hmp {' '.join(argv)} on the permanent island, before any solve",
        files=_island(),
        argv=argv,
        needs=(),
    )
    return play(scenario, tmp_path / name, env, cache)


def test_a_draft_is_checked_in_python_as_it_is_written(tmp_path, scenario_env, scenario_cache):
    scenario = Scenario(
        name="island",
        covers="hmp.check on an empty document, a draft, the whole island, and one without base",
        files=_island(),
        python=API,
        needs=(),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    result = json.loads((played.root / "check.json").read_text(encoding="utf-8"))
    assert result["empty"] == [["geographic", "to_fill", "to_fill"]]
    assert result["draft"] == [["geographic", "to_fill", "to_fill"]]
    assert result["whole"] == []
    assert result["no_base"] == [["", "refused_value", "error"]]
    assert result["figures"] == []


def test_hmp_check_lists_every_fault_of_a_file(tmp_path, scenario_env, scenario_cache):
    passed = _command(
        tmp_path,
        scenario_env,
        scenario_cache,
        "clean",
        "check",
        "project.toml",
        "--format",
        "json",
    )
    refused = _command(
        tmp_path,
        scenario_env,
        scenario_cache,
        "broken",
        "check",
        "broken.toml",
        "--format",
        "json",
    )

    assert passed.returncode == 0, passed.log.read_text(encoding="utf-8")[-2000:]
    clean = _printed(passed)
    assert clean["ok"] is True
    assert clean["diagnostics"] == []
    assert refused.returncode == EXIT_CONFIG, refused.log.read_text(encoding="utf-8")[-2000:]
    faulty = _printed(refused)
    assert faulty["ok"] is False
    errors = [item for item in faulty["diagnostics"] if item["severity"] == "error"]
    assert sorted(item["loc"] for item in errors) == ["flow.flow_regime", "simulation.results"]


def test_a_run_refuses_a_file_at_the_pointers_of_its_check(tmp_path, scenario_env, scenario_cache):
    checked = _command(
        tmp_path,
        scenario_env,
        scenario_cache,
        "checked",
        "check",
        "broken.toml",
        "--format",
        "json",
    )
    run = _command(
        tmp_path,
        scenario_env,
        scenario_cache,
        "run",
        "run",
        "broken.toml",
        "--format",
        "json",
    )

    assert run.returncode == EXIT_CONFIG, run.log.read_text(encoding="utf-8")[-2000:]
    assert not (run.root / "runs").exists()
    errors = [item for item in _printed(checked)["diagnostics"] if item["severity"] == "error"]
    refusal = _printed(run)
    assert refusal["exit_code"] == EXIT_CONFIG
    assert len(errors) == 2
    for item in errors:
        assert f": {item['loc']}: " in refusal["detail"], refusal["detail"]
