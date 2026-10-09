"""The About pages hold no copy of what a file of the repository already says."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tools.docs import citation

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "docs" / "source"
ABOUT = SRC / "about"
CFF = citation.load()


def _bib_keys() -> dict[str, str]:
    """BibTeX key to DOI, for every entry of the theory bibliography."""
    text = (SRC / "theory" / "references.bib").read_text(encoding="utf-8")
    keys = {}
    for match in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", text, re.S):
        doi = re.search(r"doi\s*=\s*\{([^}]+)\}", match.group(2))
        keys[match.group(1)] = doi.group(1) if doi else ""
    return keys


def test_every_study_cites_an_entry_of_the_bibliography_once() -> None:
    studies = yaml.safe_load((ABOUT / "applications.yaml").read_text(encoding="utf-8"))["studies"]
    bib = _bib_keys()
    keys = [s["bib"] for s in studies]
    assert len(keys) == len(set(keys)), "a study is listed twice"
    assert not [k for k in keys if k not in bib], (
        "a study cites a key that is not in references.bib"
    )
    assert all(s["use"].strip() for s in studies)
    dois = [bib[k] for k in keys]
    assert all(dois), "every study has a DOI in the bibliography"


def test_every_author_of_the_citation_file_has_affiliations_and_none_is_unused() -> None:
    data = yaml.safe_load((ABOUT / "affiliations.yaml").read_text(encoding="utf-8"))
    families = [a["family-names"] for a in CFF["authors"]]
    assert sorted(data["authors"]) == sorted(families)
    used = {n for numbers in data["authors"].values() for n in numbers}
    assert used == set(data["institutions"])


def test_the_cite_page_gives_the_doi_of_the_citation_file() -> None:
    text = (ABOUT / "cite.md").read_text(encoding="utf-8")
    assert CFF["preferred-citation"]["doi"] in text


def test_the_about_toctree_lists_every_page_of_the_door() -> None:
    index = (ABOUT / "index.md").read_text(encoding="utf-8")
    toctree = index.split("```{toctree}", 1)[1]
    listed = set(re.findall(r"<([a-z-]+)>", toctree))
    pages = {p.stem for p in ABOUT.glob("*.md") if p.stem != "index"}
    assert listed == pages


def test_no_stale_statement_comes_back() -> None:
    banned = ("not tagged", "Zenodo", "Leaflet", "Phase 3", "roadmap", "Documentation refresh")
    for page in ABOUT.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        found = [word for word in banned if word.lower() in text.lower()]
        assert not found, f"{page.name} says {found}"
        assert "—" not in text, f"{page.name} has an em dash"


def test_the_pages_that_state_a_version_read_it_from_the_release() -> None:
    for name in ("cite.md", "versions.md"):
        assert "{{ release }}" in (ABOUT / name).read_text(encoding="utf-8")
