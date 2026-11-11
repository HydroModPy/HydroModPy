"""Check and raise the coverage floor of each sub-package from one table.

The table is ``tools/ci/coverage_floors.toml``. Each key is the path of a
sub-package (``hydromodpy/core/budget``) or ``<package>/*.py`` for the modules
at the top of a package. A file counts in the deepest key that holds it.

Usage::

    python tools/ci/coverage_floors.py check tools/ci/coverage_floors.toml
    python tools/ci/coverage_floors.py measure tools/ci/coverage_floors.toml --write

Both commands read the combined coverage file, ``$COVERAGE_FILE`` when it is set
and ``.coverage`` otherwise, as coverage itself does. The measure of a key is the
share of its lines and branches that ran, as ``coverage report`` computes it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

from coverage import Coverage, CoverageData

SOURCE = "hydromodpy"
FILES_KEY = "/*.py"
MARGIN = 0.5
LINE = re.compile(r'^(\s*)"(?P<key>[^"]+)"(\s*=\s*)(?P<value>[0-9.]+)(?P<rest>.*)$')


class FloorError(Exception):
    """A floor table or a coverage file that the command cannot use."""


def repo_root() -> Path:
    """Return the repository root from the location of this file."""
    return Path(__file__).resolve().parents[2]


def load_floors(table: Path) -> dict[str, float]:
    """Read the ``[floors]`` table and refuse a value that is not a percentage."""
    try:
        payload = tomllib.loads(table.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FloorError(f"{table} does not exist") from None
    except tomllib.TOMLDecodeError as error:
        raise FloorError(f"{table} is not valid TOML: {error}") from None
    floors = payload.get("floors")
    if not isinstance(floors, dict) or not floors:
        raise FloorError(f"{table} has no [floors] table")
    for key, value in floors.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
            raise FloorError(
                f"the floor of {key} is {value!r}: it must be a percentage from 0 to 100"
            )
    return {key: float(value) for key, value in floors.items()}


def package_files(root: Path) -> list[Path]:
    """Return every module that sits inside a package of ``hydromodpy``."""
    files: list[Path] = []
    for package in sorted((root / SOURCE).iterdir()):
        if package.is_dir() and not package.name.startswith(("_", ".")):
            files.extend(sorted(package.rglob("*.py")))
    return files


def tree_keys(root: Path) -> list[str]:
    """Return the keys the tree needs: one per package and per second-level sub-package."""
    keys: list[str] = []
    for package in sorted((root / SOURCE).iterdir()):
        if not package.is_dir() or package.name.startswith(("_", ".")):
            continue
        if any(package.glob("*.py")):
            keys.append(f"{SOURCE}/{package.name}{FILES_KEY}")
        for sub in sorted(package.iterdir()):
            if sub.is_dir() and not sub.name.startswith(("_", ".")) and any(sub.rglob("*.py")):
                keys.append(f"{SOURCE}/{package.name}/{sub.name}")
    return keys


def key_base(key: str) -> str:
    """Return the folder a key stands for."""
    return key.removesuffix(FILES_KEY)


def assign_files(root: Path, keys: Sequence[str]) -> dict[str, list[Path]]:
    """Give each module to its deepest key. A key that holds no module maps to ``[]``."""
    holders: dict[str, list[Path]] = {key: [] for key in keys}
    for path in package_files(root):
        folder = path.parent.relative_to(root).as_posix()
        best: tuple[int, int, str] | None = None
        for key in keys:
            base = key_base(key)
            is_files = key.endswith(FILES_KEY)
            if folder != base and (is_files or not folder.startswith(base + "/")):
                continue
            rank = (len(base), int(is_files), key)
            if best is None or rank[:2] > best[:2]:
                best = rank
        if best is not None:
            holders[best[2]].append(path)
    return holders


def read_counts(data_file: Path, root: Path, files: Sequence[Path]) -> dict[Path, tuple[int, int]]:
    """Return ``{file: (covered, total)}`` counting lines and branches together."""
    if not data_file.is_file():
        raise FloorError(f"{data_file} does not exist: run coverage combine first")
    data = CoverageData(basename=str(data_file))
    data.read()
    measured = [Path(name) for name in data.measured_files()]
    if not any(path.is_relative_to(root) for path in measured):
        raise FloorError(f"{data_file} holds no file under {root}: the data come from another tree")
    if not data.has_arcs():
        raise FloorError(f"{data_file} holds no branch data: run pytest with --cov-branch")
    coverage = Coverage(data_file=str(data_file), config_file=False, branch=True)
    coverage.load()
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "report.json"
        coverage.json_report(morfs=[str(path) for path in files], outfile=str(out))
        report = json.loads(out.read_text(encoding="utf-8"))
    counts: dict[Path, tuple[int, int]] = {}
    for name, entry in report["files"].items():
        summary = entry["summary"]
        path = (Path.cwd() / name).resolve()
        covered = summary["covered_lines"] + summary.get("covered_branches", 0)
        total = summary["num_statements"] + summary.get("num_branches", 0)
        counts[path] = (covered, total)
    return counts


def measure_keys(
    data_file: Path, root: Path, keys: Sequence[str]
) -> tuple[dict[str, float], list[str]]:
    """Return the measure of each key and the keys that name no module."""
    holders = assign_files(root, keys)
    absent = [key for key, held in holders.items() if not held]
    wanted = [path for held in holders.values() for path in held]
    counts = read_counts(data_file, root, wanted) if wanted else {}
    measures: dict[str, float] = {}
    for key, held in holders.items():
        if not held:
            continue
        covered = sum(counts.get(path.resolve(), (0, 0))[0] for path in held)
        total = sum(counts.get(path.resolve(), (0, 0))[1] for path in held)
        measures[key] = 100.0 if total == 0 else 100.0 * covered / total
    return measures, absent


def raised(old: float, measure: float) -> float:
    """Return the floor after a measure: the measure minus 0.5, rounded down to 0.5, never lower."""
    return max(old, math.floor((measure - MARGIN) * 2 + 1e-9) / 2, 0.0)


def check(table: Path, data_file: Path, root: Path) -> list[str]:
    """Return one line per floor that fails, per missing line and per absent path."""
    floors = load_floors(table)
    measures, absent = measure_keys(data_file, root, list(floors))
    problems = [
        f"{key} names no module of the tree: fix the path or remove the line" for key in absent
    ]
    problems += [
        f"{key} has no floor: run coverage_floors.py measure"
        for key in tree_keys(root)
        if key not in floors
    ]
    for key, measure in measures.items():
        if round(measure, 2) < floors[key]:
            problems.append(f"{key} {measure:.2f} < {floors[key]:.1f}")
    return problems


def render(table: Path, new_floors: dict[str, float]) -> str:
    """Return the table text with the new values, in place, and new keys in sorted position."""
    lines = table.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        found = LINE.match(line)
        if found and found["key"] in new_floors:
            key = found["key"]
            seen.add(key)
            lines[index] = f'{found[1]}"{key}"{found[3]}{new_floors[key]:.1f}{found["rest"]}'
    for key in sorted(set(new_floors) - seen):
        slots = [(i, LINE.match(line)) for i, line in enumerate(lines)]
        slots = [(i, m["key"]) for i, m in slots if m]
        after = [i for i, other in slots if other > key]
        if after:
            at = after[0]
        elif slots:
            at = slots[-1][0] + 1
        else:
            at = next(i for i, line in enumerate(lines) if line.strip() == "[floors]") + 1
        lines.insert(at, f'"{key}" = {new_floors[key]:.1f}')
    return "\n".join(lines) + "\n"


def measure(table: Path, data_file: Path, root: Path, write: bool) -> tuple[list[str], list[str]]:
    """Return the report lines and the absent keys. With ``write`` the table is raised."""
    floors = load_floors(table)
    keys = sorted(set(floors) | set(tree_keys(root)))
    measures, absent = measure_keys(data_file, root, keys)
    new_floors = {key: raised(floors.get(key, 0.0), value) for key, value in measures.items()}
    report = [
        f"{key} {measures[key]:.2f} {floors[key]:.1f} -> {new_floors[key]:.1f}"
        if key in floors
        else f"{key} {measures[key]:.2f} new -> {new_floors[key]:.1f}"
        for key in sorted(measures)
    ]
    if write:
        table.write_text(render(table, new_floors), encoding="utf-8")
    return report, [
        f"{key} names no module of the tree: fix the path or remove the line" for key in absent
    ]


def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("check", "fail when a floor is missed, missing or names no module"),
        ("measure", "print the measure of each key and raise the floors with --write"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("table", type=Path, help="the floors table (TOML)")
        command.add_argument(
            "--data-file", type=Path, default=Path(os.environ.get("COVERAGE_FILE", ".coverage"))
        )
        command.add_argument(
            "--root", type=Path, default=repo_root(), help="the tree that was measured"
        )
        if name == "measure":
            command.add_argument("--write", action="store_true", help="rewrite the table in place")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "check":
            problems = check(args.table, args.data_file.resolve(), root)
            for line in problems:
                print(line)
            if not problems:
                print(f"{len(load_floors(args.table))} floors hold")
            return 1 if problems else 0
        report, absent = measure(args.table, args.data_file.resolve(), root, args.write)
    except FloorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for line in report + absent:
        print(line)
    return 1 if absent else 0


if __name__ == "__main__":
    raise SystemExit(main())
