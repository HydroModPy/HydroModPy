"""Merge the measured results of the validation tests into the documentation snapshot.

Usage:
  python -m tools.docs.validation_results merge SOURCE... [--snapshot PATH] [--replace]
  python -m tools.docs.validation_results fetch [--branch dev] [--run-id ID] [--snapshot PATH]

A validation run writes one ``part-*.json`` per pytest process when
``HMP_VALIDATION_RESULTS`` names a directory (see ``tests/validation/conftest.py``).
``merge`` reads such directories, part files, or a merged file (the artifact of
the nightly job), and writes the snapshot that the Validation page reads:
``docs/source/theory/validation_results.json``. A test keeps its newest result;
a test the run did not reach keeps the result of an older run, with that run's
date and commit. ``--replace`` drops every older result instead.

``fetch`` downloads, with the GitHub CLI (``gh``), the artifact each nightly
validation workflow leaves for one branch: ``validation-results-<branch>`` from
``ci-nightly.yml`` and ``validation-results-petsc-<branch>`` from
``ci-nightly-petsc.yml``. It takes the latest completed run of each workflow,
passed or failed, and merges what it found. A missing artifact is reported and
skipped; ``fetch`` fails only when it finds none.

Local run, then refresh:
  HMP_VALIDATION_RESULTS=/some/dir pytest tests/validation -m fast -n 2
  python -m tools.docs.validation_results merge /some/dir
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs" / "source" / "theory" / "validation_results.json"
SCHEMA = 1
NIGHTLY = (
    ("ci-nightly.yml", "validation-results-{branch}"),
    ("ci-nightly-petsc.yml", "validation-results-petsc-{branch}"),
)
"""Each nightly validation workflow and the name of its artifact for one branch."""


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: schema {data.get('schema')!r}, expected {SCHEMA}")
    return data


def run_key(facts: dict[str, Any]) -> str:
    """A stable name for one run: its end date and its commit."""
    return f"{facts.get('date', '')}-{(facts.get('commit') or 'nocommit')[:9]}"


def _parts(source: Path) -> list[Path]:
    if source.is_dir():
        return sorted(source.glob("part-*.json"))
    return [source]


def collect(sources: list[Path]) -> dict[str, Any]:
    """Read part files and merged files into one snapshot-shaped payload.

    The parts of one directory are one run: the run keeps the facts of its
    earliest part and the date of its latest one, the end of the run.
    """
    out: dict[str, Any] = {"schema": SCHEMA, "runs": {}, "tests": {}}
    for source in sources:
        parts = [_load(p) for p in _parts(source)]
        merged = [p for p in parts if "runs" in p]
        for snap in merged:
            out["runs"].update(snap["runs"])
            out["tests"].update(snap["tests"])
        loose = [p for p in parts if "run" in p]
        if not loose:
            continue
        facts = dict(min((p["run"] for p in loose), key=lambda f: f.get("date", "")))
        facts["date"] = max(p["run"].get("date", "") for p in loose)
        key = run_key(facts)
        out["runs"][key] = facts
        for part in loose:
            for test in part["tests"]:
                out["tests"][test["nodeid"]] = {**test, "run": key}
    return out


def merge(
    snapshot: dict[str, Any], new: dict[str, Any], *, replace: bool, repo: Path = ROOT
) -> dict[str, Any]:
    """Return the snapshot with the newer results of ``new`` laid over it."""
    tests = {} if replace else dict(snapshot.get("tests", {}))
    runs = {} if replace else dict(snapshot.get("runs", {}))
    runs.update(new["runs"])
    for nodeid, test in new["tests"].items():
        old = tests.get(nodeid)
        if old is None or runs.get(old["run"], {}).get("date", "") <= runs[test["run"]]["date"]:
            tests[nodeid] = test
    # A test file that left the tree takes its results with it.
    tests = {k: v for k, v in tests.items() if (repo / v["file"]).exists()}
    used = {t["run"] for t in tests.values()}
    return {
        "schema": SCHEMA,
        "runs": {k: runs[k] for k in sorted(used)},
        "tests": dict(sorted(tests.items())),
    }


def _is_numeric(value: Any) -> bool:
    """True for a number, a null, or a list of them, nested at any depth."""
    if isinstance(value, list):
        return all(_is_numeric(v) for v in value)
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _dumps(value: Any, depth: int = 0) -> str:
    """JSON with one key per line and every array of numbers on one line.

    One number per line made the maps and fields of the snapshot several times
    larger than their content, and its diffs unreadable.
    """
    pad = " " * (depth + 1)
    if isinstance(value, dict) and value:
        items = [
            f"{pad}{json.dumps(k, ensure_ascii=False)}: {_dumps(v, depth + 1)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + " " * depth + "}"
    if isinstance(value, list) and value and not _is_numeric(value):
        items = [f"{pad}{_dumps(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * depth + "]"
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":") if isinstance(value, list) else None
    )


def write(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(payload) + "\n")


def cmd_merge(args: argparse.Namespace) -> int:
    path = Path(args.snapshot)
    old = _load(path) if path.exists() and not args.replace else {"runs": {}, "tests": {}}
    new = collect([Path(s) for s in args.sources])
    if not new["tests"]:
        raise SystemExit("no validation result in the sources")
    payload = merge(old, new, replace=args.replace)
    write(payload, path)
    print(f"{path}: {len(payload['tests'])} tests from {len(payload['runs'])} runs")
    return 0


def _latest_completed_run(workflow: str) -> str:
    """The id of the latest completed run of ``workflow``, or an empty string."""
    listed = subprocess.run(
        ["gh", "run", "list", "--workflow", workflow, "--status", "completed", "--limit", "1"]
        + ["--json", "databaseId", "--jq", ".[0].databaseId"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return listed.stdout.strip() if listed.returncode == 0 else ""


def cmd_fetch(args: argparse.Namespace) -> int:
    pairs = [(wf, name.format(branch=args.branch)) for wf, name in NIGHTLY]
    if args.run_id:
        pairs = [(args.run_id, name) for _, name in pairs]
    with tempfile.TemporaryDirectory() as tmp:
        found: list[str] = []
        for source, name in pairs:
            run_id = source if args.run_id else _latest_completed_run(source)
            if not run_id:
                print(f"no completed run of {source}: {name} skipped")
                continue
            target = Path(tmp) / name
            done = subprocess.run(
                ["gh", "run", "download", run_id, "--name", name, "--dir", str(target)],
                cwd=ROOT,
            )
            if done.returncode != 0:
                print(f"run {run_id} has no artifact {name}: skipped")
                continue
            found.extend(str(p) for p in sorted(target.glob("*.json")))
        if not found:
            raise SystemExit(f"no validation result artifact found for branch {args.branch}")
        args.sources = found
        args.replace = False
        return cmd_merge(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("merge", help="merge local parts or a downloaded artifact")
    m.add_argument("sources", nargs="+", help="part directories or JSON files")
    m.add_argument("--snapshot", default=str(SNAPSHOT))
    m.add_argument("--replace", action="store_true", help="drop the results of older runs")
    m.set_defaults(func=cmd_merge)
    f = sub.add_parser("fetch", help="download the nightly artifacts with gh, then merge them")
    f.add_argument("--branch", default="dev")
    f.add_argument("--run-id", default="", help="read both artifact names from this one run")
    f.add_argument("--snapshot", default=str(SNAPSHOT))
    f.set_defaults(func=cmd_fetch)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
