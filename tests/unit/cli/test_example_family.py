"""Tests for the ``hmp example`` family (list, show, add)."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("HMP_EXAMPLES_SOURCE", raising=False)


def test_bare_family_is_a_usage_error(monkeypatch) -> None:
    assert _run(monkeypatch, ["hmp", "example"]) == 2


def test_family_help_lists_its_actions(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "--help"]) == 0
    out = capsys.readouterr().out
    for action in ("list", "show", "add"):
        assert action in out


def test_list_names_example_04(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "list"]) == 0
    out = capsys.readouterr().out
    assert "04" in out
    assert "MiB" in out


def test_show_json_marks_every_file_missing_on_a_cold_cache(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "show", "04", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "04"
    assert payload["missing_size"] == payload["total_size"]
    assert all(row["cached"] is False for row in payload["data"])


def test_show_of_an_unknown_id_exits_not_found(monkeypatch, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "example", "show", "99"]) == 10
    assert "Unknown example" in capsys.readouterr().err


def test_add_installs_from_a_local_source(monkeypatch, capsys, tmp_path) -> None:
    """The whole add path, pointed at a tree instead of GitHub."""
    from hydromodpy.examples.manifest import ExampleEntry, ExampleFile

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
            ExampleFile(
                repo_path="examples/projects/tiny/step1.toml",
                dest="projects/tiny/step1.toml",
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
        data=(),
    )
    monkeypatch.setattr("hydromodpy.examples.manifest.load_catalog", lambda path=None: (entry,))
    monkeypatch.setenv("HMP_EXAMPLES_SOURCE", str(checkout))

    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    code = _run(monkeypatch, ["hmp", "example", "add", "t1", "--workspace", str(workspace)])

    assert code == 0
    assert (workspace / "projects" / "tiny" / "step1.toml").read_bytes() == payload
    out = capsys.readouterr().out
    assert "1 file(s) written" in out
    assert "step1.toml" in out


def test_add_into_a_missing_workspace_exits_not_found(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "example", "add", "04", "--workspace", str(tmp_path / "nowhere")],
    )
    assert code == 10


def test_dev_examples_manifest_rewrites_the_catalog(monkeypatch, capsys, tmp_path) -> None:
    output = tmp_path / "catalog.toml"
    code = _run(monkeypatch, ["hmp", "dev", "examples", "manifest", "--output", str(output)])
    assert code == 0
    from hydromodpy.examples.manifest import catalog_path

    assert output.read_text(encoding="utf-8") == catalog_path().read_text(encoding="utf-8")
    assert "Wrote" in capsys.readouterr().out
