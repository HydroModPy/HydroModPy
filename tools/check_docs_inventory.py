from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_SOURCE = ROOT / "docs" / "source"
CLI_REFERENCE = DOC_SOURCE / "cli" / "index.rst"
API_REFERENCE = DOC_SOURCE / "api" / "index.rst"
USER_GUIDE_INDEX = DOC_SOURCE / "user_guide" / "index.rst"

COMMAND_PATTERN = re.compile(r"``hmp ([a-z0-9-]+)[^`]*``")

IGNORED_AUTHORED_PARTS = {
    "_static",
    "api/generated",
    "capability_gallery/cases",
}

BANNED_AUTHORED_PATTERNS = {
    "hmp migrate": "The public CLI does not register a migration command.",
    "examples_legacy_2": "Legacy example paths should not appear in authored docs.",
}

REQUIRED_API_PAGES = {
    "hydromodpy.run",
    "hydromodpy.calibrate",
    "hydromodpy.open",
    "hydromodpy.config",
    "hydromodpy.analysis",
}

REQUIRED_USER_GUIDE_PAGES = {
    "data/index",
}

# --- guide page floor -------------------------------------------------------
#
# The documentation is written by three machines: a generator (the config
# reference, whose floor is the JSON schema), recursive autosummary (removed:
# its floor was zero) and hand writing, which had no floor at all. The two
# checks below are that floor. Both use a shrinking allowlist: a page listed
# there is a known debt, and once it complies it must be REMOVED from the list,
# so the count can only go down.

USER_GUIDE_DIR = DOC_SOURCE / "user_guide"
GENERATED_GUIDE_DIRS = ("config_reference",)

CROSSREF_ROLE = re.compile(r":(?:doc|ref|mod|class|func|meth|attr|term|option|numref|cite):`")
CROSSREF_ALLOWLIST = ROOT / "tools" / "docs_crossref_allowlist.txt"

# One page per data family, following user_guide/data/dem.rst.
DATA_DIR = USER_GUIDE_DIR / "data"
DATA_REQUIRED_HEADINGS = ("Accepted sources", "Minimal example", "Downstream uses")
DATA_NON_FAMILY_PAGES = {
    "index.rst",
    "cache-and-lockfiles.rst",
    "custom-data.rst",
    "provider-replay-cases.rst",
    "retrieval-workflow.rst",
    "runs-and-figures.rst",
}
DATA_TEMPLATE_ALLOWLIST = ROOT / "tools" / "docs_data_template_allowlist.txt"

# The recursive autosummary produced 1290 pages of which 11 rendered a single
# Python object, and those empty pages owned the search index: searchtools.js
# scores a matching py:module at 26 against 15 for a page title and 5 for body
# text. Re-adding :recursive: silently undoes that.
# --- CLI literals, anywhere ---------------------------------------------------
#
# A dead "hmp <verb>" is worse inside the package than inside a page: a Pydantic
# Field description is republished verbatim into the generated configuration
# reference, so one wrong string ships on several pages. That is how
# "editable later via 'hmp tag'" reached two generated pages while the verb had
# never existed under that name.
#
# The lookbehind excludes ".hmp archive", ".hmp packaging" and the rest of the
# noun phrases built on the portable ".hmp" file format, which is what the
# format is called and not a command.
# Only a delimited literal or the start of a code-block line counts as a
# command. Bare mid-sentence text is prose: "conda create -n hmp python=3.12"
# names an environment, not a verb.
HMP_COMMAND_RE = re.compile(
    r"(?:[`'\"]|^[ \t]*\$?[ \t]*)hmp[ \t]+([a-z][a-z0-9-]{1,30})(?:[ \t]+([a-z][a-z0-9-]{1,30}))?",
    re.M,
)
HMP_SCAN_ROOTS = ("hydromodpy", "docs/source")
HMP_SCAN_SUFFIXES = (".py", ".rst", ".md")
CLI_LITERAL_ALLOWLIST = ROOT / "tools" / "docs_cli_literal_allowlist.txt"

