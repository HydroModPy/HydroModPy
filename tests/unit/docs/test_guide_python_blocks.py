"""The Python blocks of the guides and of Get started are valid, and name real things.

sybil reads every ```python block of these pages. Almost none can run alone: a
block starts a run of example 04 or opens a project that holds finished runs.
So each block is classified in ``guide_python_blocks.toml``: executed, or not
executed with the reason. A new block fails the test until it is classified.

Every block, executed or not, is held to what a reader can check without a run:

- it parses;
- each ``hydromodpy`` import resolves;
- each ``hmp.<name>`` exists in the package;
- each keyword of an ``hmp.<name>(...)`` call is one the function accepts.

CI installs sybil and sets ``HMP_REQUIRE_SYBIL=1``, so a missing sybil fails
there. Elsewhere the test is skipped.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import tomllib
from pathlib import Path
from typing import Any

import pytest

try:
    from sybil import Document
    from sybil.evaluators.python import PythonEvaluator
    from sybil.parsers.markdown import CodeBlockParser
except ImportError:  # pragma: no cover - depends on the environment
    if os.environ.get("HMP_REQUIRE_SYBIL"):
        raise
    pytest.skip("sybil is not installed", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "docs" / "source"
PAGE_DIRS = ("guides", "get-started")
MANIFEST = Path(__file__).with_name("guide_python_blocks.toml")
# The pages held about 52 blocks when this test was written. Far fewer means
# the reader stopped finding them.
FLOOR = 45


def _manifest() -> dict[str, Any]:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def _pages() -> list[Path]:
    pages: list[Path] = []
    for directory in PAGE_DIRS:
        pages.extend(sorted((SOURCE / directory).rglob("*.md")))
    return pages


def _blocks(page: Path) -> list[Any]:
    """Return the sybil examples of the Python blocks of ``page``, in order."""
    document = Document.parse(
        str(page), CodeBlockParser("python", evaluator=PythonEvaluator()), encoding="utf-8"
    )
    return list(document)


def _all_blocks() -> list[tuple[str, int, Any]]:
    out: list[tuple[str, int, Any]] = []
    for page in _pages():
        rel = page.relative_to(SOURCE).as_posix()
        out.extend((rel, number, block) for number, block in enumerate(_blocks(page), start=1))
    return out


@pytest.fixture(scope="module")
def blocks() -> list[tuple[str, int, Any]]:
    return _all_blocks()


def test_the_pages_hold_python_blocks(blocks: list[tuple[str, int, Any]]) -> None:
    assert len(blocks) >= FLOOR


def test_every_block_is_classified(blocks: list[tuple[str, int, Any]]) -> None:
    manifest = _manifest()
    classified = {
        (page, int(number)): value
        for page, entries in manifest["blocks"].items()
        for number, value in entries.items()
    }
    found = {(page, number) for page, number, _ in blocks}
    new = sorted(found - classified.keys())
    stale = sorted(classified.keys() - found)
    assert not new, f"blocks with no entry in {MANIFEST.name}: {new}"
    assert not stale, f"entries of {MANIFEST.name} with no block: {stale}"
    unknown = {v for v in classified.values() if v != "run" and v not in manifest["reasons"]}
    assert not unknown, f"reasons not declared in [reasons]: {sorted(unknown)}"


def test_every_block_parses(blocks: list[tuple[str, int, Any]]) -> None:
    bad: list[str] = []
    for page, number, block in blocks:
        try:
            ast.parse(block.parsed)
        except SyntaxError as exc:
            bad.append(f"{page} block {number} (line {block.line}): {exc.msg}")
    assert not bad, "\n".join(bad)


def _aliases(trees: list[ast.AST]) -> set[str]:
    """Return the names under which a page imports ``hydromodpy``."""
    names = {"hmp"}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.asname or a.name for a in node.names if a.name == "hydromodpy")
    return names


def _dotted(node: ast.AST) -> list[str] | None:
    """Return ``["hmp", "Project", "rerun"]`` for the attribute chain ``hmp.Project.rerun``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return [node.id, *reversed(parts)]
    return None


def _resolve(chain: list[str]) -> Any:
    """Return the object ``chain`` names in the package, or raise ``AttributeError``."""
    obj: Any = importlib.import_module("hydromodpy")
    for part in chain[1:]:
        obj = getattr(obj, part)
    return obj


