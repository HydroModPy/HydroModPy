"""Prove in CI that the tests a change removes lose nothing.

This file picks the tests to measure and calls ``removal_proof.py``, which does the proof.
It measures no coverage and plays no mutant itself. Exit code 0 means proved, 1 a loss
(named), 2 an input it refuses (one sentence on stderr).

    select  find the test functions a change removes and the tests that stand for them
    prove   measure both sides and run ``removal_proof.py check`` on the selection
    range   select and prove each commit of a push against its parent
    week    select and prove every commit of a period that removes tests

``select`` reads the change with git and exports both commits under ``--work`` by
``git archive``, never in the checkout. A change that removes no test gives an empty
selection and no export, which is the case of almost every push. ``prove`` compares the
same library code only, so a change that also edits ``hydromodpy/`` is refused. A push
holds many commits, so ``range`` proves each commit against its parent: a commit that
both removes tests and edits ``hydromodpy/`` is refused, while a push that does the two
in separate commits passes.

The proof answers for the modules of the removed tests (their packages in the package
scope). The tests measured on each side are the importers of those modules, so a line
of another module that only the removed tests ran in that measure may still be run by
a test outside it. Such a loss is listed under ``outside_bound`` and does not fail.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

SELECTION_FORMAT = "hmp-ci-selection/1"
REPORT_FORMAT = "hmp-ci-proof/1"
WEEK_FORMAT = "hmp-ci-proof-week/1"
RANGE_FORMAT = "hmp-ci-proof-range/1"
PHRASES = {
    "revision": (
        "{rev} is not a commit of this clone: "
        "fetch the history of the base (fetch-depth: 0) and give a commit that exists."
    ),
    "git": "git {args} failed: {message}",
    "selection": "{path} is not a selection written by `proof.py select`: run select first.",
    "trees": "{tree} is not there: run `proof.py select` with the same --work first.",
}
VERDICTS = ("none", "bounded", "alone", "changed")
LOST_PREFIX = "lost"
OUTSIDE_PREFIX = "outside the bound, not counted"


class Refusal(Exception):
    """An input the tool refuses. The message names the expected form."""


def refuse(key: str, **fields: object) -> NoReturn:
    raise Refusal(PHRASES[key].format(**fields))


def prover() -> ModuleType:
    """The module of ``removal_proof.py`` beside this file, loaded without a copy."""
    for name in ("tools.ci.removal_proof", "removal_proof"):
        if name in sys.modules:
            return sys.modules[name]
    path = Path(__file__).resolve().with_name("removal_proof.py")
    spec = importlib.util.spec_from_file_location("removal_proof", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["removal_proof"] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip()
        refuse("git", args=" ".join(args), message=message)
    return done.stdout


def resolve(repo: Path, rev: str) -> str:
    """The full sha of a commit, or a refusal when the clone does not hold it."""
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not rev or done.returncode != 0 or not done.stdout.strip():
        refuse("revision", rev=rev or "an empty revision")
    return done.stdout.strip()


def is_test_file(rel: str) -> bool:
    return rel.startswith("tests/") and rel.endswith(".py") and Path(rel).name.startswith("test_")


def touched_tests(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    """Test files that differ between two commits, as (status, path), a rename being D and A."""
    out = git(repo, "diff", "--name-status", "--no-renames", "-z", base, head, "--", "tests")
    tokens = out.decode("utf-8").split("\0")
    pairs = zip(tokens[0::2], tokens[1::2], strict=False)
    return [(status, rel) for status, rel in pairs if is_test_file(rel)]


def test_ids(rel: str, text: str) -> set[str] | None:
    """Node ids of the test functions of a file, or None when the file does not parse."""
    try:
        module = ast.parse(text)
    except SyntaxError:
        return None
    return {f.id for f in prover().test_functions(module, rel)}


def ids_at(repo: Path, sha: str, rel: str) -> set[str] | None:
    text = git(repo, "cat-file", "blob", f"{sha}:{rel}").decode("utf-8")
    return test_ids(rel, text)


def export(repo: Path, sha: str, target: Path) -> None:
    """Write the files of a commit under ``target`` with ``git archive``."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    cmd = ["git", "-C", str(repo), "archive", "--format=tar", sha]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as archive:
        assert archive.stdout is not None and archive.stderr is not None
        unreadable = ""
        try:
            with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
                tar.extractall(target, filter="data")
        except tarfile.TarError as error:
            unreadable = str(error)  # when git failed, its stderr says why just below
        message = archive.stderr.read().decode("utf-8", "replace").strip()
        if archive.wait() != 0 or unreadable:
            refuse("git", args=f"archive {sha}", message=message or unreadable)


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