# --- gallery artifacts ---------------------------------------------------------
#
# The gallery is written twice: a summary JSON per case, and a page generated
# from it. Both name repository files in the open -- the config a case reads,
# the tolerances it is judged against, the module that draws its figure -- and
# both survive a rename without a word, because a page that names a dead file
# still builds. Five calibration pages named a "docs/readthedocs/" prefix this
# layout has never had, and one named a tolerances file deleted months later.
# So the two are scanned together, against one shrinking allowlist.
GALLERY_JSON_DIR = DOC_SOURCE / "_static" / "capability_gallery"
GALLERY_PAGE_DIR = DOC_SOURCE / "capability_gallery"
# validation_cases was missing from this alternation, so every tolerances and
# config file a validation summary names was invisible to the check.
REPO_PATH_RE = re.compile(r'"((?:docs|examples|hydromodpy|tests|tools|validation_cases)/[^"]+)"')
# A page names its paths in prose and in literals, not inside JSON quotes, so
# the boundary is the surrounding text. The lookbehind stops a match from
# starting in the middle of a longer path.
PAGE_REPO_PATH_RE = re.compile(
    r"(?<![\w/.-])((?:docs|examples|hydromodpy|tests|tools|validation_cases)/[A-Za-z0-9_./-]+)"
)
PAGE_PATH_TRAILING = ".,;:)`'\""
GALLERY_PATH_ALLOWLIST = ROOT / "tools" / "docs_gallery_path_allowlist.txt"

# A case records the digest of every source it was published from. Nothing read
# those digests: ``--check`` compares a regenerated tree against the committed
# one, which needs the solver, the data and the fonts of the producing machine,
# so CI only runs it on four of the nine categories. A digest comparison needs
# none of that. It answers the question the four-category check cannot: has a
# published case fallen behind the files it declares it was made from.
GALLERY_SOURCE_HASH_ALLOWLIST = ROOT / "tools" / "docs_gallery_stale_source_allowlist.txt"

# --- parser floors -------------------------------------------------------------
#
# Every check here works by matching a pattern. A pattern that stops matching
# reports success, so a reformat, a renamed directory or a broken glob silently
# disables the check instead of failing it. These floors are the tripwire: they
# are set well below today's counts and only fire when a scan collapses.
PARSER_FLOORS = {
    "authored user_guide pages": 40,
    "hmp command literals": 200,
    "gallery json files": 90,
    "gallery pages": 70,
    "gallery page paths": 1000,
    "gallery source digests": 600,
    "config_reference pages": 20,
}

RECURSIVE_BANNED_IN = (
    DOC_SOURCE / "api" / "index.rst",
    DOC_SOURCE / "_templates" / "autosummary" / "module.rst",
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def registered_cli_commands() -> set[str]:
    from hydromodpy.cli.commands import ALL_COMMANDS

    return {getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1]) for module in ALL_COMMANDS}


def documented_cli_commands(path: Path = CLI_REFERENCE) -> set[str]:
    """Collect ``hmp <verb>`` literals across the CLI reference section.

    The reference is a section, not a single page: the index lists the
    families and each family page documents its own verbs.
    """
    documented: set[str] = set()
    for page in sorted(path.parent.rglob("*.rst")):
        documented.update(COMMAND_PATTERN.findall(page.read_text(encoding="utf-8")))
    return documented


def _is_ignored_doc(path: Path) -> bool:
    rel = path.relative_to(DOC_SOURCE).as_posix()
    return any(rel.startswith(part + "/") for part in IGNORED_AUTHORED_PARTS)


def authored_rst_files() -> list[Path]:
    return [path for path in DOC_SOURCE.rglob("*.rst") if not _is_ignored_doc(path)]


def check_cli_reference() -> list[str]:
    registered = registered_cli_commands()
    documented = documented_cli_commands()
    missing = sorted(registered - documented)
    extra = sorted(documented - registered)

    errors: list[str] = []
    if missing:
        errors.append(f"CLI reference is missing registered commands: {', '.join(missing)}")
    if extra:
        errors.append(f"CLI reference documents unregistered commands: {', '.join(extra)}")
    return errors


