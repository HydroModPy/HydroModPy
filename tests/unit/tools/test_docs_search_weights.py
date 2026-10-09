"""The search index weighs the quantity of a key over the long text of its card."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SITE = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext" / "hmp_site.py"


def _load():
    spec = importlib.util.spec_from_file_location("hmp_site_under_test", SITE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROW = (
    '<tr id="p-flow-param-k"><td><a href="#x"><code>[flow.param.K]</code></a></td>'
    "<td>Hydraulic conductivity</td><td>m/s</td></tr>"
)


def test_the_quantity_cell_of_a_known_key_is_weighted() -> None:
    body = _load().weigh_for_search(f"<table><tbody>{ROW}</tbody></table>")
    assert '<td data-pagefind-weight="8">Hydraulic conductivity</td><td>m/s</td>' in body
    # Only the second cell: the key and the unit keep the default weight.
    assert body.count("data-pagefind-weight") == 1


def test_the_card_of_a_key_weighs_less() -> None:
    body = _load().weigh_for_search('<div class="hmp-card"><dl></dl></div>')
    assert body == '<div class="hmp-card" data-pagefind-weight="0.5"><dl></dl></div>'


def test_other_tables_are_left_alone() -> None:
    html = "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    assert _load().weigh_for_search(html) == html