def note_skipped(skipped: list[str], rel: str) -> None:
    if rel not in skipped:
        skipped.append(rel)


def importers(tree: Path, modules: set[str], skipped: list[str]) -> list[str]:
    """Test files of a tree that import one of the library modules."""
    rp = prover()
    index = rp.build_index(tree)
    found = []
    for path in sorted((tree / "tests").rglob("test_*.py")):
        rel = str(path.relative_to(tree))
        if "__pycache__" in path.parts:
            continue
        try:
            scanned = rp.scan_file(tree, rel)
        except (SyntaxError, UnicodeDecodeError):
            note_skipped(skipped, rel)
            continue
        if rp.subjects_of(scanned, index) & modules:
            found.append(rel)
    return found


def removed_functions(
    repo: Path, base: str, head: str, skipped: list[str]
) -> tuple[list[str], list[str]]:
    """Test functions gone between the commits, and the test files added or modified."""
    removed: list[str] = []
    changed: list[str] = []
    for status, rel in touched_tests(repo, base, head):
        before = ids_at(repo, base, rel) if status in ("D", "M") else set()
        after = ids_at(repo, head, rel) if status in ("A", "M") else set()
        if before is None or after is None:
            note_skipped(skipped, rel)
            continue
        if status in ("A", "M"):
            changed.append(rel)
        removed.extend(sorted(before - after))
    return sorted(removed), sorted(changed)


def select(repo: Path, base: str, head: str, work: Path) -> dict[str, Any]:
    """The selection of a change: what leaves, and the tests to measure on each side."""
    rp = prover()
    base, head = resolve(repo, base), resolve(repo, head)
    skipped: list[str] = []
    removed, changed = removed_functions(repo, base, head, skipped)
    selection: dict[str, Any] = {
        "format": SELECTION_FORMAT,
        "repo": str(repo),
        "base": base,
        "head": head,
        "verdict": "none",
        "removed": removed,
        "files": sorted({fid.split("::", 1)[0] for fid in removed}),
        "modules": [],
        "without_module": [],
        "base_tree": None,
        "head_tree": None,
        "tests_base": [],
        "tests_head": [],
        "skipped": skipped,
    }
    if not removed:
        return selection
    if git(repo, "diff", "--name-only", base, head, "--", "hydromodpy").strip():
        # git tracks every file of hydromodpy/ that package_digest reads, so a
        # change seen here is a change of the digest, found without an export.
        selection["verdict"] = "changed"
        return selection
    base_tree, head_tree = work / "base", work / "head"
    export(repo, base, base_tree)
    export(repo, head, head_tree)
    selection["base_tree"], selection["head_tree"] = str(base_tree), str(head_tree)
    index = rp.build_index(base_tree)
    scanned = rp.scan_files(base_tree, selection["files"], index)
    subjects = {rel: set(scanned[rel].subjects) for rel in scanned}
    modules = set().union(*subjects.values())
    selection["modules"] = sorted(modules)
    selection["without_module"] = sorted(rel for rel, found in subjects.items() if not found)
    standing = importers(head_tree, modules, skipped) if modules else []
    tests_head = sorted({*standing, *(rel for rel in changed if (head_tree / rel).is_file())})
    tests_base = sorted({*importers(base_tree, modules, skipped), *selection["files"]})
    selection["tests_base"], selection["tests_head"] = tests_base, tests_head
    selection["verdict"] = "bounded" if tests_head else "alone"
    return selection