def check_banned_authored_references() -> list[str]:
    errors: list[str] = []
    for path in authored_rst_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern, reason in BANNED_AUTHORED_PATTERNS.items():
            if pattern in text:
                rel = path.relative_to(ROOT).as_posix()
                errors.append(f"{rel}: found {pattern!r}. {reason}")
    return errors


def check_api_reference_pages() -> list[str]:
    text = API_REFERENCE.read_text(encoding="utf-8")
    missing = sorted(page for page in REQUIRED_API_PAGES if page not in text)
    if missing:
        return [f"api-reference.rst is missing required API pages: {', '.join(missing)}"]
    return []


def check_user_guide_pages() -> list[str]:
    text = USER_GUIDE_INDEX.read_text(encoding="utf-8")
    missing = sorted(page for page in REQUIRED_USER_GUIDE_PAGES if page not in text)
    if missing:
        return [f"user_guide/index.rst is missing required guide pages: {', '.join(missing)}"]
    return []


def _read_allowlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def _authored_user_guide_pages() -> list[Path]:
    """Hand-written user_guide pages, excluding the generated reference."""
    pages = []
    for path in sorted(USER_GUIDE_DIR.rglob("*.rst")):
        rel = path.relative_to(USER_GUIDE_DIR).as_posix()
        if any(rel.startswith(part + "/") for part in GENERATED_GUIDE_DIRS):
            continue
        if path.name.endswith(".partial.rst"):
            continue
        pages.append(path)
    return pages


def _check_against_allowlist(violations: set[str], allowlist_path: Path, what: str) -> list[str]:
    """Ratchet: no new violation, and a fixed page must leave the allowlist."""
    errors: list[str] = []
    allowed = set(_read_allowlist(allowlist_path))
    rel_allowlist = allowlist_path.relative_to(ROOT).as_posix()

    for rel in sorted(violations - allowed):
        errors.append(f"{rel}: {what}")

    for rel in sorted(allowed - violations):
        target = ROOT / rel
        if not target.exists():
            errors.append(f"{rel_allowlist} lists {rel}, which no longer exists. Remove the line.")
        else:
            errors.append(
                f"{rel} now complies. Remove it from {rel_allowlist}; the list only shrinks."
            )
    return errors


def check_user_guide_crossrefs() -> list[str]:
    """Every hand-written guide page must link somewhere."""
    violations = {
        path.relative_to(ROOT).as_posix()
        for path in _authored_user_guide_pages()
        if not CROSSREF_ROLE.search(path.read_text(encoding="utf-8", errors="ignore"))
    }
    return _check_against_allowlist(
        violations,
        CROSSREF_ALLOWLIST,
        "carries no cross-reference role. A guide page that links nowhere is a dead end; "
        "link the fields it names to /user_guide/config_reference/.",
    )


def _rst_headings(text: str) -> set[str]:
    lines = text.splitlines()
    headings: set[str] = set()
    for i in range(len(lines) - 1):
        title, rule = lines[i].strip(), lines[i + 1].strip()
        if not title or len(rule) < len(title):
            continue
        if len(set(rule)) == 1 and rule[0] in "=-^~\"'+*#:":
            headings.add(title)
    return headings


def check_data_pages_follow_template() -> list[str]:
    """Every data family page must follow user_guide/data/dem.rst."""
    violations: set[str] = set()
    for path in sorted(DATA_DIR.glob("*.rst")):
        if path.name in DATA_NON_FAMILY_PAGES:
            continue
        headings = _rst_headings(path.read_text(encoding="utf-8", errors="ignore"))
        if not all(required in headings for required in DATA_REQUIRED_HEADINGS):
            violations.add(path.relative_to(ROOT).as_posix())
    return _check_against_allowlist(
        violations,
        DATA_TEMPLATE_ALLOWLIST,
        "does not follow user_guide/data/dem.rst. Required sections: "
        + ", ".join(DATA_REQUIRED_HEADINGS)
        + ".",
    )


