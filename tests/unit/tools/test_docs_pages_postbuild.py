"""The deploy keeps main, dev and stable tags, and writes the files of the site root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import docs_pages_postbuild as post


@pytest.mark.parametrize(
    ("name", "kept"),
    [
        ("main", True),
        ("dev", True),
        ("v1.0", True),
        ("v2.0.0", True),
        ("v2.0.0a4", False),
        ("v2.1.0rc1", False),
        ("v2.0.0b2", False),
    ],
)
def test_the_site_keeps_main_dev_and_stable_tags(name: str, kept: bool) -> None:
    assert post.is_kept(name) is kept


def test_a_folder_that_is_not_a_version_is_never_removed() -> None:
    assert not post.is_version("assets")
    assert post.is_version("v2.0.0a1")


def test_one_deploy_writes_the_root_and_lists_what_to_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_dir = tmp_path / "site" / "dev"
    version_dir.mkdir(parents=True)
    (version_dir / "theme.js.map").write_text("{}")
    root_dir = tmp_path / "site-root"
    remove_list = tmp_path / "remove.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "docs_pages_postbuild",
            "--version-dir",
            str(version_dir),
            "--root-dir",
            str(root_dir),
            "--existing",
            "main,v1.0,v2.0.0a1,v2.0.0a4,assets",
            "--remove-list",
            str(remove_list),
        ],
    )
    assert post.main() == 0
    switcher = json.loads((root_dir / "switcher.json").read_text())
    assert [entry["version"] for entry in switcher] == ["main", "dev", "v1.0"]
    assert switcher[0]["preferred"] is True
    assert remove_list.read_text().split() == ["v2.0.0a1", "v2.0.0a4"]
    assert not (version_dir / "theme.js.map").exists()
    for name in ("index.html", "404.html", "robots.txt"):
        assert (root_dir / name).is_file()
