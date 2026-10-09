"""llms.txt is built from the rendered article, not from the sources."""

from __future__ import annotations

from pathlib import Path

from tools.docs.llms_txt import article_text as _article_text
from tools.docs.llms_txt import describe, write

TABLE = (
    "<table><thead><tr><th><p>Table</p></th><th><p>Quantity</p></th></tr></thead>"
    "<tbody><tr><td><p><code>[flow.param.K]</code></p></td><td><p>Hydraulic conductivity</p>"
    "</td></tr></tbody></table>"
)


def _page(root: Path, name: str, body: str, canonical: str = "") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    path.write_text(
        f'<html><head>{head}</head><body><article class="bd-article">{body}</article></body></html>'
    )


def article_text(body: str) -> str:
    return _article_text(f'<article class="bd-article">{body}</article>')


def test_text_keeps_headings_code_lists_and_tables() -> None:
    text = article_text(
        '<h1>Title<a class="headerlink" href="#t">#</a></h1><p>Set <code>a.b</code> now.</p>'
        f"<ul><li><p>one</p></li><li><p>two</p></li></ul>{TABLE}"
        "<pre>x = 1\ny = 2</pre>"
    )
    assert text.startswith("# Title\n\nSet `a.b` now.\n")
    assert "- one\n- two\n" in text
    assert (
        "| Table | Quantity |\n| --- | --- |\n| `[flow.param.K]` | Hydraulic conductivity |" in text
    )
    assert "```\nx = 1\ny = 2\n```" in text


def test_buttons_hidden_text_and_scripts_are_left_out() -> None:
    text = article_text(
        "<p>Visible</p><button>Copy</button><p class='hmp-search-text'>twin</p>"
        "<script>var x = 1;</script><span hidden>door</span>"
    )
    assert text == "Visible\n"


def test_a_definition_reads_on_one_line() -> None:
    text = article_text(
        "<dl><dt>Task</dt><dd><p>Fit K.</p></dd><dt>Time</dt><dd>A minute.</dd></dl>"
    )
    assert text == "**Task**: Fit K.\n**Time**: A minute.\n"


def test_the_card_of_a_key_is_not_a_table_row() -> None:
    text = article_text(
        '<table><tbody><tr><td>K</td></tr><tr class="hmp-known-card"><td colspan="4">'
        '<span class="tl-code">value = 1</span><span class="tl-note">The value.</span>'
        "</td></tr></tbody></table>"
    )
    assert "| K |" in text
    assert "`value = 1` : The value." in text
    assert "| `value" not in text


def test_a_description_is_the_task_or_the_first_sentences() -> None:
    assert describe("# G\n\n**Task**: Fit K to a gauge. Then check it.\n**Time**: 1 min\n") == (
        "Fit K to a gauge. Then check it."
    )
    assert describe("# P\n\nYes. A result is a record of the whole run. It has more.\n") == (
        "Yes. A result is a record of the whole run."
    )
    assert describe("# P\n\n- only a list\n") == ""


def test_the_index_groups_by_door_and_the_full_text_skips_contribute(tmp_path: Path) -> None:
    base = "https://example.org/main/"
    _page(
        tmp_path, "index.html", "<h1>Home</h1><p>The home page has a long first sentence.</p>", base
    )
    _page(tmp_path, "theory/a.html", "<h1>A theory</h1><p>Fit one parameter to a gauge today.</p>")
    _page(
        tmp_path, "contribute/x.html", "<h1>Internals</h1><p>How the engine is laid out inside.</p>"
    )
    _page(tmp_path, "search.html", "<h1>Search</h1>")
    index, full = write(tmp_path)
    lines = index.read_text().splitlines()
    assert lines[0] == "# HydroModPy"
    assert lines.index("## Theory") < lines.index("## Optional")
    assert f"- [A theory]({base}theory/a.html): Fit one parameter to a gauge today." in lines
    assert "Search" not in index.read_text()
    text = full.read_text()
    assert "# A theory" in text
    assert "Internals" not in text


def test_a_version_links_its_own_folder(tmp_path: Path) -> None:
    """dev names main's page as canonical; its llms.txt still links dev's pages."""
    (tmp_path / "index.html").write_text(
        '<html><head><link rel="canonical" href="https://example.org/main/index.html">'
        "<script>DOCUMENTATION_OPTIONS.theme_switcher_version_match = 'dev';</script></head>"
        '<body><article class="bd-article"><h1>Home</h1><p>The home page.</p></article>'
        "</body></html>"
    )
    _page(tmp_path, "theory/new.html", "<h1>New</h1><p>A page that only dev has today.</p>")
    index, full = write(tmp_path)
    text = index.read_text()
    assert "(https://example.org/dev/theory/new.html)" in text
    assert "example.org/main/" not in text
    assert "<!-- https://example.org/dev/theory/new.html -->" in full.read_text()