# ---------------------------------------------------------------------------
# prove
# ---------------------------------------------------------------------------


def run_tool(command: Sequence[str]) -> tuple[int, str]:
    """Run a command, pass its stderr through, and return its code and last stderr line."""
    last = ""
    with subprocess.Popen(
        list(command), stderr=subprocess.PIPE, text=True, errors="replace"
    ) as process:
        assert process.stderr is not None
        for line in process.stderr:
            sys.stderr.write(line)
            last = line.strip() or last
        return process.wait(), last


def tool(action: str, *args: str) -> list[str]:
    return [sys.executable, str(Path(prover().__file__).resolve()), action, *args]


def measure_command(tree: str, out: Path, tests: Sequence[str], options: dict) -> list[str]:
    command = tool(
        "measure", "--tree", tree, "--out", str(out), "--workers", str(options["workers"])
    )
    command += ["--tests", *tests]
    return command + (["--ignore", *options["ignore"]] if options["ignore"] else [])


def describe_losses(check: dict) -> list[str]:
    """One line per lost item of a check result, naming the file, the mutant or the test."""
    lines = []
    for path, item in check.get("lost_coverage", {}).items():
        by = ", ".join(item.get("covered_by", [])[:3]) or "the removed tests"
        lines.append(
            f"{LOST_PREFIX} coverage: {path}, {item.get('lines_count', 0)} lines and "
            f"{item.get('arcs_count', 0)} branches, run by {by}"
        )
    for mutant in check.get("lost_mutants", []):
        killer = mutant.get("killer") or "a removed test"
        lines.append(
            f"{LOST_PREFIX} mutant: {mutant['name']} in {mutant['function']}, "
            f"{mutant['status']}, killed before by {killer}"
        )
    lines.extend(f"unaccounted test: {fid}" for fid in check.get("unaccounted_ids", []))
    lines.extend(
        f"module not proved, its tests fail with no mutant: {m}"
        for m in check.get("baseline_errors", [])
    )
    restore = check.get("restore_files", [])
    if restore:
        lines.append("put back: " + ", ".join(restore))
    for path, item in check.get("outside_bound", {}).items():
        lines.append(
            f"{OUTSIDE_PREFIX}: {path}, {item.get('lines_count', 0)} lines and "
            f"{item.get('arcs_count', 0)} branches"
        )
    return lines


def bound_files(selection: dict, scope: str) -> set[str]:
    """Library files the proof answers for: the modules of the selection, or their packages."""
    modules = set(selection["modules"])
    if scope != "package" or not modules:
        return modules
    rp = prover()
    return rp.package_modules(rp.build_index(Path(selection["base_tree"])), modules)


def bound_check(check: dict, files: set[str]) -> dict:
    """Keep the coverage losses of the bound files and list the others apart.

    The put-back list is rebuilt from what stays counted, so it names no test file for a
    loss outside the bound.
    """
    lost = check.get("lost_coverage", {})
    outside = {path: item for path, item in lost.items() if path not in files}
    check = check | {"bound": sorted(files)}
    if not outside:
        return check
    kept = {path: item for path, item in lost.items() if path in files}
    restore = {fid for item in kept.values() for fid in item.get("covered_by", [])}
    restore |= {
        fid for mutant in check.get("lost_mutants", []) for fid in mutant.get("put_back", [])
    }
    restore |= set(check.get("unaccounted_ids", []))
    return check | {
        "lost_coverage": kept,
        "outside_bound": outside,
        "restore_files": sorted({fid.split("::", 1)[0] for fid in restore}),
    }


def has_loss(check: dict) -> bool:
    lost = check["lost_coverage"] or check["lost_mutants"] or check["unaccounted_ids"]
    return bool(lost or check["baseline_errors"])


