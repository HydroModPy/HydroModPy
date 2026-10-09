"""The pages of the documentation pass the accessibility rules the browser probe checks.

Each test pins the markup one extension writes, so a regression shows up without
a browser. tools/docs/site_probe.py checks the same rules on the built site.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "docs" / "source" / "_ext"
TEMPLATES = ROOT / "docs" / "source" / "_templates"
ALLOW = ROOT / "tools" / "docs" / "site_probe_allow.toml"


@pytest.fixture(scope="module")
def ext_path():
    """The Sphinx extensions are modules of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    yield
    sys.path.remove(str(EXT))


@pytest.fixture
def params(ext_path, monkeypatch: pytest.MonkeyPatch):
    """hmp_params with a two-key registry: flow.ic (table) and flow.restart_from."""
    import hmp_params as H

    nodes = {
        "flow": {"kind": "table", "children": ["flow.ic", "flow.restart_from"]},
        "flow.ic": {"kind": "table", "name": "ic", "children": []},
        "flow.restart_from": {
            "kind": "leaf",
            "name": "restart_from",
            "form": "string",
            "summary": "Hotstart that overrides [flow.ic].",
            "description": "Hotstart that overrides [flow.ic].",
        },
    }
    state = {
        "meta": {"roots": ["flow"], "files": {}},
        "nodes": nodes,
        "split": {"flow": "reference/parameters/flow"},
        "home": {p: "reference/parameters/flow" for p in nodes},
    }
    monkeypatch.setattr(H, "S", state)
    builder = SimpleNamespace(get_relative_uri=lambda a, b: "../" + b + ".html")
    return H, builder


# ---------------------------------------------------------------- summary, nested interactive


def test_a_summary_holds_no_link(params) -> None:
    H, builder = params
    line = H.summary_md("Overrides [flow.ic] and {toml}`flow.ic`.", builder, "guides/x")
    assert "<a " not in line
    assert '<span class="hmp-toml-ref">flow.ic</span>' in line
    assert '<span class="hmp-toml-ref"><code>flow.ic</code></span>' in line


def test_the_links_of_a_summary_are_listed_once_each(params) -> None:
    H, builder = params
    links = H.summary_links("Overrides [flow.ic] and {toml}`flow.ic`.", builder, "guides/x")
    assert [href for href, _ in links] == [
        "../reference/parameters/flow.html#p-flow-ic",
    ]


def test_the_card_gives_back_the_links_the_summary_lost(params) -> None:
    H, builder = params
    n = H.node("flow.restart_from")
    card = H.render_card(builder, "guides/x", "flow.restart_from", n)
    assert "<dt>See</dt>" in card
    assert 'href="../reference/parameters/flow.html#p-flow-ic"' in card


def test_a_card_whose_summary_has_no_link_has_no_see_row(params) -> None:
    H, builder = params
    n = dict(H.node("flow.restart_from"), summary="Hotstart.", description="Hotstart.")
    assert "<dt>See</dt>" not in H.render_card(builder, "guides/x", "flow.restart_from", n)


def test_the_card_lists_the_links_of_the_text_the_line_shows(params) -> None:
    H, builder = params
    n = dict(H.node("flow.restart_from"), summary="", description="")
    card = H.render_card(builder, "guides/x", "flow.restart_from", n, "Needs [flow.ic].")
    assert "<dt>See</dt>" in card


def test_a_line_of_a_toml_view_has_no_link_in_its_summary(params) -> None:
    import hmp_tview as T

    H, builder = params
    line, _plain = T.tline(builder, "guides/x", "flow.restart_from", ids=set())
    summary = line[line.index("<summary>") : line.index("</summary>")]
    assert "<a " not in summary
    assert "flow.ic" in summary
    assert "<dt>See</dt>" in line[line.index("</summary>") :]


# ---------------------------------------------------------------- the known keys table


def test_the_header_cells_of_the_known_keys_table_are_apart(params) -> None:
    H, builder = params
    H.S["nodes"]["flow"]["known_keys"] = {}
    directive = object.__new__(H.KnownKeysDirective)
    directive.arguments = ["flow"]
    env = SimpleNamespace(docname="guides/x")
    directive.state = SimpleNamespace(document=SimpleNamespace(settings=SimpleNamespace(env=env)))
    original = H.current_builder
    H.current_builder = lambda: builder
    try:
        html = directive.run()[0].astext()
    finally:
        H.current_builder = original
    assert "<th>Table</th> <th>Quantity</th> <th>Unit</th> <th>Valid range" in html


# ---------------------------------------------------------------- quantities page


def _leaf(name: str, unit: str | None, form: str = "number", numeric: bool = True) -> dict:
    return {
        "kind": "leaf",
        "name": name,
        "unit": unit,
        "unit_source": "known",
        "form": form,
        "numeric": numeric,
        "profile": "user",
    }


