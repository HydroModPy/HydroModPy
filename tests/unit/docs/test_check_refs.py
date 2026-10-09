"""References to the documentation, written outside the pages, name files that exist.

The scan is ``tools/docs/check_refs.py``: a ``docs/...`` path must exist and a
link to the published site must name a page with a source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs import check_refs

requires_git = pytest.mark.skipif(
    not (check_refs.ROOT / ".git").exists(),
    reason="the scanned files are listed by git ls-files",
)


@requires_git
@pytest.mark.allow_subprocess
def test_the_tree_has_no_dead_reference() -> None:
    assert check_refs.check() == []


def _tree(tmp_path: Path, text: str) -> list[str]:
    (tmp_path / "docs" / "source" / "guides").mkdir(parents=True)
    (tmp_path / "docs" / "source" / "guides" / "real.md").write_text("# Real\n", encoding="utf-8")
    (tmp_path / "docs" / "source" / "guides" / "folder").mkdir()
    (tmp_path / "README.md").write_text(text, encoding="utf-8")
    return check_refs.check(root=tmp_path, files=["README.md"])


def test_a_path_that_exists_passes(tmp_path: Path) -> None:
    text = "See `docs/source/guides/real.md` and docs/source/guides/folder/.\n"
    assert _tree(tmp_path, text) == []


def test_a_dead_path_is_reported(tmp_path: Path) -> None:
    problems = _tree(tmp_path, "See docs/source/guides/gone.md for more.\n")
    assert problems == ["README.md:1: no such path: docs/source/guides/gone.md"]


def test_a_path_inside_a_longer_path_is_not_a_docs_path(tmp_path: Path) -> None:
    assert _tree(tmp_path, "Run tools/docs/check_page.py first.\n") == []


def test_a_generated_path_passes(tmp_path: Path) -> None:
    assert _tree(tmp_path, "Open docs/build/html/index.html.\n") == []


def test_a_site_link_needs_a_source(tmp_path: Path) -> None:
    good = "https://docs.hydromodpy.fr/main/guides/real.html"
    bad = "https://docs.hydromodpy.fr/main/guides/moved.html"
    problems = _tree(tmp_path, f"{good}\n{bad}\n")
    assert problems == ["README.md:2: no page for the link: guides/moved.html"]


def test_a_site_link_is_checked_against_the_built_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (tmp_path / "docs" / "source" / "guides").mkdir(parents=True)
    (tmp_path / "docs" / "source" / "guides" / "real.md").write_text("# Real\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "https://docs.hydromodpy.fr/main/guides/real.html\n", encoding="utf-8"
    )
    problems = check_refs.check(site=site, root=tmp_path, files=["README.md"])
    assert problems == ["README.md:1: not in the built site: guides/real.html"]