def prove_alone(selection: dict, work: Path, options: dict) -> tuple[int, dict | None, str | None]:
    """Prove removed tests whose modules no test left imports.

    The removed tests are measured alone first. The library files they run become the
    modules of the selection, and the tests that import one of them are measured on
    each side and checked as a bounded selection. When no test left imports any of
    them, every line the removed tests ran is lost.
    """
    rp = prover()
    out = work / "measure-removed"
    code, last = run_tool(
        measure_command(selection["base_tree"], out, selection["tests_base"], options)
    )
    if code != 0:
        return code, None, last
    cov, _ = rp.load_measure(out, Path(selection["base_tree"]))
    covered: dict[str, dict] = {}
    for context, files in cov.items.items():
        for path, items in files.items():
            if items:
                item = covered.setdefault(path, {"items": set(), "covered_by": []})
                item["items"] |= items
                item["covered_by"].append(context)
    ran, skipped = set(covered), selection["skipped"]
    standing = importers(Path(selection["head_tree"]), ran, skipped) if ran else []
    if standing:
        before = importers(Path(selection["base_tree"]), ran, skipped)
        widened = selection | {
            "modules": sorted(ran),
            "tests_base": sorted({*before, *selection["files"]}),
            "tests_head": standing,
        }
        return prove_bounded(widened, work, options)
    lost = {
        path: {
            "lines_count": len(rp.lines_of(item["items"], cov.arcs)),
            "arcs_count": len(item["items"]) if cov.arcs else 0,
            "covered_by": sorted(item["covered_by"])[:20],
        }
        for path, item in sorted(covered.items())
    }
    check = {
        "lost_coverage": lost,
        "lost_mutants": [],
        "unaccounted_ids": [],
        "baseline_errors": [],
        "restore_files": sorted(selection["files"]) if lost else [],
        "estimated_minutes": 0.0,
    }
    return (1 if lost else 0), check, None


def prove_bounded(
    selection: dict, work: Path, options: dict
) -> tuple[int, dict | None, str | None]:
    """Measure both sides on their own tests, then run ``check`` on the two measures."""
    for label, key in (("base", "tests_base"), ("head", "tests_head")):
        tree = selection[f"{label}_tree"]
        command = measure_command(tree, work / f"measure-{label}", selection[key], options)
        code, last = run_tool(command)
        if code != 0:
            return code, None, last
    out = work / "check.json"
    command = tool(
        "check",
        *("--before", selection["base_tree"], "--after", selection["head_tree"]),
        *("--measure-before", str(work / "measure-base")),
        *("--measure-after", str(work / "measure-head")),
        *("--mutmut", options["mutmut"], "--work", str(work / "check"), "--out", str(out)),
        *("--scope", options["scope"], "--budget-minutes", str(options["budget_minutes"])),
        *("--processes", str(options["processes"]), "--runner", options["runner"]),
    )
    code, last = run_tool(command)
    check = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    if check is not None and code in (0, 1):
        check = bound_check(check, bound_files(selection, options["scope"]))
        code = 1 if has_loss(check) else 0
    return code, check, last if code == 2 else None


def prove_selection(selection: dict, work: Path, options: dict) -> tuple[int, dict]:
    """Prove one selection. Returns the exit code and the report."""
    started = time.monotonic()
    verdict = selection["verdict"]
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "base": selection["base"],
        "head": selection["head"],
        "scope": options["scope"],
        "verdict": verdict,
        "removed": len(selection["removed"]),
        "files": selection["files"],
        "modules": selection["modules"],
        "tests_base": len(selection["tests_base"]),
        "tests_head": len(selection["tests_head"]),
        "exit_code": 0,
        "refusal": None,
        "check": None,
        "losses": [],
    }
    code, check, refusal = 0, None, None
    if verdict == "changed":
        code, refusal = 2, prover().PHRASES["differs"]
    elif verdict in ("bounded", "alone"):
        for tree in (selection["base_tree"], selection["head_tree"]):
            if not Path(tree).is_dir():
                refuse("trees", tree=tree)
        step = prove_bounded if verdict == "bounded" else prove_alone
        code, check, refusal = step(selection, work, options)
    report.update(exit_code=code, refusal=refusal, check=check)
    report["losses"] = describe_losses(check) if check else []
    report["seconds"] = round(time.monotonic() - started, 1)
    return code, report