def test_every_key_with_a_unit_lands_in_a_group(ext_path, params) -> None:
    import hmp_tview as T

    leaves = [
        ("a.nx", _leaf("nx", "-", "integer")),
        ("a.share", _leaf("share", "-")),
        ("a.pct", _leaf("pct", "%")),
        ("a.dpi", _leaf("figure_dpi", "dpi", "integer")),
        ("a.years", _leaf("min_record_years", "year")),
        ("a.mass", _leaf("sconc", "mass/volume")),
        ("a.flux", _leaf("values", "mm/day", "any value", numeric=False)),
        ("a.mixed", _leaf("value", "- or m3/s")),
        ("a.res", _leaf("resolution", "CRS unit")),
        ("a.rough", _leaf("rough", "s/m^(1/3)")),
        ("a.len", _leaf("length", "m")),
        ("a.free", _leaf("coef", None)),
    ]
    groups = {title: [p for p, _ in hits] for title, _, hits in T.group_quantities(leaves)}
    assert sorted(p for hits in groups.values() for p in hits) == sorted(p for p, _ in leaves)
    assert groups["Counts and indices"] == ["a.nx"]
    assert groups["Fractions and ratios"] == ["a.share", "a.pct"]
    assert groups["Image resolutions"] == ["a.dpi"]
    assert "a.years" in groups["Durations"]
    assert groups["Concentrations"] == ["a.mass"]
    assert "a.flux" in groups["Conductivities and fluxes"]
    assert groups["Other units"] == ["a.mixed", "a.res", "a.rough"]
    assert groups["Other numbers"] == ["a.free"]


def test_a_count_is_not_listed_with_the_ratios(ext_path, params) -> None:
    import hmp_tview as T

    groups = {
        title: [p for p, _ in hits]
        for title, _, hits in T.group_quantities([("a.n", _leaf("n", "-", "integer"))])
    }
    assert "Fractions and ratios" not in groups


def test_the_real_registry_leaves_no_unit_outside_a_group(ext_path, params) -> None:
    import json

    import hmp_tview as T

    registry = ROOT / "docs" / "source" / "_data" / "registry.json"
    if not registry.is_file():
        pytest.skip("docs/source/_data/registry.json is written by a docs build")
    H, _ = params
    nodes = json.loads(registry.read_text())["nodes"]
    H.S["nodes"] = nodes
    leaves = [
        (p, n) for p, n in nodes.items() if n.get("kind") == "leaf" and n.get("profile") == "user"
    ]
    grouped = {p for _, _, hits in T.group_quantities(leaves) for p, _ in hits}
    missed = [p for p, n in leaves if T.unit_of(n) and p not in grouped]
    assert missed == []


# ---------------------------------------------------------------- autodoc signature


LONG_SIGNATURE = (
    '<dt class="sig sig-object py"><span class="sig-paren">(</span>\n\n<dl>\n'
    '<dd><em class="sig-param"><span class="n"><span class="pre">a</span></span></em>,</dd>\n'
    '<dd><em class="sig-param"><span class="n"><span class="pre">b</span></span></em>,</dd>\n'
    '</dl>\n\n<span class="sig-paren">)</span></dt>'
)


def test_a_long_signature_is_not_a_definition_list(ext_path) -> None:
    import hmp_api

    out = hmp_api.fix_signature_lists(LONG_SIGNATURE)
    assert "<dl>" not in out
    assert "<dd>" not in out
    assert out.count('<div class="hmp-sig-params">') == 1
    assert out.count("<div><em") == 2


def test_a_real_definition_list_is_left_alone(ext_path) -> None:
    import hmp_api

    html = "<dl>\n<dd><p>text</p></dd>\n</dl>"
    assert hmp_api.fix_signature_lists(html) == html


# ---------------------------------------------------------------- sidebar toctree


def test_the_expand_button_of_a_toctree_entry_has_a_name(ext_path) -> None:
    bs4 = pytest.importorskip("bs4")
    import hmp_site

    soup = bs4.BeautifulSoup(
        '<ul><li class="has-children"><a href="x.html">Guides</a><details>'
        '<summary><span class="toctree-toggle"><i></i></span></summary><ul></ul></details></li>'
        '<li class="has-children"><details><summary><p class="caption">Caption</p>'
        '<span class="toctree-toggle"><i></i></span></summary></details></li></ul>',
        "html.parser",
    )
    hmp_site.name_toctree_toggles(soup)
    first, second = soup.find_all("summary")
    assert first["aria-label"] == "Show or hide the pages under Guides"
    assert second.get("aria-label") is None
    hmp_site.name_toctree_toggles(soup)
    assert first["aria-label"] == "Show or hide the pages under Guides"


def test_a_toctree_given_as_text_is_returned_as_it_is(ext_path) -> None:
    import hmp_site

    assert hmp_site.name_toctree_toggles("<ul></ul>") == "<ul></ul>"


# ---------------------------------------------------------------- validation tables, search page


def test_a_validation_table_that_scrolls_takes_the_keyboard_focus(ext_path) -> None:
    source = (EXT / "hmp_validation.py").read_text(encoding="utf-8")
    assert source.count('<div class="hmp-val-scroll">') == 0
    assert source.count('<div class="hmp-val-scroll" tabindex="0" role="region" aria-label="') == 4


def test_the_door_filter_of_the_search_page_is_named() -> None:
    page = (TEMPLATES / "search.html").read_text(encoding="utf-8")
    assert ".pf-dropdown-trigger:not([aria-label])" in page
    assert 'setAttribute("aria-label"' in page


def test_no_accessibility_violation_is_allowed_any_more() -> None:
    import tomllib

    allowed = tomllib.loads(ALLOW.read_text(encoding="utf-8")).get("allow", [])
    assert [entry["rule"] for entry in allowed] == []
