"""Every message a guide quotes in "What can go wrong" is printed by the code.

A table that names a message the code no longer prints sends the reader after
text that never appears. The scan reads the first column of the tables, keeps
the code spans that look like a message and looks for them among the string
literals of the package (``tools/docs/quoted_messages.py``). Messages of other
tools (MODFLOW, pandas, pydantic, the operating system) are listed with their
tool in ``quoted_messages_external.toml``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tools.docs import quoted_messages as qm

EXTERNAL = Path(__file__).with_name("quoted_messages_external.toml")
# The scan found about 410 quotes when this test was written. Far fewer means the
# table reader stopped matching, not that the guides got cleaner.
FLOOR = 300


def _external() -> list[dict[str, str]]:
    return tomllib.loads(EXTERNAL.read_text(encoding="utf-8"))["external"]


@pytest.fixture(scope="module")
def quotes() -> list[qm.Quoted]:
    return qm.all_quotes()


def test_the_scan_reads_the_tables(quotes: list[qm.Quoted]) -> None:
    assert len(quotes) >= FLOOR


def test_every_quoted_message_is_in_the_code() -> None:
    allowed = tuple(entry["match"] for entry in _external())
    lost = [f"{q.page}:{q.line}: {q.span[:120]}" for q in qm.missing(allowed)]
    assert not lost, "messages that the code does not print:\n" + "\n".join(lost)


def test_every_external_entry_is_used(quotes: list[qm.Quoted]) -> None:
    unused = [
        entry["match"]
        for entry in _external()
        if not any(entry["match"] in quote.span for quote in quotes)
    ]
    assert not unused, f"entries that no table quotes any more: {unused}"


def test_every_external_entry_names_its_tool() -> None:
    for entry in _external():
        assert entry["tool"].strip() and entry["reason"].strip(), entry


def test_a_reworded_message_is_caught(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "mod.py").write_text(
        "def f(name, count):\n"
        "    raise ValueError(\n"
        "        f'Unknown unit {name!r} for the recharge series. '\n"
        "        'Write a volume per time.'\n"
        "    )\n",
        encoding="utf-8",
    )
    page = tmp_path / "page.md"
    page.write_text(
        "## What can go wrong\n\n"
        "| Symptom | Cause | Fix |\n|---|---|---|\n"
        "| `Unknown unit 'mm' for the recharge series. Write a volume per time.` | a | b |\n"
        "| `Unknown unit 'mm' for the recharge table. Give a depth per time.` | a | b |\n",
        encoding="utf-8",
    )
    corpus = qm.code_corpus(package)
    found = qm.quoted_messages(page)
    assert len(found) == 2
    assert [qm.unexplained(q, corpus) for q in found] == [False, True]
