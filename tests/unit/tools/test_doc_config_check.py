"""Unit checks for ``python -m tools.doc_config --check`` helpers."""

from __future__ import annotations

from pathlib import Path

from tools.doc_config.__main__ import changed_generated_paths


def test_changed_generated_paths_detects_missing_and_different_files(tmp_path: Path) -> None:
    generated_root = tmp_path / "generated"
    repo_root = tmp_path / "repo"
    generated_static = generated_root / "docs" / "source" / "_static"
    repo_static = repo_root / "docs" / "source" / "_static"
    generated_static.mkdir(parents=True)
    repo_static.mkdir(parents=True)

    same = generated_static / "same.json"
    changed = generated_static / "changed.json"
    missing = generated_static / "missing.json"
    same.write_text("{}\n", encoding="utf-8")
    changed.write_text('{"new": true}\n', encoding="utf-8")
    missing.write_text('{"exists": false}\n', encoding="utf-8")
    (repo_static / "same.json").write_text("{}\n", encoding="utf-8")
    (repo_static / "changed.json").write_text('{"old": true}\n', encoding="utf-8")

    assert changed_generated_paths(
        [same, changed, missing],
        generated_root=generated_root,
        repo_root=repo_root,
    ) == (
        "docs/source/_static/changed.json",
        "docs/source/_static/missing.json",
    )
