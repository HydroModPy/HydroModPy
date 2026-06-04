"""Unit tests for the pure HTML helpers of static comparison reports.

These complement test_comparison_helpers.py, which already covers the
basic table escaping, the relative/link_relative sibling case, and the
render_links skip-missing branch. Here we pin the remaining branches:
full character escaping with idempotency, every short() boundary, the
relative()/link_relative() fallback paths, and the render_links empty
state.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.reporting.comparison.html_utils import (
    link_relative,
    relative,
    render_links,
    render_table,
    safe,
    short,
)


def test_safe_escapes_every_special_character() -> None:
    # html.escape with quote=True (the default) escapes & < > " '.
    assert safe("&") == "&amp;"
    assert safe("<") == "&lt;"
    assert safe(">") == "&gt;"
    assert safe('"') == "&quot;"
    assert safe("'") == "&#x27;"
    assert safe("a & b < c > d \" e ' f") == "a &amp; b &lt; c &gt; d &quot; e &#x27; f"


def test_safe_is_idempotent_on_already_safe_text() -> None:
    # Plain alphanumeric text and digits pass through unchanged, so a
    # second pass is a no-op. The ampersand inside an entity is itself
    # escaped, which is the expected (non-decoding) behavior of escape.
    plain = "head_domain_high"
    assert safe(plain) == plain
    assert safe(safe(plain)) == plain

    once = safe("a < b")
    assert once == "a &lt; b"
    assert safe(once) == "a &amp;lt; b"


def test_safe_handles_none_and_non_string_values() -> None:
    assert safe(None) == ""
    assert safe(0) == "0"
    assert safe(False) == "False"
    assert safe(3.5) == "3.5"
    # Non-None falsy values are stringified, not blanked.
    assert safe("") == ""


def test_short_returns_text_unchanged_within_limit() -> None:
    assert short("abc") == "abc"
    assert short("abcd", limit=4) == "abcd"
    # Default limit is 80, so anything shorter is untouched.
    assert short("x" * 80) == "x" * 80


def test_short_truncates_with_ellipsis_beyond_limit() -> None:
    # Result length equals limit: limit-1 kept chars plus the 3-char "..."
    # is wrong; the code appends "..." after text[: limit - 1].
    result = short("abcdef", limit=4)
    assert result == "abc..."
    assert result[: 4 - 1] == "abc"

    long = short("x" * 200)
    assert long == "x" * 79 + "..."
    assert long.endswith("...")


def test_short_clamps_negative_kept_length_to_zero() -> None:
    # limit <= 0 must not produce a negative slice end; max(0, limit-1).
    assert short("abcdef", limit=0) == "..."
    assert short("abcdef", limit=1) == "..."


def test_short_handles_none() -> None:
    assert short(None) == ""
    assert short(None, limit=2) == ""


def test_relative_success_and_fallback(tmp_path) -> None:
    root = tmp_path / "comparison"
    inside = root / "sub" / "metrics.csv"
    inside.parent.mkdir(parents=True)
    inside.write_text("x", encoding="utf-8")

    assert relative(root, inside) == "sub/metrics.csv"

    # A path outside root cannot be made relative, so the raw string is
    # returned untouched (the except branch).
    outside = tmp_path / "elsewhere" / "other.csv"
    assert relative(root, outside) == str(outside)


def test_link_relative_direct_child_branch(tmp_path) -> None:
    web_dir = tmp_path / "web"
    asset = web_dir / "figures" / "plot.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"x")

    # Path under web_dir resolves through the first relative_to branch.
    assert link_relative(web_dir, asset) == "figures/plot.png"


def test_link_relative_sibling_uses_os_relpath_fallback(tmp_path) -> None:
    web_dir = tmp_path / "comparison" / "web"
    sibling = tmp_path / "comparison" / "metrics.csv"
    web_dir.mkdir(parents=True)
    sibling.write_text("x", encoding="utf-8")

    # Not under web_dir, but a valid relpath exists -> os.path.relpath.
    assert link_relative(web_dir, sibling) == "../metrics.csv"


def test_render_table_truncates_long_cell_values() -> None:
    long_value = "y" * 200
    html = render_table(
        [{"name": long_value}],
        [("name", "Name")],
        empty="none",
    )
    # short() runs before safe() so the rendered cell is capped at 80.
    assert ("y" * 79 + "...") in html
    assert ("y" * 81) not in html
    assert html.startswith("<table>")
    assert "<th>Name</th>" in html


def test_render_table_uses_empty_value_for_missing_keys() -> None:
    # A row missing the column key falls back to the empty default ''.
    html = render_table(
        [{"other": "ignored"}],
        [("name", "Name")],
        empty="nothing",
    )
    assert "<td></td>" in html
    assert "ignored" not in html


def test_render_links_empty_when_no_existing_files(tmp_path) -> None:
    missing_a = tmp_path / "a.csv"
    missing_b = tmp_path / "b.csv"
    html = render_links(root=tmp_path, web_dir=tmp_path, links=[missing_a, missing_b])
    assert html == '<p class="muted">Aucun fichier cle.</p>'

    # And with no links at all.
    assert render_links(root=tmp_path, web_dir=tmp_path, links=[]) == (
        '<p class="muted">Aucun fichier cle.</p>'
    )


def test_render_links_escapes_paths_and_builds_anchor(tmp_path) -> None:
    root = tmp_path / "comparison"
    web_dir = root / "web"
    web_dir.mkdir(parents=True)
    asset = web_dir / "figures" / "a & b.csv"
    asset.parent.mkdir(parents=True)
    asset.write_text("x", encoding="utf-8")

    html = render_links(root=root, web_dir=web_dir, links=[asset])

    # The href is relative to web_dir, the label relative to root, both
    # HTML-escaped (ampersand -> &amp;).
    assert 'href="figures/a &amp; b.csv"' in html
    assert ">web/figures/a &amp; b.csv</a>" in html
    assert html.startswith("<p><a ")
