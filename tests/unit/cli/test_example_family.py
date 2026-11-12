"""The ``hmp example`` family: list, show and add the example projects.

Sizes are in MiB. A cold cache has no example file.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

from ._hmp import run_main as _run


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("HMP_EXAMPLES_SOURCE", raising=False)


def test_list(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "list"]) == 0
    out = capsys.readouterr().out
    assert "04" in out
    assert "MiB" in out


def test_show_on_a_cold_cache(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "show", "04", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)["data"]
    assert payload["id"] == "04"
    assert payload["missing_size"] == payload["total_size"]
    assert all(row["cached"] is False for row in payload["data"])


def test_show_unknown_id(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "show", "99"]) == 10
    assert "Unknown example" in capsys.readouterr().err


def test_add_from_a_local_source(monkeypatch, capsys, tmp_path) -> None:
    # The whole add path, pointed at a tree instead of GitHub.
    from hydromodpy.core.payload.index import PayloadFile
    from hydromodpy.project.examples.manifest import ExampleEntry

    payload = b'[simulation]\nname = "tiny"\n'
    checkout = tmp_path / "checkout"
    (checkout / "examples" / "projects" / "tiny").mkdir(parents=True)
    (checkout / "examples" / "projects" / "tiny" / "step1.toml").write_bytes(payload)

    entry = ExampleEntry(
        id="t1",
        directory="tiny",
        title="Tiny",
        summary="One file.",
        runtime="instant",
        entry_config="step1.toml",
        files=(
            PayloadFile(
                repo_path="examples/projects/tiny/step1.toml",
                dest="projects/tiny/step1.toml",
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
        data=(),
    )
    monkeypatch.setattr(
        "hydromodpy.project.examples.manifest.load_catalog", lambda path=None: (entry,)
    )
    monkeypatch.setenv("HMP_EXAMPLES_SOURCE", str(checkout))

    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    code = _run(monkeypatch, ["hmp", "example", "add", "t1", "--workspace", str(workspace)])

    assert code == 0
    assert (workspace / "projects" / "tiny" / "step1.toml").read_bytes() == payload
    out = capsys.readouterr().out
    assert "1 file(s) written" in out
    assert "step1.toml" in out


def test_add_missing_workspace(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "example", "add", "04", "--workspace", str(tmp_path / "nowhere")],
    )
    assert code == 10
