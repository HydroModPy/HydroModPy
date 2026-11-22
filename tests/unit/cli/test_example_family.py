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


def _tiny_catalog(monkeypatch, tmp_path: Path) -> Path:
    """Two one-file examples served from a local tree, and the workspace to fill."""
    from hydromodpy.core.payload.index import PayloadFile
    from hydromodpy.project.examples.manifest import ExampleEntry

    checkout = tmp_path / "checkout"
    entries = []
    for example_id in ("t1", "t2"):
        payload = f'[simulation]\nname = "{example_id}"\n'.encode()
        folder = checkout / "examples" / "projects" / example_id
        folder.mkdir(parents=True)
        (folder / "project.toml").write_bytes(payload)
        entries.append(
            ExampleEntry(
                id=example_id,
                directory=example_id,
                title="Tiny",
                summary="One file.",
                runtime="instant",
                entry_config="project.toml",
                files=(
                    PayloadFile(
                        repo_path=f"examples/projects/{example_id}/project.toml",
                        dest=f"projects/{example_id}/project.toml",
                        size=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    ),
                ),
                data=(),
            )
        )
    monkeypatch.setattr(
        "hydromodpy.project.examples.install.load_catalog", lambda path=None: tuple(entries)
    )
    monkeypatch.setenv("HMP_EXAMPLES_SOURCE", str(checkout))
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    return workspace


def test_add_from_a_local_source(monkeypatch, capsys, tmp_path) -> None:
    # The whole add path, pointed at a tree instead of GitHub.
    workspace = _tiny_catalog(monkeypatch, tmp_path)
    code = _run(monkeypatch, ["hmp", "example", "add", "t1", "--workspace", str(workspace)])

    assert code == 0
    assert (workspace / "projects" / "t1" / "project.toml").is_file()
    assert not (workspace / "projects" / "t2").exists()
    out = capsys.readouterr().out
    assert "1 file(s) written" in out
    assert "hmp run" in out and "project.toml" in out


def test_add_several_then_all(monkeypatch, capsys, tmp_path) -> None:
    workspace = _tiny_catalog(monkeypatch, tmp_path)
    argv = ["hmp", "example", "add", "t2", "t1", "-w", str(workspace), "--format", "json"]
    assert _run(monkeypatch, argv) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "hmp.example.add.v2"
    assert [row["example_id"] for row in document["data"]] == ["t2", "t1"]
    assert all(row["written"] for row in document["data"])

    assert _run(monkeypatch, ["hmp", "example", "add", "--all", "-w", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "[example add t1] Everything already cached" in out
    assert "[example add t2] 0 file(s) written, 1 already up to date" in out


@pytest.mark.parametrize("extra", [[], ["t1", "--all"]])
def test_add_wants_ids_or_all_but_not_both(monkeypatch, capsys, tmp_path, extra) -> None:
    workspace = _tiny_catalog(monkeypatch, tmp_path)
    assert _run(monkeypatch, ["hmp", "example", "add", *extra, "-w", str(workspace)]) == 2
    assert "--all" in capsys.readouterr().err
    assert not (workspace / "projects").exists()


def test_add_missing_workspace(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "example", "add", "04", "--workspace", str(tmp_path / "nowhere")],
    )
    assert code == 10