def load_selection(path: Path) -> dict:
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refuse("selection", path=path)
    if not isinstance(selection, dict) or selection.get("format") != SELECTION_FORMAT:
        refuse("selection", path=path)
    if selection.get("verdict") not in VERDICTS:
        refuse("selection", path=path)
    return selection


# ---------------------------------------------------------------------------
# week
# ---------------------------------------------------------------------------


def trim(folder: Path) -> None:
    """Keep the JSON files of a commit folder and drop the exports and the measures."""
    for child in folder.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        elif child.suffix != ".json":
            child.unlink()


def is_budget_refusal(text: str | None) -> bool:
    return bool(text) and text.startswith(prover().PHRASES["budget"].split("{", 1)[0])  # type: ignore[union-attr]


def commits_since(repo: Path, since: str, head: str) -> list[str]:
    out = git(repo, "log", f"--since={since}", "--no-merges", "--reverse", "--format=%H", head)
    return out.decode("utf-8").split()


def commits_between(repo: Path, base: str, head: str) -> list[str]:
    out = git(repo, "rev-list", "--reverse", "--no-merges", f"{base}..{head}")
    return out.decode("utf-8").split()


def week(repo: Path, since: str, head: str, work: Path, options: dict) -> tuple[int, dict]:
    """Prove each commit of a period that removes tests, against its parent, in one budget.

    A commit that also edits ``hydromodpy/`` is listed as changed without a proof,
    because a weekly job has no change to refuse.
    """
    head = resolve(repo, head)
    worst, result = prove_commits(repo, commits_since(repo, since, head), work, options, False)
    return worst, {"format": WEEK_FORMAT, "since": since, "head": head, **result}


def push_range(repo: Path, base: str, head: str, work: Path, options: dict) -> tuple[int, dict]:
    """Prove each commit of a push, against its parent, in one budget.

    A commit that removes tests and edits ``hydromodpy/`` is refused with exit 2. A
    commit past the budget is listed as left and does not fail the push.
    """
    base, head = resolve(repo, base), resolve(repo, head)
    worst, result = prove_commits(repo, commits_between(repo, base, head), work, options, True)
    return worst, {"format": RANGE_FORMAT, "base": base, "head": head, **result}