def check_api_reference_is_not_recursive() -> list[str]:
    errors: list[str] = []
    for path in RECURSIVE_BANNED_IN:
        if not path.exists():
            continue
        if ":recursive:" in path.read_text(encoding="utf-8"):
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: ':recursive:' is banned. It generated "
                "1290 pages of which 11 documented a Python object, and they dominated the "
                "site search."
            )
    return errors


def _scan_hmp_literals() -> list[tuple[str, str, str | None]]:
    """Every "hmp <verb> [<action>]" literal in the package and the docs."""
    found: list[tuple[str, str, str | None]] = []
    for root in HMP_SCAN_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in HMP_SCAN_SUFFIXES or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in HMP_COMMAND_RE.finditer(text):
                found.append((path.relative_to(ROOT).as_posix(), match.group(1), match.group(2)))
    return found


def _registered_actions() -> dict[str, set[str]]:
    from hydromodpy.cli.commands import ALL_COMMANDS

    families: dict[str, set[str]] = {}
    for module in ALL_COMMANDS:
        name = getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1])
        actions = getattr(module, "ACTIONS", ())
        families[name] = {
            getattr(action, "NAME", action.__name__.rsplit(".", 1)[-1]) for action in actions
        }
    return families


def check_cli_literals_resolve() -> list[str]:
    """No text anywhere may name a command the argparse tree does not register."""
    families = _registered_actions()
    literals = _scan_hmp_literals()

    errors: list[str] = []
    if len(literals) < PARSER_FLOORS["hmp command literals"]:
        errors.append(
            f"the hmp literal scan matched only {len(literals)} times, below the floor of "
            f"{PARSER_FLOORS['hmp command literals']}. The pattern has probably stopped matching."
        )

    violations: set[str] = set()
    for rel, verb, action in literals:
        if verb not in families:
            violations.add(f"{rel}: 'hmp {verb}' is not a registered verb")
        elif action and families[verb] and action not in families[verb]:
            violations.add(f"{rel}: 'hmp {verb} {action}' is not an action of the {verb} family")

    return errors + _check_against_allowlist(
        violations,
        CLI_LITERAL_ALLOWLIST,
        "names a command the CLI does not register.",
    )


def _scan_gallery_summaries() -> tuple[int, set[str]]:
    files = sorted(GALLERY_JSON_DIR.rglob("*.json"))
    violations: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in REPO_PATH_RE.finditer(text):
            if not (ROOT / match.group(1)).exists():
                violations.add(f"{path.relative_to(ROOT).as_posix()}: {match.group(1)}")
    return len(files), violations


def _scan_gallery_pages() -> tuple[int, int, set[str]]:
    pages = sorted(GALLERY_PAGE_DIR.rglob("*.rst"))
    named = 0
    violations: set[str] = set()
    for page in pages:
        text = page.read_text(encoding="utf-8", errors="ignore")
        seen: set[str] = set()
        for match in PAGE_REPO_PATH_RE.finditer(text):
            candidate = match.group(1).rstrip(PAGE_PATH_TRAILING)
            if candidate in seen:
                continue
            seen.add(candidate)
            named += 1
            if not (ROOT / candidate).exists():
                violations.add(f"{page.relative_to(ROOT).as_posix()}: {candidate}")
    return len(pages), named, violations


def check_gallery_paths_exist() -> list[str]:
    """Every repository path a generated gallery artifact names must exist."""
    missing_roots = [
        directory.relative_to(ROOT).as_posix()
        for directory in (GALLERY_JSON_DIR, GALLERY_PAGE_DIR)
        if not directory.exists()
    ]
    if missing_roots:
        return [f"{name} is missing" for name in missing_roots]

    summary_count, violations = _scan_gallery_summaries()
    page_count, named_paths, page_violations = _scan_gallery_pages()
    violations |= page_violations

    errors: list[str] = []
    for label, count in (
        ("gallery json files", summary_count),
        ("gallery pages", page_count),
        ("gallery page paths", named_paths),
    ):
        if count < PARSER_FLOORS[label]:
            errors.append(
                f"{label}: found {count}, below the floor of {PARSER_FLOORS[label]}. "
                "The scan has probably stopped matching."
            )

    return errors + _check_against_allowlist(
        violations,
        GALLERY_PATH_ALLOWLIST,
        "points at a repository path that does not exist.",
    )