def _problems(page: str, number: int, block: Any, aliases: set[str]) -> list[str]:
    where = f"{page} block {number} (line {block.line})"
    tree = ast.parse(block.parsed)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "hydromodpy":
            try:
                module = importlib.import_module(node.module)
            except ImportError as exc:
                out.append(f"{where}: cannot import {node.module}: {exc}")
                continue
            for alias in node.names:
                if not hasattr(module, alias.name):
                    try:
                        importlib.import_module(f"{node.module}.{alias.name}")
                    except ImportError:
                        out.append(f"{where}: {node.module} has no {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "hydromodpy":
                    try:
                        importlib.import_module(alias.name)
                    except ImportError as exc:
                        out.append(f"{where}: cannot import {alias.name}: {exc}")
        elif isinstance(node, ast.Attribute):
            chain = _dotted(node)
            if chain and chain[0] in aliases and len(chain) > 1:
                try:
                    _resolve(chain)
                except AttributeError:
                    out.append(f"{where}: hydromodpy has no {'.'.join(chain[1:])}")
        if isinstance(node, ast.Call):
            chain = _dotted(node.func)
            if chain and chain[0] in aliases and len(chain) > 1:
                out.extend(_keyword_problems(where, chain, node))
    return out


def _keyword_problems(where: str, chain: list[str], call: ast.Call) -> list[str]:
    try:
        target = _resolve(chain)
        parameters = inspect.signature(target).parameters
    except (AttributeError, ValueError, TypeError):
        # A missing name is reported by the attribute check; a builtin or an
        # object with no signature has no keyword list to hold the call to.
        return []
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return []
    named = [k.arg for k in call.keywords if k.arg is not None]
    return [
        f"{where}: {'.'.join(chain)}() takes no keyword {name!r}"
        for name in named
        if name not in parameters
    ]


def test_every_block_names_real_things(blocks: list[tuple[str, int, Any]]) -> None:
    by_page: dict[str, list[tuple[int, Any]]] = {}
    for page, number, block in blocks:
        by_page.setdefault(page, []).append((number, block))
    problems: list[str] = []
    for page, items in by_page.items():
        aliases = _aliases([ast.parse(block.parsed) for _, block in items])
        for number, block in items:
            problems.extend(_problems(page, number, block, aliases))
    assert not problems, "\n".join(problems)


def _runnable() -> list[tuple[str, int]]:
    return sorted(
        (page, int(number))
        for page, entries in _manifest()["blocks"].items()
        for number, value in entries.items()
        if value == "run"
    )


@pytest.mark.parametrize(("page", "number"), _runnable(), ids=lambda v: str(v))
def test_a_self_contained_block_runs(
    page: str, number: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, text in _manifest().get("files", {}).get(page, {}).get(str(number), {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    blocks = _blocks(SOURCE / page)
    # Earlier blocks of the page share the namespace: run the ones marked "run".
    manifest = _manifest()["blocks"][page]
    for index, block in enumerate(blocks, start=1):
        if index <= number and manifest[str(index)] == "run":
            block.evaluate()


def test_a_block_that_cannot_run_is_not_run() -> None:
    """The reason table, not the reader's luck, decides what is executed."""
    manifest = _manifest()
    assert "run" not in manifest["reasons"]
    assert set(manifest["reasons"]) >= {"fragment", "finished-runs"}


def test_the_static_check_catches_a_renamed_name() -> None:
    from types import SimpleNamespace

    source = (
        "import hydromodpy as hmp\n"
        "from hydromodpy.display import no_such_helper\n"
        "hmp.no_such_verb('x')\n"
        "hmp.open('.', read_only=False)\n"
        "hmp.read(run, 'head', timestep=-1)\n"
        "hmp.run('a.toml', K=1e-5)\n"
    )
    block = SimpleNamespace(parsed=source, line=1)
    problems = _problems("page.md", 1, block, {"hmp"})
    joined = "\n".join(problems)
    assert "hydromodpy.display has no no_such_helper" in joined
    assert "hydromodpy has no no_such_verb" in joined
    assert "hmp.read() takes no keyword 'timestep'" in joined
    # A keyword the signature accepts, and the free keywords of hmp.run, pass.
    assert "read_only" not in joined
    assert "hmp.run()" not in joined