def prove_commits(
    repo: Path, shas: Sequence[str], work: Path, options: dict, refuse_changed: bool
) -> tuple[int, dict]:
    """Select and prove each commit against its parent. Returns the worst code and the lists."""
    started = time.monotonic()
    budget = float(options["budget_minutes"])
    lists: dict[str, list] = {k: [] for k in ("proved", "lost", "changed", "left", "refused")}
    spent, scanned, worst = 0.0, 0, 0
    for sha in shas:
        try:
            parent = resolve(repo, f"{sha}^")
        except Refusal:
            continue  # the first commit of the history has nothing to compare with
        scanned += 1
        folder = work / sha[:12]
        selection = select(repo, parent, sha, folder)
        if selection["verdict"] == "none":
            shutil.rmtree(folder, ignore_errors=True)
            continue
        subject = git(repo, "log", "-1", "--format=%s", sha).decode("utf-8").strip()
        entry: dict[str, Any] = {"commit": sha, "subject": subject, "files": selection["files"]}
        remaining = budget - spent
        if selection["verdict"] == "changed":
            if refuse_changed:
                entry["refusal"] = prover().PHRASES["differs"]
                worst = 2
            lists["changed"].append(entry)
        elif remaining <= 0:
            lists["left"].append(entry)
        else:
            code, report = prove_selection(
                selection, folder, {**options, "budget_minutes": remaining}
            )
            write_json(folder / "report.json", report)
            spent += float((report["check"] or {}).get("estimated_minutes", 0.0))
            entry["report"] = f"{folder.name}/report.json"
            if code == 0:
                lists["proved"].append(entry)
            elif code == 1:
                lists["lost"].append(entry | {"losses": report["losses"]})
                worst = max(worst, 1)
            elif is_budget_refusal(report["refusal"]):
                lists["left"].append(entry | {"refusal": report["refusal"]})
            else:
                lists["refused"].append(entry | {"refusal": report["refusal"]})
                worst = 2
        if folder.is_dir():
            trim(folder)
    result = {
        "commits": scanned,
        "budget_minutes": budget,
        "spent_minutes": round(spent, 1),
        **lists,
        "seconds": round(time.monotonic() - started, 1),
    }
    return worst, result


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proof.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)

    def where(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=".", help="the clone to read (default: here)")
        p.add_argument("--work", required=True, help="folder for exports, measures and logs")
        p.add_argument("--out", required=True, help="the JSON file to write")

    def proof(p: argparse.ArgumentParser, budget: float) -> None:
        p.add_argument("--scope", choices=("module", "package"), default="module")
        p.add_argument("--budget-minutes", type=float, default=budget)
        p.add_argument("--mutmut", default=sys.executable, help="python that has mutmut 3.8.0")
        p.add_argument("--processes", type=int, default=4, help="mutant runs in parallel")
        p.add_argument("--workers", type=int, default=4, help="pytest-xdist workers per measure")
        p.add_argument("--runner", choices=("fresh", "fork"), default="fresh")
        p.add_argument("--ignore", nargs="+", default=[], help="test paths to leave out")

    pick = sub.add_parser("select", help="find the removed tests and the tests that stand for them")
    where(pick)
    pick.add_argument("--base", required=True)
    pick.add_argument("--head", default="HEAD")
    run = sub.add_parser("prove", help="run removal_proof.py check on a selection")
    run.add_argument("selection")
    where(run)
    proof(run, 45.0)
    ranged = sub.add_parser("range", help="prove each commit of a push against its parent")
    where(ranged)
    ranged.add_argument("--base", required=True)
    ranged.add_argument("--head", default="HEAD")
    proof(ranged, 45.0)
    weekly = sub.add_parser("week", help="prove each commit of a period that removes tests")
    where(weekly)
    weekly.add_argument("--since", default="7 days ago")
    weekly.add_argument("--head", default="HEAD")
    proof(weekly, 300.0)
    weekly.set_defaults(scope="package")
    return parser


def options_of(args: argparse.Namespace) -> dict:
    keys = ("scope", "budget_minutes", "mutmut", "processes", "workers", "runner", "ignore")
    return {key: getattr(args, key) for key in keys}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work, out, repo = Path(args.work).resolve(), Path(args.out), Path(args.repo).resolve()
    try:
        if args.action == "select":
            selection = select(repo, args.base, args.head, work)
            write_json(out, selection)
            print(
                f"select: {len(selection['removed'])} test functions gone in "
                f"{len(selection['files'])} files, {len(selection['modules'])} modules, "
                f"{len(selection['tests_base'])} tests before and {len(selection['tests_head'])} after "
                f"({selection['verdict']})"
            )
            return 0
        if args.action == "prove":
            code, report = prove_selection(
                load_selection(Path(args.selection)), work, options_of(args)
            )
            write_json(out, report)
            print(
                f"prove: exit {code}, {report['verdict']}, {report['removed']} test functions gone"
            )
        else:
            if args.action == "range":
                code, report = push_range(repo, args.base, args.head, work, options_of(args))
            else:
                code, report = week(repo, args.since, args.head, work, options_of(args))
            write_json(out, report)
            print(
                f"{args.action}: {report['commits']} commits, {len(report['proved'])} proved, "
                f"{len(report['lost'])} lost, {len(report['changed'])} changed, "
                f"{len(report['left'])} left, {len(report['refused'])} refused"
            )
            for entry in report["lost"]:
                print(f"{entry['commit'][:12]} {entry['subject']}", *entry["losses"], sep="\n  ")
            for entry in report["changed"] + report["refused"]:
                if entry.get("refusal"):
                    print(f"{entry['commit'][:12]} {entry['refusal']}", file=sys.stderr)
            return code
        for line in report["losses"]:
            print(line)
        if report["refusal"]:
            print(report["refusal"], file=sys.stderr)
        return code
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