def check_gallery_sources_are_current() -> list[str]:
    """Every source a published gallery case declares must still hash the same."""
    from tools.doc_gallery.update_gallery import MISSING_SOURCE_HASH, _sha256

    if not GALLERY_JSON_DIR.exists():
        return [f"{GALLERY_JSON_DIR.relative_to(ROOT).as_posix()} is missing"]

    declared = 0
    errors: list[str] = []
    violations: set[str] = set()
    for path in sorted(GALLERY_JSON_DIR.rglob("*_summary.json")):
        rel_summary = path.relative_to(ROOT).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"{rel_summary}: is not readable JSON ({exc})")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{rel_summary}: is not a JSON object")
            continue
        hashes = payload.get("source_hashes")
        if hashes is None:
            # The two calibration intercomparison decks declare no sources of
            # their own: they are assembled from the case summaries beside them,
            # which are checked here on their own account.
            continue
        if not isinstance(hashes, dict):
            errors.append(f"{rel_summary}: source_hashes is {type(hashes).__name__}, not an object")
            continue
        for source, expected in hashes.items():
            if not isinstance(source, str) or not isinstance(expected, str):
                errors.append(f"{rel_summary}: source_hashes holds a non-string entry")
                continue
            declared += 1
            source_path = ROOT / source
            if not source_path.is_file():
                # A source the repository does not carry is the other check's
                # business; counting it here would report one debt twice.
                continue
            if expected == MISSING_SOURCE_HASH or _sha256(source_path) != expected:
                # One line per case, not per source: a case is republished as a
                # whole, so a per-source ledger would carry four hundred lines
                # that clear in blocks of ten. The cost of that choice is that a
                # case already listed can fall further behind without a visible
                # diff; the line says the case is stale, never by how much.
                violations.add(rel_summary)

    if declared < PARSER_FLOORS["gallery source digests"]:
        errors.append(
            f"gallery source digests: found {declared}, below the floor of "
            f"{PARSER_FLOORS['gallery source digests']}. The scan has probably "
            "stopped matching."
        )

    return errors + _check_against_allowlist(
        violations,
        GALLERY_SOURCE_HASH_ALLOWLIST,
        "is behind at least one source it declares. Regenerate the case.",
    )


def check_parser_floors() -> list[str]:
    """The scans that back the other checks must still be matching something."""
    errors: list[str] = []
    counts = {
        "authored user_guide pages": len(_authored_user_guide_pages()),
        "config_reference pages": len(list((USER_GUIDE_DIR / "config_reference").glob("*.rst"))),
    }
    for label, count in counts.items():
        floor = PARSER_FLOORS[label]
        if count < floor:
            errors.append(
                f"{label}: found {count}, below the floor of {floor}. A check is scanning nothing."
            )
    return errors


def run_checks() -> list[str]:
    errors: list[str] = []
    errors.extend(check_cli_reference())
    errors.extend(check_banned_authored_references())
    errors.extend(check_api_reference_pages())
    errors.extend(check_user_guide_pages())
    errors.extend(check_user_guide_crossrefs())
    errors.extend(check_data_pages_follow_template())
    errors.extend(check_api_reference_is_not_recursive())
    errors.extend(check_cli_literals_resolve())
    errors.extend(check_gallery_paths_exist())
    errors.extend(check_gallery_sources_are_current())
    errors.extend(check_parser_floors())
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that authored documentation inventories match public code surfaces."
    )
    parser.parse_args(argv)

    errors = run_checks()
    if not errors:
        print("Documentation inventory checks passed.")
        return 0

    print("Documentation inventory checks failed:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
