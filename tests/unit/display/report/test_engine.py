"""The report engine: levels by construction, missing figures, copies, escaping, report.json."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.display.report.engine import (
    LEVELS,
    Block,
    Link,
    Metric,
    Picture,
    Prose,
    Table,
    items_at,
    pairs_table,
    write_pages,
)

TODAY = date(2026, 11, 11)


def _png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n")
    return path


def _write(tmp_path: Path, blocks: list[Block], **kwargs) -> Path:
    return write_pages(
        tmp_path / "out", title="T", subtitle="S", blocks=blocks, rendered=TODAY, **kwargs
    )


LEVELLED = Block(
    "b",
    "Block",
    items=(
        ("compact", Metric("a", 1)),
        ("standard", Metric("b", 2)),
        ("audit", Metric("c", 3)),
    ),
)


@pytest.mark.parametrize(
    ("level", "labels"),
    [("compact", ["a"]), ("standard", ["a", "b"]), ("audit", ["a", "b", "c"])],
)
def test_items_grow_with_the_level(level, labels):
    assert [i.label for i in items_at(LEVELLED, level)] == labels


def test_levels_are_monotonic_by_construction():
    seen = [len(items_at(LEVELLED, level)) for level in LEVELS]
    assert seen == sorted(seen)


def test_block_above_the_level_is_none():
    block = Block("hi", "High", min_level="audit", items=(("audit", Metric("x", 1)),))
    assert items_at(block, "standard") is None
    assert items_at(block, "audit") is not None


def test_levels_true_writes_five_pages(tmp_path):
    index = _write(tmp_path, [LEVELLED])
    out = tmp_path / "out"
    assert index == out / "index.html"
    for name in (*LEVELS, "by_block"):
        assert (out / "review" / name / "index.html").is_file()


def test_levels_false_writes_one_page(tmp_path):
    _write(tmp_path, [LEVELLED], levels=False)
    out = tmp_path / "out"
    assert (out / "index.html").is_file()
    assert not (out / "review").exists()


def test_compact_page_hides_standard_items(tmp_path):
    _write(tmp_path, [LEVELLED])
    compact = (tmp_path / "out" / "review" / "compact" / "index.html").read_text()
    audit = (tmp_path / "out" / "review" / "audit" / "index.html").read_text()
    assert "<span>b</span>" not in compact
    assert "<span>c</span>" in audit


def test_by_block_page_carries_every_level_variant(tmp_path):
    _write(tmp_path, [LEVELLED])
    text = (tmp_path / "out" / "review" / "by_block" / "index.html").read_text()
    assert text.count('class="variant"') == len(LEVELS)


def test_required_missing_figure_gets_a_frame(tmp_path):
    block = Block("f", "F", items=(("compact", Picture("gone", "Gone", None, required=True)),))
    _write(tmp_path, [block])
    assert "Required figure missing" in (tmp_path / "out" / "index.html").read_text()


def test_optional_missing_figure_shows_nothing(tmp_path):
    block = Block("f", "F", items=(("compact", Picture("gone", "Gone", tmp_path / "no.png")),))
    _write(tmp_path, [block])
    text = (tmp_path / "out" / "index.html").read_text()
    assert "Required figure missing" not in text
    assert "<img" not in text


def test_figures_are_copied_and_name_collisions_kept(tmp_path):
    first = _png(tmp_path / "a" / "figures" / "map.png")
    second = _png(tmp_path / "b" / "figures" / "map.png")
    block = Block(
        "f",
        "F",
        items=(
            ("compact", Picture("one", "One", first)),
            ("compact", Picture("two", "Two", second)),
        ),
    )
    _write(tmp_path, [block])
    copies = sorted(p.name for p in (tmp_path / "out" / "figures").iterdir())
    assert len(copies) == 2
    assert "map.png" in copies


def test_text_is_escaped(tmp_path):
    block = Block("x", "<b>Title</b>", items=(("compact", Metric("<i>", "<script>")),))
    _write(tmp_path, [block])
    text = (tmp_path / "out" / "index.html").read_text()
    assert "<script>" not in text.split("</style>")[1]
    assert "&lt;script&gt;" in text


def test_every_item_kind_renders(tmp_path):
    table = Table("t", "Table", (("k", "K"),), ({"k": "cell"},))
    empty = Table("e", "Empty", (("k", "K"),), (), empty="Nothing here.")
    block = Block(
        "all",
        "All",
        "Lead sentence.",
        items=(
            ("compact", Prose(("First paragraph.",))),
            ("compact", table),
            ("compact", empty),
            ("compact", Link("manifest", tmp_path / "out" / "manifest.json", "json")),
            ("compact", Link("site", "https://example.org/x")),
            ("compact", "A warning line."),
            ("compact", pairs_table("p", "Pairs", [("a", 1)])),
        ),
    )
    _write(tmp_path, [block], levels=False)
    text = (tmp_path / "out" / "index.html").read_text()
    for part in ("Lead sentence.", "First paragraph.", "cell", "Nothing here.", "A warning line."):
        assert part in text
    assert 'href="manifest.json"' in text
    assert 'href="https://example.org/x"' in text


def test_report_json_lists_figures_and_missing(tmp_path):
    ok = _png(tmp_path / "run" / "figures" / "ok.png")
    block = Block(
        "f",
        "F",
        items=(
            ("compact", Picture("ok", "Ok", ok, required=True)),
            ("compact", Picture("gone", "Gone", None, required=True)),
            ("compact", Picture("opt", "Opt", None)),
        ),
    )
    _write(tmp_path, [block], lang="fr", label="validated", preset="research")
    data = json.loads((tmp_path / "out" / "report.json").read_text())
    assert data["schema"] == "hydromodpy.report.v1"
    assert (data["preset"], data["lang"], data["label"]) == ("research", "fr", "validated")
    assert data["rendered"] == "2026-11-11"
    assert data["figures"]["ok"]["file"] == "ok.png"
    assert data["figures"]["gone"] == {"title": "Gone", "file": None, "required": True}
    assert data["missing"] == ["gone"]


def test_header_carries_label_and_date(tmp_path):
    _write(tmp_path, [LEVELLED], label="validated, rule 2")
    text = (tmp_path / "out" / "index.html").read_text()
    assert "validated, rule 2" in text
    assert "2026-11-11" in text


def test_rewrite_replaces_old_figures(tmp_path):
    first = _png(tmp_path / "a" / "figures" / "old.png")
    _write(tmp_path, [Block("f", "F", items=(("compact", Picture("o", "O", first)),))])
    second = _png(tmp_path / "a" / "figures" / "new.png")
    _write(tmp_path, [Block("f", "F", items=(("compact", Picture("n", "N", second)),))])
    assert [p.name for p in (tmp_path / "out" / "figures").iterdir()] == ["new.png"]


def test_a_file_the_engine_did_not_write_stays_in_figures(tmp_path):
    out = tmp_path / "out"
    theirs = _png(out / "figures" / "drawn_by_the_caller.png")
    other = _png(out / "figures" / "unrelated.png")
    _write(tmp_path, [Block("f", "F", items=(("compact", Picture("t", "T", theirs)),))])
    _write(tmp_path, [Block("f", "F", items=(("compact", Picture("t", "T", theirs)),))])
    assert theirs.is_file()
    assert other.is_file()
    report = json.loads((out / "report.json").read_text())
    assert report["missing"] == []
    assert report["figures"]["t"]["file"] == "drawn_by_the_caller.png"


def test_a_copy_never_overwrites_a_file_of_the_caller(tmp_path):
    out = tmp_path / "out"
    theirs = _png(out / "figures" / "map.png")
    before = theirs.read_bytes()
    source = tmp_path / "src" / "map.png"
    source.parent.mkdir()
    source.write_bytes(b"other bytes")
    _write(tmp_path, [Block("f", "F", items=(("compact", Picture("m", "M", source)),))])
    assert theirs.read_bytes() == before
    copied = json.loads((out / "report.json").read_text())["figures"]["m"]["file"]
    assert copied != "map.png"
    assert (out / "figures" / copied).read_bytes() == b"other bytes"


def test_the_frame_words_come_from_the_caller(tmp_path):
    page = write_pages(
        tmp_path / "out",
        title="T",
        subtitle="",
        blocks=[Block("f", "F", items=(("compact", Picture("m", "M", None, required=True)),))],
        levels=False,
        rendered=date(2026, 11, 11),
        words={"eyebrow": "Rapport", "contents": "Sommaire", "figure_missing": "Absente"},
    )
    text = page.read_text()
    assert "Rapport" in text and "Sommaire" in text and "Absente" in text
    assert "Contents" not in text and 'class="pill">standard' not in text
