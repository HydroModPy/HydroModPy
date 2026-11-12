"""The page check catches a wrong key, a dead link, a bad block and a key written without its role.

It reads ``docs/source/_data/registry.json`` and the pages under ``docs/source``,
so each test writes a small docs tree under ``tmp_path`` and points the module
at it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.docs import check_page, field_registry

KEY = "simulation.time.start_datetime"
SENTENCE = (
    "write the key {role}`simulation.time.start_datetime` "
    "so its card gives the default and the unit"
)


@pytest.fixture(scope="module")
def registry() -> dict:
    payload, _gates = field_registry.build_payload("test")
    return payload


@pytest.fixture()
def page_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: dict):
    """A docs tree with one existing page and the registry the check reads."""
    src = tmp_path / "docs" / "source"
    (src / "_data").mkdir(parents=True)
    (src / "_data" / "registry.json").write_text(json.dumps(registry))
    (src / "guides").mkdir()
    (src / "guides" / "other.md").write_text("# Other\n")
    monkeypatch.setattr(check_page, "SRC", src)
    return src


def run_check(page: Path) -> list[str]:
    return check_page.check(page, check_page.Registry(), check_page.docnames())


def test_the_page_check_accepts_a_clean_page(page_env: Path) -> None:
    page = page_env / "guides" / "good.md"
    page.write_text(
        "# Good\n\nSet {toml}`the start|simulation.time.start_datetime` and read {doc}`other`.\n\n"
        "```{hmp-params}\nsimulation.time.start_datetime\n```\n"
    )
    assert run_check(page) == []


def test_the_page_check_catches_an_unknown_key_a_dead_link_and_a_bad_block(page_env: Path) -> None:
    page = page_env / "guides" / "bad.md"
    page.write_text(
        "# Bad\n\nSet {toml}`simulation.time.no_such_key` and read {doc}`missing`.\n\n"
        "```toml\n[simulation\n```\n"
    )
    joined = "\n".join(run_check(page))
    assert "unknown TOML path: simulation.time.no_such_key" in joined
    assert "link to a page that does not exist: missing" in joined
    assert "TOML syntax" in joined


def test_a_block_marked_not_checked_is_skipped(page_env: Path) -> None:
    page = page_env / "guides" / "skip.md"
    page.write_text(
        "# Skip\n\n```toml\n# not checked: a mistake on purpose\n[workflow]\nmode = 3\n```\n"
    )
    assert run_check(page) == []


MARKDOWN_ROWS = [
    pytest.param(
        f"Set `{KEY}` to a date.\n",
        [f"guides/p.md:3: {SENTENCE.format(role='{toml}')}"],
        id="a key outside the role is refused",
    ),
    pytest.param(
        f"Set {{toml}}`{KEY}` to a date.\n",
        [],
        id="a key inside the role is accepted",
    ),
    pytest.param(
        f"Set {{toml}}`the start|{KEY}` to a date.\n",
        [],
        id="a key inside the role with a label is accepted",
    ),
    pytest.param(
        f"```text\nuse `{KEY}` here\n```\n",
        [],
        id="a key in a code block is accepted",
    ),
    pytest.param(
        f"```{{hmp-toml}}\n# not checked: shown as written\nuse = `{KEY}`\n```\n",
        [],
        id="a key in a hmp-toml block is accepted",
    ),
    pytest.param(
        "Call `solver.backend_name` and `time` and `simulation.time.no_key_here`.\n",
        [],
        id="a text equal to no key is accepted",
    ),
    pytest.param(
        f"Set `{KEY} = 3` to a date.\n",
        [],
        id="a text longer than a key is accepted",
    ),
    pytest.param(
        f":::{{note}}\nSet `{KEY}` first.\n:::\n",
        [f"guides/p.md:4: {SENTENCE.format(role='{toml}')}"],
        id="a key in an admonition is refused",
    ),
    pytest.param(
        f"Set `{KEY}` and `{KEY}`.\n",
        [f"guides/p.md:3: {SENTENCE.format(role='{toml}')}"] * 2,
        id="each key of a line is refused",
    ),
]


@pytest.mark.parametrize(("body", "expected"), MARKDOWN_ROWS)
def test_a_key_of_the_registry_goes_through_the_toml_role_in_markdown(
    page_env: Path, body: str, expected: list[str]
) -> None:
    page = page_env / "guides" / "p.md"
    page.write_text("# P\n\n" + body)
    problems = [p for p in run_check(page) if "so its card gives" in p]
    assert problems == expected


RST_ROWS = [
    pytest.param(
        f"Set ``{KEY}`` to a date.\n",
        [f"guides/r.rst:4: {SENTENCE.format(role=':toml:')}"],
        id="a literal outside the role is refused",
    ),
    pytest.param(
        f"Set :toml:`{KEY}` to a date.\n",
        [],
        id="a key inside the role is accepted",
    ),
    pytest.param(
        f".. code-block:: text\n\n   use ``{KEY}`` here\n\nAfter.\n",
        [],
        id="a key in a code block is accepted",
    ),
    pytest.param(
        f".. code-block:: text\n\n   use here\n\nSet ``{KEY}`` after the block.\n",
        [f"guides/r.rst:8: {SENTENCE.format(role=':toml:')}"],
        id="a key after a code block is refused",
    ),
]


@pytest.mark.parametrize(("body", "expected"), RST_ROWS)
def test_a_key_of_the_registry_goes_through_the_toml_role_in_restructuredtext(
    page_env: Path, body: str, expected: list[str]
) -> None:
    page = page_env / "guides" / "r.rst"
    page.write_text("Title\n=====\n\n" + body)
    problems = [p for p in run_check(page) if "so its card gives" in p]
    assert problems == expected


def test_the_page_of_history_may_write_a_key_as_it_was(
    page_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (page_env / "about").mkdir()
    page = page_env / "about" / "changes-during-the-alphas.md"
    page.write_text(f"# Alphas\n\nThe key `{KEY}` moved.\n")
    assert run_check(page) == []


def test_french_is_read_without_the_code_and_the_names_of_places() -> None:
    assert check_page.looks_french("Le modèle est une couche.")
    assert check_page.looks_french("An accent in café is enough.")
    assert not check_page.looks_french("The model reads `le la des` from a table.")
    assert not check_page.looks_french("The Nançon basin is small.")


def test_a_cited_path_must_exist_and_a_placeholder_is_skipped(page_env: Path) -> None:
    root = page_env.parents[1]
    (root / "hydromodpy").mkdir()
    (root / "hydromodpy" / "real.py").write_text("")
    page = page_env / "guides" / "paths.md"
    page.write_text(
        "# Paths\n\nSee `hydromodpy/real.py`, `hydromodpy/real.py:12` and `hydromodpy/<pkg>/a.py`,\n"
        "also `tests/*.py`, `tools/{a,b}`, `docs/...` and `tools/gone.py` or `other/gone.py`.\n\n"
        "```text\nhydromodpy/inside_a_block.py\n```\n"
    )
    problems = run_check(page)
    assert len(problems) == 1
    assert "guides/paths.md:4" in problems[0]
    assert problems[0].endswith("tools/gone.py")


def test_the_history_page_may_cite_a_gone_path(page_env: Path) -> None:
    (page_env / "about").mkdir()
    page = page_env / "about" / "changes-during-the-alphas.md"
    page.write_text("# History\n\nThe file `hydromodpy/gone.py` was removed.\n")
    assert run_check(page) == []
