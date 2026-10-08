"""The site check catches what a strict Sphinx build lets through."""

from __future__ import annotations

from pathlib import Path

from tools.docs.check_site import check


def _page(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<html><body><article class="bd-article">{body}</article></body></html>')


def test_a_clean_site_has_no_problem(tmp_path: Path) -> None:
    _page(tmp_path, "a.html", '<p id="here">See <a href="b.html#there"><code>b</code></a>.</p>')
    _page(tmp_path, "b.html", '<h1 id="there">B</h1><pre>``kept`` in code</pre>')
    assert check(tmp_path) == []


def test_a_link_inside_a_link_is_reported(tmp_path: Path) -> None:
    _page(tmp_path, "a.html", '<a class="card" href="#x"><span>see <a href="#x">x</a></span></a>')
    _page(tmp_path, "b.html", '<span id="x"></span>')
    assert any("inside a link" in p for p in check(tmp_path))


def test_a_missing_page_or_anchor_is_reported(tmp_path: Path) -> None:
    _page(tmp_path, "a.html", '<a href="b.html#gone">b</a> <a href="nowhere.html">c</a>')
    _page(tmp_path, "b.html", '<span id="here"></span>')
    problems = check(tmp_path)
    assert "a.html: dead link b.html#gone" in problems
    assert "a.html: dead link nowhere.html" in problems


def test_markup_shown_as_text_is_reported(tmp_path: Path) -> None:
    _page(tmp_path, "a.html", "<p>Parsed from ``[flow.bc]``. **Supported** sections.</p>")
    problems = check(tmp_path)
    assert any("double backticks" in p for p in problems)
    assert any("bold markers" in p for p in problems)
