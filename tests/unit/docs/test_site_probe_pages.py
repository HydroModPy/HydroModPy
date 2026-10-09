"""The page types of the browser probe exist, and its allow list says why.

``tools/docs/site_probe.py`` opens one page of each type in a browser. A page that
moves would turn the probe red for the wrong reason, so the list is held to the
sources, and each accepted violation has a reason and an owner file.
"""

from __future__ import annotations

from tools.docs import check_refs, site_probe


def test_there_are_about_twenty_page_types() -> None:
    assert len(site_probe.PAGES) >= 20


def test_every_page_type_has_a_source_or_a_generator() -> None:
    gone = [
        path
        for path in site_probe.PAGES.values()
        if path != "search.html" and not check_refs.page_source_exists(path.removesuffix(".html"))
    ]
    assert not gone, f"pages with no source under docs/source: {gone}"


def test_every_allowed_violation_has_a_reason_and_names_its_fix() -> None:
    # The list may be empty: every violation found so far is fixed.
    for entry in site_probe.load_allow():
        assert entry["rule"] and entry["reason"], entry
        assert "Fix:" in entry["reason"], entry


def test_an_allowed_violation_is_matched_by_rule_page_and_target() -> None:
    allow = [{"rule": "r", "page": "p", "target": "sel", "reason": "x"}]
    assert site_probe.allowed(allow, "p", "r", "a > sel > b")
    assert not site_probe.allowed(allow, "q", "r", "a > sel")
    assert not site_probe.allowed(allow, "p", "other", "a > sel")
    assert not site_probe.allowed(allow, "p", "r", "unrelated")
    assert site_probe.allowed([{"rule": "r", "reason": "x"}], "any page", "r", "anything")
