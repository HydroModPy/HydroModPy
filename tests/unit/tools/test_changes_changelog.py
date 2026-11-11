"""The Numbers block of the changelog is written from the register, between two comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.schema.changes import Register, read
from tools import changes_changelog as numbers

HEAD = 'schema = "hydromodpy.changes.v1"\n'


def _bug(row_id: str, since: str, text: str) -> str:
    return (
        f'[[bug]]\nid = "{row_id}"\nsince = "{since}"\nversions = "<{since}"\n'
        f'quantities = ["metrics"]\ntext = "{text}"\n'
    )


def _recipe(row_id: str, since: str, effect: str, text: str) -> str:
    quantities = '["metrics"]' if effect == "numbers" else "[]"
    return (
        f'[[recipe]]\nid = "{row_id}"\nsince = "{since}"\neffect = "{effect}"\n'
        f'quantities = {quantities}\ntext = "{text}"\n'
    )


DEFAULT = (
    '[[default]]\nid = "d"\nsince = "2.1.0"\nedition = "2.1"\nkey = "solver.x"\nold = 0.5\n'
    'new = 0.45\nquantities = ["metrics"]\ntext = "A default."\n'
)

MIGRATION = '[[migration]]\ndocument = "config"\nold = "a.b"\nnew = "a.c"\nsince = "2.1.0"\n'

REGISTER_TEXT = (
    HEAD
    + _recipe("late_number", "2.1.0", "numbers", "A recipe that moves a number.")
    + _recipe("a_refusal", "2.1.0", "refusal", "A recipe that refuses.")
    + DEFAULT
    + _bug("old_bug", "2.0.0", "A bug of the published release.")
    + _bug("new_bug", "2.1.0", "A bug fixed after it.")
    + MIGRATION
)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- Something.

## [v2.0.0] - 2026-11-07

### Numbers

- A published line.
"""

BLOCK = "- A bug fixed after it.\n- A default.\n- A recipe that moves a number.\n"


@pytest.fixture(scope="module")
def register() -> Register:
    return read(REGISTER_TEXT)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (CHANGELOG, "2.0.0"),
        ("## [Unreleased]\n\n## [v2.0.0a5] - 2026-10-13\n\n## [v2.0.0a4] - x\n", "2.0.0a5"),
        ("## [Unreleased]\n\n## [v1.0.0] - 2026-08-10\n", "1.0.0"),
    ],
    ids=["a release", "a pre-release", "the first release"],
)
def test_the_last_release_is_the_first_published_section(text: str, expected: str) -> None:
    assert numbers.last_release(text) == expected


def test_a_changelog_without_a_published_section_is_refused() -> None:
    with pytest.raises(ValueError, match="no published section"):
        numbers.last_release("## [Unreleased]\n")


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        ("2.0.0", ["A bug fixed after it.", "A default.", "A recipe that moves a number."]),
        (
            "2.0.0a5",
            [
                "A bug of the published release.",
                "A bug fixed after it.",
                "A default.",
                "A recipe that moves a number.",
            ],
        ),
        ("2.1.0", []),
    ],
    ids=["after 2.0.0", "after a pre-release", "after 2.1.0"],
)
def test_the_bullets_are_the_numbers_rows_after_the_release(
    register: Register, after: str, expected: list[str]
) -> None:
    assert numbers.bullets(register, after) == [f"- {text}" for text in expected]


def test_a_refusal_and_a_migration_are_not_bullets(register: Register) -> None:
    joined = "\n".join(numbers.bullets(register, "1.0.0"))
    assert "refuses" not in joined
    assert "a.b" not in joined


def test_a_default_without_a_quantity_is_not_a_bullet() -> None:
    quiet = DEFAULT.replace('id = "d"', 'id = "quiet"').replace('["metrics"]', "[]")
    register = read(HEAD + quiet.replace("A default.", "A default that moves nothing."))

    assert numbers.bullets(register, "2.0.0") == []


def test_the_section_is_made_at_the_end_of_unreleased(register: Register) -> None:
    out = numbers.rewrite(CHANGELOG, register)

    expected = (
        "- Something.\n\n### Numbers\n\n"
        f"{numbers.BEGIN}\n{BLOCK}{numbers.END}\n\n## [v2.0.0] - 2026-11-07"
    )
    assert expected in out
    # What was published is untouched.
    assert out.endswith("### Numbers\n\n- A published line.\n")
    assert numbers.rewrite(out, register) == out


def test_the_block_between_the_comments_is_replaced_and_the_rest_kept(
    register: Register,
) -> None:
    before = CHANGELOG.replace(
        "- Something.\n",
        f"- Something.\n\n### Numbers\n\nA hand-written line.\n\n{numbers.BEGIN}\n- stale\n"
        f"{numbers.END}\n\nAnother hand-written line.\n",
    )

    out = numbers.rewrite(before, register)

    assert f"{numbers.BEGIN}\n{BLOCK}{numbers.END}" in out
    assert "stale" not in out
    assert "A hand-written line." in out and "Another hand-written line." in out


def test_a_register_with_no_number_leaves_a_changelog_without_comments_alone() -> None:
    quiet = read(HEAD + _bug("old_bug", "2.0.0", "Published."))

    assert numbers.rewrite(CHANGELOG, quiet) == CHANGELOG


def test_a_register_with_no_number_empties_the_comments_it_finds() -> None:
    quiet = read(HEAD + _bug("old_bug", "2.0.0", "Published."))
    held = CHANGELOG.replace("- Something.\n", f"{numbers.BEGIN}\n- stale\n{numbers.END}\n")

    out = numbers.rewrite(held, quiet)

    assert f"{numbers.BEGIN}\n{numbers.END}" in out
    assert numbers.rewrite(out, quiet) == out


@pytest.mark.parametrize(
    "marks",
    [
        numbers.BEGIN,
        numbers.END,
        f"{numbers.END}\n{numbers.BEGIN}",
        f"{numbers.BEGIN}\n{numbers.END}\n{numbers.BEGIN}\n{numbers.END}",
    ],
    ids=["no end", "no begin", "end first", "twice"],
)
def test_comments_that_are_not_one_pair_are_refused(register: Register, marks: str) -> None:
    held = CHANGELOG.replace("- Something.\n", f"{marks}\n")

    with pytest.raises(ValueError, match="one <!-- numbers:begin"):
        numbers.rewrite(held, register)


def test_a_changelog_without_unreleased_is_refused(register: Register) -> None:
    with pytest.raises(ValueError, match="no '## \\[Unreleased\\]'"):
        numbers.rewrite("## [v2.0.0] - x\n", register)


def test_the_check_says_the_difference_and_the_write_fixes_it(
    tmp_path: Path, register: Register, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    args = ["--changelog", str(path)]

    assert numbers.main(args, register) == 1
    err = capsys.readouterr().err
    assert "+- A default." in err and "--write" in err
    assert path.read_text(encoding="utf-8") == CHANGELOG

    assert numbers.main([*args, "--write"], register) == 0
    assert numbers.main(args, register) == 0
    assert "- A default." in path.read_text(encoding="utf-8")


def test_a_changelog_the_tool_cannot_read_exits_with_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## [v2.0.0] - x\n", encoding="utf-8")

    assert numbers.main(["--changelog", str(path)]) == 2
    assert "no '## [Unreleased]'" in capsys.readouterr().err
