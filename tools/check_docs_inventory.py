from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_SOURCE = ROOT / "docs" / "readthedocs" / "source"
CLI_REFERENCE = DOC_SOURCE / "user_guide" / "cli-reference.rst"
API_REFERENCE = DOC_SOURCE / "api-reference.rst"

COMMAND_PATTERN = re.compile(r"``hmp ([a-z0-9-]+)``")

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
    "api/hydromodpy-project-results",
    "api/hydromodpy-data",
    "api/hydromodpy-workflow-pipeline",
    "api/hydromodpy-analysis-calibration",
    "api/hydromodpy-schema",
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def registered_cli_commands() -> set[str]:
    from hydromodpy._cli.commands import ALL_COMMANDS

    return {getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1]) for module in ALL_COMMANDS}


def documented_cli_commands(path: Path = CLI_REFERENCE) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(COMMAND_PATTERN.findall(text))


def _is_ignored_doc(path: Path) -> bool:
    rel = path.relative_to(DOC_SOURCE).as_posix()
    return any(rel.startswith(part + "/") for part in IGNORED_AUTHORED_PARTS)


def authored_rst_files() -> list[Path]:
    return [
        path
        for path in DOC_SOURCE.rglob("*.rst")
        if not _is_ignored_doc(path)
    ]


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


def run_checks() -> list[str]:
    errors: list[str] = []
    errors.extend(check_cli_reference())
    errors.extend(check_banned_authored_references())
    errors.extend(check_api_reference_pages())
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
