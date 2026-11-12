"""Prove that removed tests lose nothing: same lines, same arcs, same killed mutants.

Exit code 0 means proven, 1 a loss (listed), 2 an input the tool refuses.

    measure  run the suite once with a coverage context per test
    plan     choose the test functions that can leave, and prove it
    apply    edit a checkout so that the planned functions leave
    check    compare two trees that hold the same library code
    replay   play named mutants one by one (the control of the mutant runner)

The tool imports nothing from the library. It reads the standard library and the
coverage data file, and it starts pytest and mutmut as separate processes. It writes
only under the directories it is given, except ``apply``, which edits a checkout.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import importlib.metadata
import json
import os
import queue
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import traceback
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

PACKAGES = ("hydromodpy", "hydromodpy_server", "hydromodpy_annex")
REPO_ROOTS = (*PACKAGES, "tools", "tests", "validation_cases")
PROCESS_WORDS = ("subprocess", "sys.executable", "ProcessPoolExecutor", "multiprocessing")
READ_SUFFIXES = {".toml", ".yml", ".yaml", ".json", ".py", ".md", ".rst", ".txt", ".cfg", ".ini"}
PHASES = ("run", "setup", "teardown")
MUTMUT_VERSION = "3.8.0"
COVERAGE_MINIMUM = (7, 10)
TIMEOUT_SECONDS = 300
GENERATE_SECONDS = 1200
GENERATE_PER_MODULE = 3
ERROR_CODES = (2, 3, 4, 5)
SURVIVOR_SHARE = 0.25
FORK_SPEEDUP = 3.0
LIST_LIMIT = 200
PHRASES = {
    "differs": (
        "hydromodpy/ differs between the two trees: "
        "prove a test removal on unchanged code, in a change of its own."
    ),
    "failing": "the measure of {tree} has failing tests: a removal is proven on a green suite only.",
    "mutmut": (
        "mutmut 3.8.0 is needed for the mutant proof: "
        "pass --mutmut <python of an environment that has it>."
    ),
    "coverage": "coverage 7.10 or later is needed to measure child processes.",
    "import": "hydromodpy is imported from {path}, not from {tree}: run the measure on the tree itself.",
    "budget": "the mutant proof needs {n} minutes, over the budget of {m}: split the removal.",
    "plan": "the plan was made on {plan_tree}, whose tests differ from {tree}: make the plan again.",
    "mutant": (
        "{name} is not a mutmut 3.8 mutant name: "
        "<module>.x_<function>__mutmut_<n> or <module>.xǁ<Class>ǁ<method>__mutmut_<n> is expected."
    ),
    "measure": "{path} is not a measure: run `removal_proof.py measure` on the tree first.",
    "partial": (
        "mutmut wrote the mutants of {written} of {asked} modules in {seconds} s, "
        "{first} is the first one missing: a partial set of mutants proves nothing."
    ),
    "nometa": "{path} is missing: mutmut wrote no mutants for this module.",
    "stale": "the measure in {path} was made on {measured}, not on {tree}: measure the tree again.",
}
MUTANT_NAME = re.compile(
    r"^(?P<module>.+)\.(?:x_(?P<fn>.+)|xǁ(?P<cls>[^ǁ]+)ǁ(?P<meth>.+))__mutmut_(?P<n>\d+)$"
)
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)
WORDS = re.compile(r"[A-Za-z_]\w*")
ARC_BITS = 22
ARC_OFFSET = 1 << 21


class Refusal(Exception):
    """An input the tool refuses. The message names the expected form."""


def refuse(key: str, **fields: object) -> NoReturn:
    raise Refusal(PHRASES[key].format(**fields))


@dataclass(frozen=True)
class ScannedFunction:
    id: str
    file: str
    start: int
    end: int

    @property
    def lines(self) -> int:
        return self.end - self.start + 1


@dataclass
class ScannedFile:
    path: str
    text: str
    functions: list[ScannedFunction]
    imports: list[tuple[str, tuple[str, ...]]]
    imports_repo: bool
    reads_repo: bool
    subjects: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Case:
    status: str
    seconds: float


@dataclass
class Coverage:
    """Items run per test function and library file. An item is a packed arc, or a line."""

    arcs: bool
    items: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    block: dict[str, set[int]] = field(default_factory=dict)


@dataclass
class ModuleIndex:
    tree: Path
    modules: dict[str, str]
    symbols: dict[str, tuple[set[str], dict[str, tuple[str, str]]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    """One pytest run against one mutant. An empty mutant name runs the original code."""

    mutant: str
    ids: tuple[str, ...]
    tree: str
    stop_first: bool = True
    fresh: bool = False


@dataclass(frozen=True)
class Outcome:
    code: int
    failed: tuple[str, ...] = ()
    seconds: float = 0.0


Runner = Callable[[Job], Outcome]


@dataclass(frozen=True)
class MutantCase:
    name: str
    function: str
    kept_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    kept_tree: str
    gone_tree: str


@dataclass(frozen=True)
class Verdict:
    name: str
    function: str
    status: str
    killer: str | None = None
    put_back: tuple[str, ...] = ()


@dataclass
class Side:
    """One tree seen by the proof: its suite, its coverage and the directory mutants run in."""

    tree: Path
    run_dir: Path
    cov: Coverage
    files: dict[str, ScannedFile]
    seconds: dict[str, float]
    ids: set[str]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_digest(tree: Path, package: str = "hydromodpy") -> dict[str, str]:
    files = sorted((tree / package).rglob("*"))
    return {
        str(p.relative_to(tree)): sha256_of(p)
        for p in files
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def count_lines(tree: Path) -> int:
    paths = (p for p in (tree / "tests").rglob("*.py") if "__pycache__" not in p.parts)
    return sum(len(p.read_bytes().splitlines()) for p in paths)


def function_id_of(node_id: str) -> str:
    """Strip the phase and the parameters of a node id or a coverage context."""
    node, bar, phase = node_id.rpartition("|")
    return (node if bar and phase in PHASES else node_id).split("[", 1)[0]


def toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def is_function(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def span_of(node: ast.AST) -> tuple[int, int]:
    """First line (decorators included) and last line of a definition."""
    decorators = getattr(node, "decorator_list", [])
    return min([node.lineno, *(d.lineno for d in decorators)]), node.end_lineno  # type: ignore[attr-defined]


def in_keep(path: str, keep: set[str]) -> bool:
    return any(path == k or path.startswith(k.rstrip("/") + "/") for k in keep)


def read_keep(path: Path) -> set[str]:
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return {ln for ln in lines if ln}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Modules of the library and imports of a test file
# ---------------------------------------------------------------------------


def dotted_of(rel: str) -> str:
    parts = list(Path(rel).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def build_index(tree: Path) -> ModuleIndex:
    found = (p for pkg in PACKAGES for p in sorted((tree / pkg).rglob("*.py")))
    rels = [str(p.relative_to(tree)) for p in found if "__pycache__" not in p.parts]
    return ModuleIndex(tree, {dotted_of(rel): rel for rel in rels})


def symbols_of(index: ModuleIndex, rel: str) -> tuple[set[str], dict[str, tuple[str, str]]]:
    """Names a library file defines, and the names it imports with their origin."""
    if rel not in index.symbols:
        defined: set[str] = set()
        imported: dict[str, tuple[str, str]] = {}
        package = dotted_of(rel).split(".")
        package = package if rel.endswith("__init__.py") else package[:-1]
        for node in ast.parse((index.tree / rel).read_text(encoding="utf-8")).body:
            if is_function(node) or isinstance(node, ast.ClassDef):
                defined.add(node.name)  # type: ignore[attr-defined]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                defined.update(t.id for t in targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.ImportFrom):
                base = package[: len(package) - max(node.level - 1, 0)] if node.level else []
                source = ".".join([*base, *([node.module] if node.module else [])])
                imported.update({(a.asname or a.name): (source, a.name) for a in node.names})
        index.symbols[rel] = (defined, imported)
    return index.symbols[rel]


def defining_module(index: ModuleIndex, module: str, name: str, depth: int = 0) -> str | None:
    """The file of the library that defines ``name`` as imported from ``module``."""
    if module not in index.modules:
        return None
    if f"{module}.{name}" in index.modules:
        return index.modules[f"{module}.{name}"]
    rel = index.modules[module]
    defined, imported = symbols_of(index, rel)
    if name in defined or depth >= 4 or name not in imported:
        return rel
    return defining_module(index, *imported[name], depth + 1) or rel


def named_module(rel: str, index: ModuleIndex) -> set[str]:
    """The module that a file ``test_<module>.py`` names, the nearest folder match first."""
    stem = Path(rel).stem
    name = stem.removeprefix("test_")
    if name == stem:
        return set()
    folders = set(Path(rel).parent.parts)
    scored = [
        (len(folders & set(dotted.split("."))), path)
        for dotted, path in index.modules.items()
        if dotted.rsplit(".", 1)[-1] == name and not path.endswith("__init__.py")
    ]
    best = max((score for score, _ in scored), default=0)
    winners = {path for score, path in scored if score == best}
    return winners if best > 0 or len(winners) == 1 else set()


def subjects_of(file: ScannedFile, index: ModuleIndex) -> frozenset[str]:
    out = set(named_module(file.path, index))
    for module, names in file.imports:
        if not names and module in index.modules:
            out.add(index.modules[module])
        out.update(p for p in (defining_module(index, module, n) for n in names) if p)
    return frozenset(out)


def names_used(module: ast.AST) -> set[str]:
    """Names read in code, plus names written in string annotations."""
    used: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        notes = [getattr(node, "annotation", None), getattr(node, "returns", None)]
        for note in filter(None, notes):
            for sub in ast.walk(note):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    used.update(WORDS.findall(sub.value))
    return used


def reads_repo_file(module: ast.AST, text: str, tree: Path) -> bool:
    """Whether a test file mentions a file of the tree: ``__file__``, or a path that exists."""
    if "__file__" in text:
        return True
    for node in ast.walk(module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            pathlike = "/" in value or Path(value).suffix in READ_SUFFIXES
            if pathlike and 0 < len(value) < 200 and "\n" not in value and value[0] != "/":
                if (tree / value).exists():
                    return True
    return False


def definitions(module: ast.Module, rel: str) -> Iterator[tuple[str, ast.AST, ast.ClassDef | None]]:
    """Functions of a module and methods of its classes, with their node ids."""
    for node in module.body:
        if is_function(node):
            yield f"{rel}::{node.name}", node, None  # type: ignore[attr-defined]
        elif isinstance(node, ast.ClassDef):
            for sub in filter(is_function, node.body):
                yield f"{rel}::{node.name}::{sub.name}", sub, node  # type: ignore[attr-defined]


def test_functions(module: ast.Module, rel: str) -> list[ScannedFunction]:
    found = []
    for fid, node, owner in definitions(module, rel):
        if node.name.startswith("test") and (owner is None or owner.name.startswith("Test")):  # type: ignore[attr-defined]
            found.append(ScannedFunction(fid, rel, *span_of(node)))
    return found


def scan_file(tree: Path, rel: str) -> ScannedFile:
    text = (tree / rel).read_text(encoding="utf-8")
    module = ast.parse(text)
    imports: list[tuple[str, tuple[str, ...]]] = []
    repo = False
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            repo |= node.level > 0 or (node.module or "").split(".")[0] in REPO_ROOTS
            if node.level == 0 and (node.module or "").split(".")[0] in PACKAGES:
                imports.append((node.module or "", tuple(a.name for a in node.names)))
        elif isinstance(node, ast.Import):
            roots = [a.name for a in node.names if a.name.split(".")[0] in REPO_ROOTS]
            repo |= bool(roots)
            imports.extend((n, ()) for n in roots if n.split(".")[0] in PACKAGES)
    functions = test_functions(module, rel)
    return ScannedFile(rel, text, functions, imports, repo, reads_repo_file(module, text, tree))


def scan_files(tree: Path, paths: Sequence[str], index: ModuleIndex) -> dict[str, ScannedFile]:
    out: dict[str, ScannedFile] = {}
    for rel in sorted({p for p in paths if (tree / p).is_file()}):
        out[rel] = scan_file(tree, rel)
        out[rel].subjects = subjects_of(out[rel], index)
    return out


def scope_files(tree: Path, scope_dirs: Sequence[str]) -> list[str]:
    paths = (p for d in scope_dirs for p in (tree / d).rglob("test_*.py"))
    return sorted({str(p.relative_to(tree)) for p in paths if "__pycache__" not in p.parts})


# ---------------------------------------------------------------------------
# Results of a pytest run and coverage data
# ---------------------------------------------------------------------------


def junit_node_id(classname: str, name: str, tree: Path) -> str:
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        rel = "/".join(parts[:cut]) + ".py"
        if (tree / rel).is_file():
            return "::".join([rel, *parts[cut:], name])
    return "::".join(["/".join(parts) + ".py", name])


def parse_junit(text: str, tree: Path) -> dict[str, Case]:
    """Map each case node id to its worst status and its duration."""
    rank = {"passed": 0, "skipped": 1, "xfail": 1, "failed": 2, "error": 2}
    kinds = {"skipped": "skipped", "failure": "failed", "error": "error"}
    out: dict[str, Case] = {}
    for element in ET.fromstring(text).iter("testcase"):
        status = "passed"
        for child in element:
            kind = kinds.get(child.tag, "passed")
            if kind == "skipped" and "xfail" in (child.get("type") or ""):
                kind = "xfail"
            status = kind if rank[kind] > rank[status] else status
        node = junit_node_id(element.get("classname", ""), element.get("name", ""), tree)
        seconds = float(element.get("time") or 0.0)
        if node in out:
            old = out[node]
            status = status if rank[status] > rank[old.status] else old.status
            seconds += old.seconds
        out[node] = Case(status, seconds)
    return out


def group_cases(cases: dict[str, Case]) -> dict[str, list[Case]]:
    grouped: dict[str, list[Case]] = defaultdict(list)
    for node, case in cases.items():
        grouped[function_id_of(node)].append(case)
    return grouped


def pack_arc(a: int, b: int) -> int:
    return ((a + ARC_OFFSET) << ARC_BITS) | (b + ARC_OFFSET)


def unpack_arc(value: int) -> tuple[int, int]:
    return (value >> ARC_BITS) - ARC_OFFSET, (value & ((1 << ARC_BITS) - 1)) - ARC_OFFSET


def lines_of(items: set[int], arcs: bool) -> set[int]:
    if not arcs:
        return set(items)
    return {x for value in items for x in unpack_arc(value) if x > 0}


def relative_to_tree(path: str, tree: Path) -> str | None:
    for root in (tree, tree.resolve()):
        with contextlib.suppress(ValueError):
            return str(Path(path).relative_to(root))
    return None if Path(path).is_absolute() else path


def function_of_context(context: str) -> str | None:
    """The test function a context belongs to, or None for the empty context."""
    node, bar, phase = context.rpartition("|")
    return node.split("[", 1)[0] if bar and phase in PHASES and "::" in node else None


def numbits_lines(blob: bytes) -> Iterator[int]:
    for j, byte in enumerate(blob):
        yield from (8 * j + i for i in range(8) if byte >> i & 1)


def load_coverage(data_file: Path, tree: Path) -> Coverage:
    """Read a combined data file: items per test function, and the empty context apart."""
    con = sqlite3.connect(f"file:{data_file}?mode=ro", uri=True)
    try:
        cov = Coverage(arcs=dict(con.execute("select key, value from meta")).get("has_arcs") == "1")
        rels = {
            fid: relative_to_tree(path, tree)
            for fid, path in con.execute("select id, path from file")
        }
        files = {fid: r for fid, r in rels.items() if r and r.split("/", 1)[0] in PACKAGES}
        contexts = {
            cid: function_of_context(c) for cid, c in con.execute("select id, context from context")
        }
        if cov.arcs:
            rows = con.execute("select file_id, context_id, fromno, tono from arc")
            pairs = ((f, c, pack_arc(a, b)) for f, c, a, b in rows)
        else:
            rows = con.execute("select file_id, context_id, numbits from line_bits")
            pairs = ((f, c, n) for f, c, blob in rows for n in numbits_lines(blob))
        for fid, cid, item in pairs:
            if fid in files:
                fn = contexts[cid]
                target = cov.block if fn is None else cov.items.setdefault(fn, {})
                target.setdefault(files[fid], set()).add(item)
    finally:
        con.close()
    return cov


def union_items(cov: Coverage) -> dict[str, set[int]]:
    union: dict[str, set[int]] = defaultdict(set)
    for per_file in [*cov.items.values(), cov.block]:
        for path, items in per_file.items():
            union[path] |= items
    return union


def lost_items(before: Coverage, after: Coverage, removed: set[str]) -> dict[str, dict]:
    """Lines and arcs run before and not after, per file, with the removed tests that ran them."""
    ub, ua = union_items(before), union_items(after)
    lost: dict[str, dict] = {}
    for path, items in sorted(ub.items()):
        missing = items - ua.get(path, set())
        if not missing:
            continue
        gone = sorted(lines_of(items, before.arcs) - lines_of(ua.get(path, set()), after.arcs))
        arcs = sorted(unpack_arc(x) for x in missing) if before.arcs else []
        by = [f for f in sorted(removed) if before.items.get(f, {}).get(path, set()) & missing]
        lost[path] = {
            "lines_count": len(gone),
            "lines": gone[:LIST_LIMIT],
            "arcs_count": len(arcs),
            "arcs": [list(a) for a in arcs[:LIST_LIMIT]],
            "covered_by": by[:20],
        }
    return lost


# ---------------------------------------------------------------------------
# Candidates and the greedy cover
# ---------------------------------------------------------------------------


def pick_candidates(
    files: Sequence[ScannedFile], grouped: dict[str, list[Case]], cov: Coverage, keep: set[str]
) -> tuple[list[ScannedFunction], list[ScannedFunction], dict[str, list[str]]]:
    """Split test functions into the pool, the unconditional ones and the skipped, by reason."""
    pool, unconditional = [], []
    skipped: dict[str, list[str]] = defaultdict(list)
    for file in files:
        reason = ""
        if in_keep(file.path, keep):
            reason = "keep"
        elif "allow_subprocess" in file.text:
            reason = "allow_subprocess"
        elif any(word in file.text for word in PROCESS_WORDS):
            reason = "subprocess"
        for fn in file.functions:
            cases = grouped.get(fn.id)
            if not reason and not cases:
                reason_fn = "not_run"
            elif not reason and any(c.status != "passed" for c in cases or []):
                reason_fn = "not_green"
            elif not reason and not cov.items.get(fn.id):
                reason_fn = "" if not (file.imports_repo or file.reads_repo) else "no_coverage"
                if not reason_fn:
                    unconditional.append(fn)
                    continue
            else:
                reason_fn = reason
            if reason_fn:
                skipped[reason_fn].append(fn.id)
            else:
                pool.append(fn)
    return pool, unconditional, skipped


def greedy_cover(cov: Coverage, candidates: Sequence[ScannedFunction]) -> dict[str, dict]:
    """Candidates leave, longest first, while every item they run stays run by a kept test."""
    cover: Counter[tuple[str, int]] = Counter()
    for per_file in [cov.block, *cov.items.values()]:
        for path, items in per_file.items():
            cover.update((path, x) for x in items)
    removed: dict[str, dict] = {}
    for fn in sorted(candidates, key=lambda f: (-f.lines, f.id)):
        mine = [(p, x) for p, items in cov.items.get(fn.id, {}).items() for x in items]
        if mine and all(cover[key] > 1 for key in mine):
            removed[fn.id] = {
                "items": len(mine),
                "min_other_covers": min(cover[k] - 1 for k in mine),
            }
            cover.subtract(mine)
    return removed


# ---------------------------------------------------------------------------
# Mutants: names, source functions, cases
# ---------------------------------------------------------------------------


def parse_mutant(name: str) -> tuple[str, str | None, str]:
    """Dotted module, class and function of a mutmut 3.8 mutant name."""
    found = MUTANT_NAME.match(name)
    if not found:
        refuse("mutant", name=name)
    return found["module"], found["cls"], found["fn"] or found["meth"]


def module_file(tree: Path, dotted: str) -> str:
    base = dotted.replace(".", "/")
    return f"{base}.py" if (tree / f"{base}.py").is_file() else f"{base}/__init__.py"


def function_spans(tree: Path, rel: str) -> dict[tuple[str | None, str], tuple[int, int]]:
    """Body line range of each function and method of a module, keyed by (class, name)."""
    module = ast.parse((tree / rel).read_text(encoding="utf-8"))
    return {
        (owner.name if owner else None, node.name): (node.body[0].lineno, node.end_lineno)  # type: ignore[attr-defined]
        for _, node, owner in definitions(module, rel)
    }


def function_source_sha(tree: Path, function_id: str) -> str | None:
    rel, *chain = function_id.split("::")
    if not (tree / rel).is_file():
        return None
    text = (tree / rel).read_text(encoding="utf-8")
    nodes = {fid: node for fid, node, _ in definitions(ast.parse(text), rel)}
    if function_id not in nodes:
        return None
    start, end = span_of(nodes[function_id])
    return hashlib.sha256("\n".join(text.splitlines()[start - 1 : end]).encode()).hexdigest()


def module_names(run_dir: Path, rel: str) -> list[str]:
    """Mutant names of a module, read from the ``.meta`` file that mutmut wrote for it."""
    meta = run_dir / f"{rel}.meta"
    if not meta.is_file():
        refuse("nometa", path=meta)
    return sorted(json.loads(meta.read_text(encoding="utf-8")).get("exit_code_by_key", {}))


def module_cases(
    module: str, kept: Side, gone: Side, removed: dict[str, frozenset[str]], names: Sequence[str]
) -> list[MutantCase]:
    """Mutants of the functions of ``module`` that a removed test runs."""
    removed_ids = tuple(sorted(i for i, subjects in removed.items() if module in subjects))
    hit: set[int] = set()
    for fid in removed_ids:
        hit |= lines_of(gone.cov.items.get(fid, {}).get(module, set()), gone.cov.arcs)
    spans = function_spans(kept.tree, module)
    index: dict[int, set[str]] = defaultdict(set)
    for fid, per_file in kept.cov.items.items():
        for line in lines_of(per_file.get(module, set()), kept.cov.arcs):
            index[line].add(fid)
    by_subject = {fn.id for f in kept.files.values() if module in f.subjects for fn in f.functions}
    cases = []
    for name in names:
        dotted, cls, fn_name = parse_mutant(name)
        start, end = spans.get((cls, fn_name), (1, 0))
        if not hit & set(range(start, end + 1)):
            continue
        covering = {fid for line in range(start, end + 1) for fid in index.get(line, ())}
        ids = sorted(
            (by_subject | covering) & kept.ids - set(removed),
            key=lambda i: (kept.seconds.get(i, 0.0), i),
        )
        label = f"{dotted}::{cls + '.' if cls else ''}{fn_name}"
        cases.append(
            MutantCase(name, label, tuple(ids), removed_ids, str(kept.run_dir), str(gone.run_dir))
        )
    return cases


# ---------------------------------------------------------------------------
# Runners: one fresh process per mutant, or a forked child of a warm worker
# ---------------------------------------------------------------------------


def pytest_args(ids_file: Path, stop_first: bool) -> list[str]:
    args = [f"@{ids_file}", "-q", "-p", "no:cacheprovider", "--no-cov", "-n", "0", "-W", "ignore"]
    return [*args, "-rfE", *(["-x"] if stop_first else [])]


def prepare_run(job: Job, scratch_root: Path) -> tuple[Path, Path, Path]:
    scratch = Path(tempfile.mkdtemp(prefix="m", dir=scratch_root))
    ids_file = scratch / "ids.txt"
    ids_file.write_text("\n".join(job.ids) + "\n", encoding="utf-8")
    return scratch, ids_file, scratch / "out.txt"


def finish_run(scratch: Path, out: Path, code: int, started: float) -> Outcome:
    text = out.read_text(encoding="utf-8", errors="replace") if out.is_file() else ""
    shutil.rmtree(scratch, ignore_errors=True)
    return Outcome(code, tuple(FAILED_LINE.findall(text)), round(time.monotonic() - started, 3))


def run_fresh(job: Job, python: str, scratch_root: Path, timeout: int) -> Outcome:
    started = time.monotonic()
    scratch, ids_file, out = prepare_run(job, scratch_root)
    env = {
        **os.environ,
        "HMP_TEST_SCRATCH_ROOT": str(scratch),
        "TMPDIR": str(scratch),
        "MPLBACKEND": "Agg",
        "MUTANT_UNDER_TEST": job.mutant,
    }
    command = [python, "-m", "pytest", *pytest_args(ids_file, job.stop_first)]
    with out.open("wb") as handle:
        proc = subprocess.Popen(
            command,
            cwd=job.tree,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            code = 124
    return finish_run(scratch, out, code, started)


@dataclass
class ForkWorkers:
    """Warm workers of the fork runner, one set per directory of mutants."""

    python: str
    work: Path
    limit: int
    timeout: int
    idle: dict[str, queue.Queue] = field(default_factory=dict)
    count: dict[str, int] = field(default_factory=dict)
    procs: list[subprocess.Popen] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


def acquire_worker(pool: ForkWorkers, tree: str) -> subprocess.Popen:
    with pool.lock:
        free = pool.idle.setdefault(tree, queue.Queue())
        if free.empty() and pool.count.get(tree, 0) < pool.limit:
            pool.count[tree] = pool.count.get(tree, 0) + 1
            command = [pool.python, str(Path(__file__).resolve()), "worker", "--run-dir", tree]
            logfile = (pool.work / f"worker-{len(pool.procs)}.log").open("wb")
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=logfile,
                text=True,
                start_new_session=True,
            )
            pool.procs.append(proc)
            return proc
    return free.get()


def run_forked(job: Job, pool: ForkWorkers, scratch_root: Path) -> Outcome:
    started = time.monotonic()
    scratch, ids_file, out = prepare_run(job, scratch_root)
    request = {
        "mutant": job.mutant,
        "args": pytest_args(ids_file, job.stop_first),
        "out": str(out),
        "scratch": str(scratch),
        "timeout": pool.timeout,
    }
    worker = acquire_worker(pool, job.tree)
    try:
        worker.stdin.write(json.dumps(request) + "\n")
        worker.stdin.flush()
        reply = worker.stdout.readline()
        if not reply:
            raise RuntimeError(f"a fork worker of {job.tree} stopped: see {pool.work}/worker-*.log")
    finally:
        pool.idle[job.tree].put(worker)
    return finish_run(scratch, out, int(json.loads(reply)["code"]), started)


@contextlib.contextmanager
def open_runner(
    kind: str, python: str, work: Path, processes: int, timeout: int = TIMEOUT_SECONDS
) -> Iterator[Runner]:
    """A runner, ``fresh`` or ``fork``. Both take a Job and give an Outcome in the same format."""
    scratch_root = work / "scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    pool = ForkWorkers(python, work, processes, timeout)

    def run(job: Job) -> Outcome:
        if kind == "fork" and not job.fresh:
            return run_forked(job, pool, scratch_root)
        return run_fresh(job, python, scratch_root, timeout)

    try:
        yield run
    finally:
        for proc in pool.procs:
            with contextlib.suppress(OSError):
                proc.stdin.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)


def run_jobs(jobs: Sequence[Job], run: Runner, processes: int, label: str = "") -> list[Outcome]:
    """Run jobs in parallel. A job without ids has no test to kill its mutant, so it survives."""
    outcomes = [Outcome(0)] * len(jobs)
    todo = [i for i, job in enumerate(jobs) if job.ids]
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(processes, len(todo)))) as pool:
            results = pool.map(run, [jobs[i] for i in todo])
            for n, (i, outcome) in enumerate(zip(todo, results, strict=True), 1):
                outcomes[i] = outcome
                if label and n * 10 // len(todo) > (n - 1) * 10 // len(todo):
                    log(f"{label}: {n} of {len(todo)} done")
    return outcomes


def worker_serve(run_dir: str) -> None:
    """Warm worker. One request per line: fork a child that runs pytest, reply with its code."""
    os.chdir(run_dir)
    sys.path.insert(0, run_dir)
    import pytest

    import hydromodpy  # noqa: F401

    reply = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    for line in sys.stdin:
        request = json.loads(line)
        pid = os.fork()
        if pid == 0:
            code = 3
            try:
                os.setsid()
                fd = os.open(request["out"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                os.dup2(fd, 1)
                os.dup2(fd, 2)
                scratch = request["scratch"]
                os.environ.update(
                    HMP_TEST_SCRATCH_ROOT=scratch,
                    TMPDIR=scratch,
                    MUTANT_UNDER_TEST=request["mutant"],
                )
                os.environ["MPLBACKEND"] = "Agg"
                tempfile.tempdir = scratch
                code = int(pytest.main(request["args"]))
            except BaseException:
                traceback.print_exc()
            finally:
                # os._exit flushes nothing, and the failed tests are read from this output.
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
        reply.write(json.dumps({"code": wait_child(pid, float(request["timeout"]))}) + "\n")
        reply.flush()


def wait_child(pid: int, timeout: float) -> int:
    """Exit code of a child, 128 plus the signal for a killed one, 124 after the timeout."""
    deadline = time.monotonic() + timeout
    pause = 0.01
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            code = os.waitstatus_to_exitcode(status)
            return code if code >= 0 else 128 - code
        if time.monotonic() > deadline:
            os.killpg(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            return 124
        time.sleep(pause)
        pause = min(pause * 1.5, 0.1)


# ---------------------------------------------------------------------------
# The decision on each mutant
# ---------------------------------------------------------------------------


def classify(code: int) -> str:
    if code == 0:
        return "survived"
    return "error" if code in ERROR_CODES else "killed"


def prove_mutants(
    cases: Sequence[MutantCase], run: Runner, processes: int, fork_first: bool
) -> list[Verdict]:
    """Play each mutant against the kept tests, then its survivors against the removed ones."""
    first = [Job(c.name, c.kept_ids, c.kept_tree, fresh=not fork_first) for c in cases]
    outcomes = run_jobs(first, run, processes, "mutants")
    if fork_first:
        # A cache filled at import in the warm parent may hide a mutant, so only kills count.
        again = [i for i, o in enumerate(outcomes) if classify(o.code) != "killed" or not o.failed]
        fresh = [Job(first[i].mutant, first[i].ids, first[i].tree, fresh=True) for i in again]
        for i, outcome in zip(again, run_jobs(fresh, run, processes), strict=True):
            outcomes[i] = outcome
    survivors = [i for i, o in enumerate(outcomes) if classify(o.code) == "survived"]
    removed = [
        Job(cases[i].name, cases[i].removed_ids, cases[i].gone_tree, fresh=True) for i in survivors
    ]
    second = dict(zip(survivors, run_jobs(removed, run, processes), strict=True))
    return [decide(c, outcomes[i], second.get(i)) for i, c in enumerate(cases)]


def decide(case: MutantCase, kept: Outcome, gone: Outcome | None) -> Verdict:
    state = classify(kept.code)
    if state == "killed" and not kept.failed:
        # A timeout or a crash names no red test: it does not prove that a test sees the mutant.
        state = "error"
    if state == "killed":
        return Verdict(case.name, case.function, "killed", function_id_of(kept.failed[0]))
    second = classify(gone.code) if gone else "survived"
    if state == "error" or second == "error":
        return Verdict(case.name, case.function, "error", None, case.removed_ids)
    if second == "survived":
        return Verdict(case.name, case.function, "proved")
    killer = function_id_of(gone.failed[0]) if gone and gone.failed else None
    put_back = (killer,) if killer in case.removed_ids else case.removed_ids
    return Verdict(case.name, case.function, "lost", killer, put_back)


# ---------------------------------------------------------------------------
# mutmut: version check, generation of the mutants
# ---------------------------------------------------------------------------


def require_mutmut(python: str) -> None:
    probe = "import importlib.metadata as m; print(m.version('mutmut'))"
    try:
        done = subprocess.run([python, "-c", probe], capture_output=True, text=True, timeout=60)
    except OSError:
        refuse("mutmut")
    if done.returncode != 0 or done.stdout.strip() != MUTMUT_VERSION:
        refuse("mutmut")


def require_coverage(version: str) -> None:
    if tuple(int(x) for x in re.findall(r"\d+", version)[:2]) < COVERAGE_MINIMUM:
        refuse("coverage")


def emptied(work: Path, rel: str) -> bool:
    """Whether the mutated copy of a module is empty while the module is not."""
    mutated = work / "mutants" / rel
    return mutated.is_file() and mutated.stat().st_size == 0 and (work / rel).stat().st_size > 0


def generate_mutants(
    tree: Path, modules: Sequence[str], work: Path, python: str, selection: Sequence[str]
) -> Path:
    """Copy the tree, ask mutmut for the mutants of ``modules`` and stop once they exist."""
    if work.exists():
        shutil.rmtree(work)
    skip = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".hmp", "build", ".*_cache")
    shutil.copytree(tree, work, symlinks=True, ignore=skip)
    config = {
        "source_paths": sorted({m.split("/", 1)[0] + "/" for m in modules}),
        "only_mutate": sorted(modules),
        "pytest_add_cli_args_test_selection": list(selection)[:20],
        "pytest_add_cli_args": ["-p", "no:cacheprovider", "--no-cov", "-n", "0", "-W", "ignore"],
        "process_isolation": "forkserver",
        "forkserver_warmup": "collect",
        "also_copy": ["tests", "pyproject.toml", "pytest.ini", "validation_cases", "tools"]
        + ["docs/source", "examples"],
    }
    body = "\n".join(f"{key} = {toml_value(value)}" for key, value in config.items())
    with (work / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write(f"\n[tool.mutmut]\n{body}\n")
    metas = [work / "mutants" / f"{m}.meta" for m in modules]
    with (work / "generate.log").open("wb") as logfile:
        command = [python, "-m", "mutmut", "run", "--max-children", "1"]
        proc = subprocess.Popen(
            command, cwd=work, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True
        )
        started = time.monotonic()
        deadline = started + GENERATE_SECONDS + GENERATE_PER_MODULE * len(modules)
        while time.monotonic() < deadline and proc.poll() is None:
            if all(p.is_file() for p in metas):
                break
            time.sleep(1)
        time.sleep(2)
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    written = [
        m for m in modules if (work / "mutants" / f"{m}.meta").is_file() and not emptied(work, m)
    ]
    if len(written) < len(modules):
        seconds = round(time.monotonic() - started)
        first = sorted(set(modules) - set(written))[0]
        refuse("partial", written=len(written), asked=len(modules), seconds=seconds, first=first)
    return work / "mutants"


def swap_tests(mutants: Path, tree: Path, work: Path) -> Path:
    """Directory of mutants for another tree: the same library code, the tests of that tree."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(mutants, work, symlinks=True, ignore=shutil.ignore_patterns("tests"))
    shutil.copytree(tree / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    return work


# ---------------------------------------------------------------------------
# Budget, folds and moves
# ---------------------------------------------------------------------------


def module_gain(
    removed: dict[str, ScannedFunction], subjects: dict[str, frozenset[str]]
) -> dict[str, float]:
    """Test lines a module earns: each removed function shares its lines between its subjects."""
    gain: dict[str, float] = defaultdict(float)
    for fid, fn in removed.items():
        for module in subjects[fid]:
            gain[module] += fn.lines / len(subjects[fid])
    return gain


def rank_modules(gain: dict[str, float], seconds: dict[str, float]) -> list[str]:
    def ratio(module: str) -> float:
        return float("inf") if not seconds.get(module) else gain[module] / seconds[module]

    return sorted(gain, key=lambda m: (-ratio(m), m))


def take_modules(gain: dict[str, float], seconds: dict[str, float], budget: float) -> list[str]:
    taken, spent = [], 0.0
    for module in rank_modules(gain, seconds):
        if spent + seconds.get(module, 0.0) <= budget:
            taken.append(module)
            spent += seconds.get(module, 0.0)
    return taken


def hours_to_target(
    gain: dict[str, float], seconds: dict[str, float], total: int, target: int, processes: int
) -> float | None:
    """Hours of mutant replay before the suite falls to ``target`` lines, or None if it never does."""
    if total <= target:
        return 0.0
    got = spent = 0.0
    for module in rank_modules(gain, seconds):
        got, spent = got + gain[module], spent + seconds.get(module, 0.0)
        if got >= total - target:
            return round(spent / processes / 3600, 2)
    return None


class DropLiterals(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.Constant(value="_")


def fold_groups(
    files: Sequence[ScannedFile], stays: Callable[[str, ScannedFile], bool]
) -> list[dict]:
    """Test functions of one file whose syntax tree differs only by literals."""
    out: list[dict] = []
    for file in files:
        nodes = {fid: node for fid, node, _ in definitions(ast.parse(file.text), file.path)}
        shapes: dict[str, list[str]] = defaultdict(list)
        for fn in file.functions:
            if fn.id in nodes and stays(fn.id, file):
                node = copy.deepcopy(nodes[fn.id])
                node.name = "_"  # type: ignore[attr-defined]
                if ast.get_docstring(node):  # type: ignore[arg-type]
                    node.body = node.body[1:]  # type: ignore[attr-defined]
                shapes[fn.id.rpartition("::")[0] + ast.dump(DropLiterals().visit(node))].append(
                    fn.id
                )
        out.extend({"file": file.path, "ids": ids} for ids in shapes.values() if len(ids) > 1)
    return out


def move_targets(
    files: Sequence[ScannedFile], stays: Callable[[str, ScannedFile], bool]
) -> list[dict]:
    """Test functions with one subject module, in a file that does not carry that module's name."""
    out: list[dict] = []
    for file in files:
        if len(file.subjects) == 1:
            (module,) = file.subjects
            target = str(Path(file.path).with_name(f"test_{Path(module).stem}.py"))
            rows = [
                {"id": fn.id, "from": file.path, "to": target, "module": module}
                for fn in file.functions
                if stays(fn.id, file)
            ]
            out.extend(rows if target != file.path else [])
    return out


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


def write_coveragerc(tree: Path, out: Path) -> Path:
    payload = tomllib.loads((tree / "pyproject.toml").read_text(encoding="utf-8"))
    run = dict(payload.get("tool", {}).get("coverage", {}).get("run", {}))
    run.update(
        source=list(PACKAGES),
        branch=True,
        patch=["subprocess"],
        concurrency=["thread", "multiprocessing"],
        data_file=str(out / ".coverage"),
    )
    path = out / "coveragerc.toml"
    body = "\n".join(f"{key} = {toml_value(value)}" for key, value in run.items())
    path.write_text(f"[tool.coverage.run]\n{body}\n", encoding="utf-8")
    return path


def library_location(python: str, tree: Path, cwd: Path) -> str:
    probe = "import hydromodpy; print(hydromodpy.__file__)"
    env = {**os.environ, "PYTHONPATH": str(tree)}
    done = subprocess.run([python, "-c", probe], cwd=cwd, env=env, capture_output=True, text=True)
    return done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""


# More red cases than this and the measure is refused.
MAX_RED_CASES = 20


def run_measure(
    tree: Path, out: Path, tests: Sequence[str], ignores: Sequence[str], workers: int
) -> dict:
    """Run the suite on ``tree`` with one coverage context per test and keep the results in ``out``."""
    python = sys.executable
    require_coverage(importlib.metadata.version("coverage"))
    out.mkdir(parents=True, exist_ok=True)
    found = library_location(python, tree, out)
    if not found or not Path(found).resolve().is_relative_to(tree.resolve()):
        refuse("import", path=found or "nowhere", tree=tree)
    for old in out.glob(".coverage*"):
        old.unlink()
    rc = write_coveragerc(tree, out)
    scratch = out / "scratch"
    scratch.mkdir(exist_ok=True)
    junit = out / "junit.xml"
    command = [python, "-m", "pytest", *tests, *(f"--ignore={p}" for p in ignores)]
    command += [f"--cov={p}" for p in PACKAGES]
    command += [f"--cov-config={rc}", "--cov-context=test", "--cov-report=", f"--junitxml={junit}"]
    # Contexts are written by the xdist workers only, so even one worker runs under xdist.
    command += ["-p", "no:cacheprovider", "-q", "-n", str(max(workers, 1))]
    env = {
        **os.environ,
        "PYTHONPATH": str(tree),
        "HMP_TEST_SCRATCH_ROOT": str(scratch),
        "TMPDIR": str(scratch),
        "MPLBACKEND": "Agg",
        "COVERAGE_FILE": str(out / ".coverage"),
    }
    started = time.monotonic()
    code = subprocess.run(command, cwd=tree, env=env, check=False).returncode
    # pytest returns 1 when tests fail and more when it could not run them.
    if code not in (0, 1) or not junit.is_file():
        refuse("failing", tree=tree)
    cases = parse_junit(junit.read_text(encoding="utf-8"), tree)
    red = sorted(node for node, case in cases.items() if case.status in ("failed", "error"))
    # A few red tests are kept as they are by the plan. A red suite proves nothing.
    if len(red) > MAX_RED_CASES:
        refuse("failing", tree=tree)
    if any(out.glob(".coverage.*")):
        combine = [python, "-m", "coverage", "combine", f"--rcfile={rc}", "--append"]
        subprocess.run(combine, cwd=out, env=env, check=True)
    (out / "ids.txt").write_text("\n".join(sorted(cases)) + "\n", encoding="utf-8")
    meta = {
        "format": "hmp-removal-measure/1",
        "tree": str(tree.resolve()),
        "hydromodpy_sha256": package_digest(tree),
        "tests": list(tests),
        "ignore": list(ignores),
        "python": sys.version.split()[0],
        "coverage": importlib.metadata.version("coverage"),
        "pytest": importlib.metadata.version("pytest"),
        "pytest_code": code,
        "seconds": round(time.monotonic() - started, 1),
        "cases": len(cases),
        "red": red,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def load_measure(directory: Path, tree: Path) -> tuple[Coverage, dict[str, Case]]:
    needed = ("meta.json", ".coverage", "junit.xml")
    if not all((directory / name).is_file() for name in needed):
        refuse("measure", path=directory)
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    if Path(meta["tree"]) != tree.resolve():
        refuse("stale", path=directory, measured=meta["tree"], tree=tree)
    junit = (directory / "junit.xml").read_text(encoding="utf-8")
    return load_coverage(directory / ".coverage", tree), parse_junit(junit, tree)


# ---------------------------------------------------------------------------
# Mutant proof shared by plan and check
# ---------------------------------------------------------------------------


def make_side(
    tree: Path, cov: Coverage, cases: dict[str, Case], index: ModuleIndex, extra: Sequence[str] = ()
) -> Side:
    grouped = group_cases(cases)
    seconds = {fid: sum(c.seconds for c in group) for fid, group in grouped.items()}
    paths = {fid.split("::", 1)[0] for fid in grouped} | set(extra)
    return Side(tree, tree, cov, scan_files(tree, sorted(paths), index), seconds, set(grouped))


def measure_baseline(
    modules: Sequence[str],
    cases: dict[str, list[MutantCase]],
    removed: dict[str, frozenset[str]],
    run: Runner,
    processes: int,
) -> dict[str, dict]:
    """Run each module's tests once without a mutant: seconds, and the tests red already."""
    jobs = []
    for module in modules:
        mine = cases[module][0]
        kept = sorted({i for c in cases[module] for i in c.kept_ids})
        gone = sorted(i for i, subjects in removed.items() if module in subjects)
        jobs.append(Job("", tuple(kept), mine.kept_tree, stop_first=False, fresh=True))
        jobs.append(Job("", tuple(gone), mine.gone_tree, stop_first=False, fresh=True))
    outcomes = run_jobs(jobs, run, processes)
    result = {}
    for n, module in enumerate(modules):
        a, b = outcomes[2 * n], outcomes[2 * n + 1]
        result[module] = {
            "kept_seconds": a.seconds,
            "removed_seconds": b.seconds,
            "red_kept": sorted({function_id_of(i) for i in a.failed}),
            "red_removed": sorted({function_id_of(i) for i in b.failed}),
            "error": a.code in ERROR_CODES or b.code in ERROR_CODES,
        }
    return result


def drop_red(cases: list[MutantCase], baseline: dict) -> list[MutantCase]:
    """Leave out the tests that fail with no mutant: they would kill every mutant."""
    red_kept, red_removed = set(baseline["red_kept"]), set(baseline["red_removed"])
    return [
        MutantCase(
            c.name,
            c.function,
            tuple(i for i in c.kept_ids if i not in red_kept),
            tuple(i for i in c.removed_ids if i not in red_removed),
            c.kept_tree,
            c.gone_tree,
        )
        for c in cases
    ]


def seconds_per_mutant(baseline: dict, runner: str) -> float:
    total = baseline["kept_seconds"] + SURVIVOR_SHARE * baseline["removed_seconds"]
    return total / FORK_SPEEDUP if runner == "fork" else total


def mutant_cases(
    modules: Sequence[str],
    kept: Side,
    gone: Side,
    removed: dict[str, frozenset[str]],
    skip: set[str] = frozenset(),
) -> dict[str, list[MutantCase]]:
    names = {m: module_names(kept.run_dir, m) for m in modules}
    cases = {m: module_cases(m, kept, gone, removed, names[m]) for m in modules}
    cases = {m: [c for c in cs if c.name not in skip] for m, cs in cases.items()}
    return {m: cs for m, cs in cases.items() if cs}


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def run_plan(args: argparse.Namespace) -> int:
    tree, work = Path(args.tree).resolve(), Path(args.work)
    require_mutmut(args.mutmut)
    cov, cases = load_measure(Path(args.measure), tree)
    index = build_index(tree)
    scoped = scope_files(tree, args.scope_dir)
    side = make_side(tree, cov, cases, index, scoped)
    scoped_files = [side.files[p] for p in scoped if p in side.files]
    pool, unconditional, skipped = pick_candidates(
        scoped_files, group_cases(cases), cov, read_keep(Path(args.keep))
    )
    by_id = {fn.id: fn for fn in pool}
    removed = greedy_cover(cov, pool)
    subjects = {fid: side.files[by_id[fid].file].subjects for fid in removed}
    put_back = [{"id": f, "reason": "no_subject"} for f in sorted(removed) if not subjects[f]]
    removed = {f: p for f, p in removed.items() if subjects[f]}
    modules = sorted({m for f in removed for m in subjects[f]})
    log(f"plan: {len(removed)} functions by coverage, {len(modules)} subject modules")
    gain = module_gain({f: by_id[f] for f in removed}, subjects)
    verdicts: list[Verdict] = []
    rows: list[dict] = []
    seconds: dict[str, float] = {}
    taken: list[str] = []
    if modules:
        selection = sorted({by_id[f].file for f in removed})
        side.run_dir = generate_mutants(tree, modules, work / "tree", args.mutmut, selection)
        zero = {f: subjects[f] for f in removed}
        case_map = mutant_cases(modules, side, side, zero)
        with open_runner(args.runner, args.mutmut, work / "run", args.processes) as run:
            base = measure_baseline(list(case_map), case_map, zero, run, args.processes)
            seconds = {m: len(case_map[m]) * seconds_per_mutant(base[m], args.runner) for m in base}
            free = [m for m in modules if m not in case_map]
            seconds.update({m: 0.0 for m in free})
            taken = take_modules(gain, seconds, args.budget_hours * 3600 * args.processes)
            broken = {m for m, row in base.items() if row["error"]}
            taken = [m for m in taken if m not in broken]
            red = {i for m in taken if m in base for i in base[m]["red_removed"]}
            for fid in sorted(removed):
                reason = "red_without_mutant" if fid in red else "module_not_proved"
                reason = "baseline_error" if subjects[fid] & broken else reason
                if fid in red or not subjects[fid] <= set(taken):
                    put_back.append({"id": fid, "reason": reason})
                    del removed[fid]
            live = {f: subjects[f] for f in removed}
            case_map = mutant_cases([m for m in taken if m in base], side, side, live)
            todo = [c for m, cs in case_map.items() for c in drop_red(cs, base[m])]
            log(f"plan: {len(todo)} mutants to play in {len(case_map)} modules")
            verdicts = prove_mutants(todo, run, args.processes, args.runner == "fork")
        for verdict in verdicts:
            for fid in verdict.put_back:
                if removed.pop(fid, None) is not None:
                    put_back.append({"id": fid, "reason": verdict.status, "mutant": verdict.name})
        cost = {m: round(seconds[m], 1) for m in modules}
        rows = [
            {"module": m, "taken": m in taken, "seconds": cost[m], "gain": round(gain[m], 1)}
            for m in modules
        ]
    total = count_lines(tree)
    gone_lines = sum(by_id[f].lines for f in removed) + sum(f.lines for f in unconditional)

    def stays(fid: str, file: ScannedFile) -> bool:
        return fid not in removed and bool(file.subjects) and file.subjects <= set(taken)

    plan = {
        "format": "hmp-removal-plan/1",
        "tree": str(tree),
        "measure": str(args.measure),
        "budget_hours": args.budget_hours,
        "runner": args.runner,
        "processes": args.processes,
        "skipped": {reason: sorted(ids) for reason, ids in skipped.items()},
        "removed": [
            {
                "id": f,
                "file": by_id[f].file,
                "function": f.split("::", 1)[1],
                "lines": by_id[f].lines,
                "subjects": sorted(subjects[f]),
                "proof": removed[f],
            }
            for f in sorted(removed)
        ],
        "unconditional": [
            {"id": f.id, "file": f.file, "function": f.id.split("::", 1)[1], "lines": f.lines}
            for f in sorted(unconditional, key=lambda f: f.id)
        ],
        "put_back": put_back,
        "mutants": [
            {"name": v.name, "function": v.function, "status": v.status, "killer": v.killer}
            for v in verdicts
        ],
        "modules": rows,
        "folds": fold_groups(scoped_files, stays),
        "move_candidates": move_targets(scoped_files, stays),
        "lines": {"total": total, "removed": gone_lines, "after": total - gone_lines},
        "hours_to_200k": hours_to_target(gain, seconds, total, 200_000, args.processes),
        "tests_sha256": {
            f: sha256_of(tree / f)
            for f in sorted({by_id[i].file for i in removed} | {u.file for u in unconditional})
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(
        f"plan: {len(removed)} functions leave on proof, {len(unconditional)} unconditionally, "
        f"{len(put_back)} put back, {gone_lines} test lines"
    )
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def is_fixture(node: ast.AST) -> tuple[bool, bool, str]:
    """Whether a function is a fixture, whether it is ``autouse``, and the name it is asked by."""
    for decorator in getattr(node, "decorator_list", []):
        text = ast.unparse(decorator)
        if re.match(r"(pytest\.)?fixture\b", text):
            name = re.search(r"name=['\"]([^'\"]+)['\"]", text)
            return True, "autouse=True" in text, name.group(1) if name else node.name  # type: ignore[attr-defined]
    return False, False, ""


def cut_lines(text: str, cuts: Sequence[tuple[int, int]]) -> str:
    drop = {n for start, end in cuts for n in range(start, end + 1)}
    return "".join(ln for n, ln in enumerate(text.splitlines(keepends=True), 1) if n not in drop)


def remove_functions(text: str, rel: str, ids: set[str]) -> str:
    """Cut the functions of ``ids``, and a class whose methods all leave."""
    cuts = []
    for node in ast.parse(text).body:
        if is_function(node) and f"{rel}::{node.name}" in ids:  # type: ignore[attr-defined]
            cuts.append(span_of(node))
        elif isinstance(node, ast.ClassDef):
            methods = list(filter(is_function, node.body))
            gone = [s for s in methods if f"{rel}::{node.name}::{s.name}" in ids]  # type: ignore[attr-defined]
            cuts.extend(
                [span_of(node)] if gone and len(gone) == len(methods) else map(span_of, gone)
            )
    return cut_lines(text, cuts)


def remove_dead_fixtures(text: str, rel: str) -> str:
    """Drop fixtures of the file that no remaining code asks for. ``autouse`` fixtures stay."""
    for _ in range(20):
        module = ast.parse(text)
        total: Counter[str] = Counter()
        for node in ast.walk(module):
            total.update(words_of(node))
        cuts = []
        for _, node, _owner in definitions(module, rel):
            fixture, autouse, name = is_fixture(node)
            own: Counter[str] = Counter()
            for sub in ast.walk(node):
                own.update(words_of(sub))
            if fixture and not autouse and total[name] - own[name] <= 0:
                cuts.append(span_of(node))
        if not cuts:
            return text
        text = cut_lines(text, cuts)
    return text


def words_of(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return WORDS.findall(node.value)
    return []


def drop_orphan_imports(before: str, after: str) -> str:
    """Remove the import names that the removed code used and that nothing uses any more."""
    orphan = names_used(ast.parse(before)) - names_used(ast.parse(after))
    cuts: list[tuple[int, int]] = []
    swaps: dict[int, tuple[int, str]] = {}
    for node in ast.parse(after).body:
        if (
            not isinstance(node, (ast.Import, ast.ImportFrom))
            or getattr(node, "module", "") == "__future__"
        ):
            continue
        kept = [a for a in node.names if (a.asname or a.name.split(".")[0]) not in orphan]
        if not kept:
            cuts.append((node.lineno, node.end_lineno))
        elif len(kept) < len(node.names):
            clone = copy.copy(node)
            clone.names = kept
            swaps[node.lineno] = (node.end_lineno, ast.unparse(clone) + "\n")
    out: list[str] = []
    resume = 0
    drop = {n for s, e in cuts for n in range(s, e + 1)}
    for n, line in enumerate(after.splitlines(keepends=True), 1):
        if n > resume and n not in drop:
            out.append(swaps[n][1] if n in swaps else line)
            resume = swaps[n][0] if n in swaps else resume
    return "".join(out)


def format_files(files: Sequence[Path], tree: Path) -> None:
    if files:
        command = [sys.executable, "-m", "ruff", "format", "--no-cache", *map(str, files)]
        done = subprocess.run(command, cwd=tree, capture_output=True, text=True)
        if done.returncode != 0:
            log(f"ruff format failed: {done.stderr.strip()[:300]}")


def cited_elsewhere(tree: Path, rel: str) -> bool:
    stem = re.compile(rf"\b{re.escape(Path(rel).stem)}\b")
    others = (p for p in (tree / "tests").rglob("*.py") if str(p.relative_to(tree)) != rel)
    return any(stem.search(p.read_text(encoding="utf-8", errors="replace")) for p in others)


def apply_plan(
    plan: dict, tree: Path, formatter: Callable[[Sequence[Path], Path], None] = format_files
) -> dict:
    """Edit ``tree`` so that the planned functions leave. conftest.py and tests/_helpers stay."""
    ids_by_file: dict[str, set[str]] = defaultdict(set)
    for row in [*plan["removed"], *plan["unconditional"]]:
        ids_by_file[row["file"]].add(row["id"])
    for rel, digest in plan["tests_sha256"].items():
        if not (tree / rel).is_file() or sha256_of(tree / rel) != digest:
            refuse("plan", plan_tree=plan["tree"], tree=tree)
    edited: list[Path] = []
    deleted: list[str] = []
    for rel, ids in sorted(ids_by_file.items()):
        if Path(rel).name == "conftest.py" or rel.startswith("tests/_helpers/"):
            continue
        path = tree / rel
        before = path.read_text(encoding="utf-8")
        after = remove_dead_fixtures(remove_functions(before, rel, ids), rel)
        after = drop_orphan_imports(before, after)
        if test_functions(ast.parse(after), rel) or cited_elsewhere(tree, rel):
            path.write_text(after, encoding="utf-8")
            edited.append(path)
        else:
            path.unlink()
            deleted.append(rel)
    formatter(edited, tree)
    return {"edited": len(edited), "deleted": deleted}


def run_apply(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    summary = apply_plan(plan, Path(args.tree).resolve())
    print(f"apply: {summary['edited']} files edited, {len(summary['deleted'])} deleted")
    return 0


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def load_moves(folder: Path | None) -> list[dict]:
    """Moves written by the tidy-up step, as JSON lines or a JSON list, one file per writer."""
    moves: list[dict] = []
    for path in sorted(folder.glob("*.json")) if folder else []:
        text = path.read_text(encoding="utf-8").strip()
        if text.startswith("["):
            moves.extend(json.loads(text))
        else:
            moves.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return moves


def package_modules(index: ModuleIndex, modules: set[str]) -> set[str]:
    """Every module of the layer packages that hold the given modules."""
    layers = {Path(m).parts[:2] for m in modules}
    return {p for p in index.modules.values() if Path(p).parts[:2] in layers}


def carried_mutants(plan: dict, before: Path, after: Path) -> set[str]:
    """Mutants the plan killed by a test that still exists unchanged: no replay needed."""
    same: dict[str, bool] = {}
    carried: set[str] = set()
    for row in plan.get("mutants", []):
        killer = row.get("killer")
        if row["status"] == "killed" and killer:
            if killer not in same:
                old = function_source_sha(before, killer)
                same[killer] = old is not None and old == function_source_sha(after, killer)
            if same[killer]:
                carried.add(row["name"])
    return carried


def run_check(args: argparse.Namespace) -> int:
    before, after = Path(args.before).resolve(), Path(args.after).resolve()
    work = Path(args.work)
    if package_digest(before) != package_digest(after):
        refuse("differs")
    require_mutmut(args.mutmut)
    loaded = {}
    for label, tree, given in (
        ("before", before, args.measure_before),
        ("after", after, args.measure_after),
    ):
        directory = Path(given) if given else work / f"measure-{label}"
        if not given:
            run_measure(tree, directory, args.tests or ["tests"], args.ignore, args.workers)
        loaded[label] = load_measure(directory, tree)
    (cov_b, cases_b), (cov_a, cases_a) = loaded["before"], loaded["after"]
    moved = {
        function_id_of(m["from_id"]) for m in load_moves(Path(args.moves) if args.moves else None)
    }
    removed_ids = set(group_cases(cases_b)) - set(group_cases(cases_a)) - moved
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8")) if args.plan else None
    planned = {r["id"] for r in [*plan["removed"], *plan["unconditional"]]} if plan else removed_ids
    unaccounted = sorted(removed_ids - planned)
    index = build_index(before)
    side_b, side_a = (
        make_side(before, cov_b, cases_b, index),
        make_side(after, cov_a, cases_a, index),
    )
    files = side_b.files
    removed = {
        f: files[f.split("::", 1)[0]].subjects for f in removed_ids if f.split("::", 1)[0] in files
    }
    removed = {f: s for f, s in removed.items() if s}
    lost = lost_items(cov_b, cov_a, removed_ids)
    modules = {m for s in removed.values() for m in s}
    modules = package_modules(index, modules) if args.scope == "package" else modules
    verdicts: list[Verdict] = []
    carried: set[str] = set()
    minutes = 0.0
    broken: list[str] = []
    if modules:
        selection = sorted({fid.split("::", 1)[0] for fid in side_a.ids})
        side_a.run_dir = generate_mutants(
            after, sorted(modules), work / "after", args.mutmut, selection
        )
        side_b.run_dir = swap_tests(side_a.run_dir, before, work / "before")
        carried = carried_mutants(plan, before, after) if plan else set()
        case_map = mutant_cases(sorted(modules), side_a, side_b, removed, carried)
        with open_runner(args.runner, args.mutmut, work / "run", args.processes) as run:
            base = measure_baseline(list(case_map), case_map, removed, run, args.processes)
            seconds = sum(len(case_map[m]) * seconds_per_mutant(base[m], args.runner) for m in base)
            minutes = round(seconds / args.processes / 60, 1)
            if args.budget_minutes is not None and minutes > args.budget_minutes:
                refuse("budget", n=minutes, m=args.budget_minutes)
            broken = sorted(m for m, row in base.items() if row["error"])
            todo = [
                c for m, cs in case_map.items() if m not in broken for c in drop_red(cs, base[m])
            ]
            verdicts = prove_mutants(todo, run, args.processes, args.runner == "fork")
    bad = [v for v in verdicts if v.status in ("lost", "error")]
    restore = {f for v in bad for f in v.put_back} | set(unaccounted)
    restore |= {f for item in lost.values() for f in item["covered_by"]}
    result = {
        "format": "hmp-removal-check/1",
        "before": str(before),
        "after": str(after),
        "scope": args.scope,
        "removed_ids": len(removed_ids),
        "unaccounted_ids": unaccounted,
        "lost_coverage": lost,
        "baseline_errors": broken,
        "lost_mutants": [
            {"name": v.name, "function": v.function, "status": v.status, "killer": v.killer}
            | {"put_back": list(v.put_back)}
            for v in bad
        ],
        "mutants": {
            "replayed": len(verdicts),
            "carried": len(carried),
            "killed": sum(v.status == "killed" for v in verdicts),
            "proved": sum(v.status == "proved" for v in verdicts),
        },
        "estimated_minutes": minutes,
        "restore_files": sorted({f.split("::", 1)[0] for f in restore}),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"check: {len(removed_ids)} test functions gone, {len(lost)} files lose coverage, "
        f"{len(bad)} mutants lost, {len(unaccounted)} ids unaccounted, {len(broken)} baselines in error"
    )
    return 1 if (lost or bad or unaccounted or broken) else 0


# ---------------------------------------------------------------------------
# replay and command line
# ---------------------------------------------------------------------------


def run_replay(args: argparse.Namespace) -> int:
    """Play named mutants one by one and write ``<name> <code>`` lines, as a replay file does."""
    names = Path(args.names).read_text(encoding="utf-8").split()
    run_dir = str(Path(args.run_dir).resolve())
    jobs = [Job(n, tuple(args.tests), run_dir) for n in names]
    started = time.monotonic()
    with open_runner(
        args.runner, args.mutmut, Path(args.work), args.processes, args.timeout
    ) as run:
        codes = {n: o.code for n, o in zip(names, run_jobs(jobs, run, args.processes), strict=True)}
    Path(args.out).write_text("".join(f"{n} {c}\n" for n, c in codes.items()), encoding="utf-8")
    killed = {n for n, c in codes.items() if c != 0}
    seconds = round(time.monotonic() - started, 1)
    print(f"replay: {len(names)} mutants, {len(killed)} killed, {seconds} s, runner {args.runner}")
    if not args.compare:
        return 0
    lines = Path(args.compare).read_text(encoding="utf-8").splitlines()
    reference = dict(ln.split() for ln in lines if ln.strip())
    differ = sorted(n for n in names if n in reference and (reference[n] != "0") != (n in killed))
    print(f"replay: {len(differ)} differ from {args.compare}")
    for name in differ[:20]:
        print(f"  {name}: reference {reference[name]}, now {codes[name]}")
    return 1 if differ else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="removal_proof.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)

    def command(name: str, help: str, required: Sequence[str], optional: dict | None = None):
        p = sub.add_parser(name, help=help)
        for flag in required:
            p.add_argument(f"--{flag}", required=True)
        for flag, kwargs in (optional or {}).items():
            p.add_argument(f"--{flag}", **kwargs)
        return p

    def suite(p: argparse.ArgumentParser) -> None:
        p.add_argument("--tests", nargs="+", action="extend", default=[])
        p.add_argument("--ignore", nargs="+", action="extend", default=[])
        p.add_argument("--workers", type=int, default=8)

    def runner(p: argparse.ArgumentParser) -> None:
        p.add_argument("--runner", choices=("fresh", "fork"), default="fresh")
        p.add_argument("--processes", type=int, default=16)

    suite(command("measure", "run the suite with a coverage context per test", ["tree", "out"]))
    plan = command("plan", "choose the test functions that leave, and prove it", ["tree"])
    for flag in ("measure", "keep", "mutmut", "work", "out"):
        plan.add_argument(f"--{flag}", required=True)
    plan.add_argument("--scope-dir", action="append", default=[], required=True)
    plan.add_argument(
        "--budget-hours",
        type=float,
        default=10.0,
        help="choose the modules from the baseline estimate of their cost, it does not stop the run",
    )
    runner(plan)
    command("apply", "edit a checkout so that the planned functions leave", ["plan", "tree"])
    check = command("check", "compare two trees with the same library code", ["before", "after"])
    for flag in ("mutmut", "work", "out"):
        check.add_argument(f"--{flag}", required=True)
    check.add_argument("--scope", choices=("module", "package"), default="module")
    for flag in ("plan", "moves", "measure-before", "measure-after"):
        check.add_argument(f"--{flag}")
    check.add_argument("--budget-minutes", type=float)
    suite(check)
    runner(check)
    replay = command(
        "replay", "play mutants one by one", ["run-dir", "names", "mutmut", "work", "out"]
    )
    replay.add_argument("--tests", nargs="+", required=True)
    replay.add_argument("--compare")
    replay.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    runner(replay)
    command("worker", "warm worker of the fork runner", ["run-dir"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "worker":
        worker_serve(args.run_dir)
        return 0
    try:
        if args.action == "measure":
            meta = run_measure(
                Path(args.tree).resolve(),
                Path(args.out),
                args.tests or ["tests"],
                args.ignore,
                args.workers,
            )
            print(f"measure: {meta['cases']} cases in {meta['seconds']} s")
            return 0
        actions = {"plan": run_plan, "apply": run_apply, "check": run_check, "replay": run_replay}
        return actions[args.action](args)
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
