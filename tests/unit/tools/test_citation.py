"""The citation entries of the Cite page come from CITATION.cff and say what it says."""

from __future__ import annotations

import pytest

from tools.docs import citation

CFF = citation.load()
VERSION = "2.0.0a4"
DOI = CFF["preferred-citation"]["doi"]


def test_every_format_names_the_version_the_doi_and_every_author() -> None:
    family_names = [a["family-names"] for a in CFF["authors"]]
    assert family_names == [a["family-names"] for a in CFF["preferred-citation"]["authors"]]
    for fmt in citation.FORMATS:
        out = citation.render(fmt, CFF, VERSION, "2026")
        assert VERSION in out, fmt
        assert DOI in out, fmt
        # BibTeX writes the accents as TeX, so compare on the ASCII part of the name.
        for family in family_names:
            probe = citation.tex(family) if fmt == "bibtex" else family
            assert probe in out, (fmt, family)


def test_bibtex_stays_ascii_and_keeps_the_accents_as_tex() -> None:
    out = citation.bibtex(CFF, VERSION, "2026")
    assert out.isascii()
    assert r"Abherv{\'e}" in out
    assert r"Mar{\c c}ais" in out
    assert out.count("@article{") == 1
    assert out.count("@software{") == 1


def test_bibtex_without_a_known_year_omits_it_for_the_software() -> None:
    soft = citation.bibtex(CFF, "9.9.9").split("@software")[1]
    assert "year" not in soft
    assert "version = {9.9.9}" in soft


def test_ris_has_one_author_line_per_author_and_two_records() -> None:
    out = citation.ris(CFF, VERSION, "2026")
    assert out.count("\nER  - ") + out.startswith("ER  - ") == 2
    assert out.count("AU  - ") == 2 * len(CFF["authors"])
    assert "AU  - Abhervé, Ronan" in out
    assert f"IS  - {CFF['preferred-citation']['issue']}" in out


def test_text_uses_initials_and_the_ampersand_before_the_last_author() -> None:
    out = citation.text(CFF, VERSION, "2026")
    flat = " ".join(out.split())
    assert "Gauvain, A., Abhervé, R." in flat
    assert "& de Dreuzy, J.-R. (2026)" in flat
    assert "(Version 2.0.0a4) [Computer software]" in flat


@pytest.mark.parametrize(
    ("given", "expected"),
    [("Jean-Raynald", "J.-R."), ("Rock S.", "R. S."), ("Théa", "T."), ("Alexandre", "A.")],
)
def test_initials(given: str, expected: str) -> None:
    assert citation.initials(given) == expected


def test_release_year_reads_the_changelog_headings() -> None:
    log = "## [Unreleased]\n\n## [v2.0.0a4] - 2026-09-29\n\n## [v0.3.3] - 2025-12-03\n"
    assert citation.release_year(log, "2.0.0a4") == "2026"
    assert citation.release_year(log, "0.3.3") == "2025"
    assert citation.release_year(log, "2.0.0a5") is None


@pytest.mark.parametrize("word", ["Abhervé", "Marçais", "Servière", "Théa", "Pélissier"])
def test_untex_undoes_tex(word: str) -> None:
    assert citation.untex(citation.tex(word)) == word


def test_untex_reads_the_forms_a_bib_file_uses() -> None:
    assert citation.untex(r"Abherv\'e") == "Abhervé"
    assert citation.untex(r"Servi{\`e}re") == "Servière"
    assert citation.untex(r"Mar\c{c}ais") == "Marçais"
    assert citation.untex("pages 1--31") == "pages 1–31"


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown citation format"):
        citation.render("endnote", CFF, VERSION)
