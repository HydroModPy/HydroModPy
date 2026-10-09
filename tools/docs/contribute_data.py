"""Facts of the contributor pages, read from the files that own them.

Each function reads one source of truth and returns plain data. Nothing here is
typed by hand: a wrong row is fixed in its source, never in a page.

- layer graph: ``tests/unit/architecture/layer_matrix.yaml``;
- architecture gates: the module docstrings of ``tests/unit/architecture/test_*.py``
  and the ``*_layout.yaml`` contracts beside them;
- CI workflows: ``.github/workflows/*.yml``;
- test inventory: the test files of ``tests/``, read as syntax trees, and the
  markers of ``pytest.ini`` (no test is collected or run);
- packages and counts: the package folders, their ``README.md`` and the
  registries of the code (variables, figures, solvers, sources, steps);
- storage tree: ``hydromodpy.results.storage.contract`` and
  ``hydromodpy.core.state.paths``;
- environment variables: ``hydromodpy.core.env`` and a scan of the code;
- extras: ``[project.optional-dependencies]`` of ``pyproject.toml``.

The Sphinx extension ``docs/source/_ext/hmp_contribute.py`` renders them.
"""

from __future__ import annotations

import ast
import configparser
import re
import tomllib
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROOT_LAYER = "<root>"
ARCHITECTURE_DIR = Path("tests/unit/architecture")
LAYER_MATRIX = ARCHITECTURE_DIR / "layer_matrix.yaml"
WORKFLOWS_DIR = Path(".github/workflows")

ENV_NAME = re.compile(r"HMP_[A-Z][A-Z0-9_]*")
ENV_PY_ROOTS = ("hydromodpy", "tools", "tests", "validation_cases", "validity_frame")
ENV_PY_FILES = ("docs/source/conf.py", "poly.py")
ENV_PY_DIRS = ("docs/source/_ext",)
ENV_TEXT_GLOBS = (".github/workflows/*.yml", "docs/Makefile", "Dockerfile")
ENV_SCAN_EXCLUDED = (
    "hydromodpy/core/env.py",
    "tests/unit/architecture/test_env_vars_are_registered.py",
)
"""The registry and its gate name every variable; they are not readers."""

SKIP_PARTS = {"__pycache__", ".git", "node_modules", "build"}


def first_paragraph(text: str | None) -> str:
    """First paragraph of a docstring or a README, on one line."""
    body = (text or "").strip()
    paragraph = re.split(r"\n\s*\n", body, maxsplit=1)[0] if body else ""
    return " ".join(paragraph.split())


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if not SKIP_PARTS & set(p.parts))


def _rel(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


# -- layer graph ---------------------------------------------------------------


def load_layer_matrix(repo: Path = ROOT) -> dict[str, Any]:
    return yaml.safe_load((repo / LAYER_MATRIX).read_text(encoding="utf-8"))


def _greedy_order(nodes: list[str], edges: set[tuple[str, str]]) -> list[str]:
    """Order the layers so that few granted edges point backwards (Eades et al.).

    Sinks go to the end and sources to the front; when neither is left, the
    node with the largest out-degree minus in-degree goes to the front. Ties
    keep the order of the contract, so the result is deterministic.
    """
    remaining = list(nodes)
    head: list[str] = []
    tail: list[str] = []

    def degree(node: str, outgoing: bool) -> int:
        live = set(remaining)
        if outgoing:
            return sum(1 for u, v in edges if u == node and v in live)
        return sum(1 for u, v in edges if v == node and u in live)

    while remaining:
        moved = True
        while moved:
            moved = False
            for node in list(remaining):
                if degree(node, outgoing=True) == 0:
                    tail.insert(0, node)
                    remaining.remove(node)
                    moved = True
            for node in list(remaining):
                if degree(node, outgoing=False) == 0:
                    head.append(node)
                    remaining.remove(node)
                    moved = True
        if remaining:
            best = max(
                remaining,
                key=lambda n: (degree(n, True) - degree(n, False), -nodes.index(n)),
            )
            head.append(best)
            remaining.remove(best)
    return head + tail


def _reaches(start: str, goal: str, edges: set[tuple[str, str]], skip: tuple[str, str]) -> bool:
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        for u, v in edges:
            if u != node or (u, v) == skip or v in seen:
                continue
            if v == goal:
                return True
            seen.add(v)
            stack.append(v)
    return False


def layer_graph(matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    """The granted imports of the layer matrix, reduced for drawing.

    The matrix is a set of permissions, not a hierarchy: some pairs grant each
    other (``config`` and ``schema``, for instance). The layers are first put
    in an order where as few granted edges as possible point upwards. The
    edges that still do are kept apart. The others are reduced transitively:
    an edge is dropped when a longer path of granted edges joins the same two
    layers.
    """
    matrix = matrix if matrix is not None else load_layer_matrix()
    allowed: dict[str, list[str]] = matrix["allowed"]
    layers = list(allowed)
    granted = {(u, v) for u, targets in allowed.items() for v in targets or [] if u != v}
    order = _greedy_order(layers, granted)
    rank = {name: i for i, name in enumerate(order)}
    downward = {(u, v) for u, v in granted if rank[u] < rank[v]}
    upward = sorted((u, v) for u, v in granted if rank[u] > rank[v])
    reduced = sorted(e for e in downward if not _reaches(e[0], e[1], downward, e))
    tolerated = [
        (t["src"], t["tgt"], t.get("reason", ""))
        for t in matrix.get("tolerances") or []
        if (t["src"], t["tgt"]) not in granted
    ]
    return {
        "layers": order,
        "granted": len(granted),
        "granted_with_self": sum(len(v or []) for v in allowed.values()),
        "reduced": reduced,
        "upward": upward,
        "tolerated": tolerated,
        "exempt_files": list(matrix.get("exempt_files") or []),
    }


def layer_label(name: str) -> str:
    return "hydromodpy (root)" if name == ROOT_LAYER else name


def layer_dot(graph: dict[str, Any]) -> str:
    """Graphviz source of the reduced graph. Upward and tolerated edges are dashed."""
    ids = {name: f"n{i}" for i, name in enumerate(graph["layers"])}
    lines = [
        "digraph layers {",
        '  graph [rankdir=TB, bgcolor="transparent", nodesep=0.25, ranksep=0.45];',
        '  node [shape=box, style="rounded,filled", fillcolor="#e8f0f8", color="#5b7fa6",'
        ' fontcolor="#1d2a38", fontname="Helvetica", fontsize=11, height=0.3];',
        '  edge [color="#7a8a9a", arrowsize=0.6];',
    ]
    for name in graph["layers"]:
        lines.append(f'  {ids[name]} [label="{layer_label(name)}"];')
    for u, v in graph["reduced"]:
        lines.append(f"  {ids[u]} -> {ids[v]};")
    for u, v in graph["upward"]:
        lines.append(f'  {ids[u]} -> {ids[v]} [style=dashed, color="#c0632b", constraint=false];')
    for u, v, _reason in graph["tolerated"]:
        lines.append(f'  {ids[u]} -> {ids[v]} [style=dotted, color="#8a5bb0", constraint=false];')
    lines.append("}")
    return "\n".join(lines) + "\n"


# -- architecture gates --------------------------------------------------------


def _test_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names.extend(
                f"{node.name}.{item.name}"
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                and item.name.startswith("test")
            )
    return names


def architecture_gates(repo: Path = ROOT) -> list[dict[str, Any]]:
    """One row per gate module of ``tests/unit/architecture``."""
    folder = repo / ARCHITECTURE_DIR
    contracts = sorted(p.name for p in folder.glob("*.yaml"))
    rows = []
    for path in sorted(folder.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        rows.append(
            {
                "file": _rel(path, repo),
                "rule": first_paragraph(ast.get_docstring(tree)),
                "contracts": [name for name in contracts if name in text],
                "tests": _test_names(tree),
            }
        )
    return rows


def layout_contracts(repo: Path = ROOT) -> list[dict[str, Any]]:
    """One row per ``<package>_layout.yaml``: the parts it orders and its other keys."""
    rows = []
    for path in sorted((repo / ARCHITECTURE_DIR).glob("*_layout.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        allowed = data.get("allowed") or {}
        rows.append(
            {
                "file": _rel(path, repo),
                "package": path.name.removesuffix("_layout.yaml"),
                "parts": list(allowed),
                "other_keys": sorted(k for k in data if k != "allowed"),
            }
        )
    return rows


# -- CI workflows --------------------------------------------------------------


def _triggers(on: Any) -> list[str]:
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(item) for item in on]
    out: list[str] = []
    for event, spec in (on or {}).items():
        if event == "schedule":
            out.extend(f"schedule ``{item['cron']}`` (UTC)" for item in spec or [])
            continue
        detail: list[str] = []
        if isinstance(spec, dict):
            for key in ("branches", "tags"):
                if spec.get(key):
                    detail.append(f"{key} {', '.join(map(str, spec[key]))}")
            if spec.get("paths"):
                detail.append(f"{len(spec['paths'])} path filters")
        out.append(f"{event} ({'; '.join(detail)})" if detail else str(event))
    return out


def _step_label(step: dict[str, Any]) -> str:
    if step.get("name"):
        return str(step["name"])
    if step.get("uses"):
        return f"``{step['uses']}``"
    first = str(step.get("run") or "").strip().splitlines()
    return f"``{first[0]}``" if first else "(empty step)"


def ci_workflows(repo: Path = ROOT) -> list[dict[str, Any]]:
    """One row per workflow file, with its triggers and the steps of each job."""
    rows = []
    for path in sorted((repo / WORKFLOWS_DIR).glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # PyYAML reads the bare key ``on`` as the boolean True.
        on = data.get("on", data.get(True))
        jobs = []
        for job_id, job in (data.get("jobs") or {}).items():
            jobs.append(
                {
                    "id": job_id,
                    "name": str(job.get("name") or job_id),
                    "matrix": bool((job.get("strategy") or {}).get("matrix")),
                    "needs": [job.get("needs")]
                    if isinstance(job.get("needs"), str)
                    else list(job.get("needs") or []),
                    "steps": [_step_label(s) for s in job.get("steps") or []],
                    "uses": job.get("uses"),
                }
            )
        rows.append(
            {
                "file": _rel(path, repo),
                "name": str(data.get("name") or path.stem),
                "triggers": _triggers(on),
                "jobs": jobs,
            }
        )
    return rows


# -- test inventory ------------------------------------------------------------


TIER_ORDER = (
    "unit",
    "integration",
    "regression",
    "validation",
    "e2e",
    "characterization",
    "contract",
    "performance",
)


def _decorator_marks(decorators: list[ast.expr]) -> list[str]:
    marks = []
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            marks.append(target.attr)
    return marks


def _module_marks(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            values = (
                node.value.elts if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
            )
            return _decorator_marks(list(values))
    return []


def pytest_markers(repo: Path = ROOT) -> dict[str, str]:
    """The markers declared in ``pytest.ini``, with their description."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(repo / "pytest.ini", encoding="utf-8")
    out: dict[str, str] = {}
    for line in parser.get("pytest", "markers", fallback="").splitlines():
        if ":" in line:
            name, _, text = line.partition(":")
            out[name.strip()] = text.strip()
    return out


def suite_inventory(repo: Path = ROOT) -> dict[str, Any]:
    """Test files and test functions per tier and folder, and marker use.

    Counts functions as written. A parametrized function counts once here,
    whereas pytest collects one item per parameter set.
    """
    tests_dir = repo / "tests"
    tiers: dict[str, Counter] = defaultdict(Counter)
    folders: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    mark_files: Counter = Counter()
    mark_functions: Counter = Counter()
    for path in sorted(tests_dir.rglob("test_*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(tests_dir).parts
        if len(rel) < 2:
            continue
        tier = rel[0]
        folder = rel[1] if len(rel) > 2 else "(tier root)"
        tree = _parse(path)
        if tree is None:
            continue
        functions = 0
        parametrized = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test"
            ):
                functions += 1
                marks = _decorator_marks(node.decorator_list)
                if "parametrize" in marks:
                    parametrized += 1
                for mark in set(marks):
                    mark_functions[mark] += 1
        for mark in set(_module_marks(tree)):
            mark_files[mark] += 1
        for counter in (tiers[tier], folders[tier][folder]):
            counter["files"] += 1
            counter["functions"] += functions
            counter["parametrized"] += parametrized
    ordered = [t for t in TIER_ORDER if t in tiers] + sorted(set(tiers) - set(TIER_ORDER))
    declared = pytest_markers(repo)
    markers = [
        {
            "name": name,
            "description": text,
            "functions": mark_functions.get(name, 0),
            "files": mark_files.get(name, 0),
        }
        for name, text in sorted(declared.items())
    ]
    return {
        "tiers": [{"tier": t, **dict(tiers[t])} for t in ordered],
        "folders": {
            t: [{"folder": f, **dict(c)} for f, c in sorted(folders[t].items())] for t in ordered
        },
        "markers": markers,
        "undeclared_marks": sorted(
            (set(mark_functions) | set(mark_files))
            - set(declared)
            - {"parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings"}
        ),
    }


# -- packages and registry counts ----------------------------------------------


def _readme_summary(readme: Path) -> str:
    text = readme.read_text(encoding="utf-8")
    body = re.sub(r"\A\s*#[^\n]*\n", "", text, count=1)
    summary = first_paragraph(body)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", summary)


def package_map(repo: Path = ROOT) -> list[dict[str, Any]]:
    """One row per sub-package of ``hydromodpy``: its README summary and its size."""
    layers = set(load_layer_matrix(repo)["allowed"])
    rows = []
    for folder in sorted(p for p in (repo / "hydromodpy").iterdir() if p.is_dir()):
        if not (folder / "__init__.py").exists():
            continue
        readme = folder / "README.md"
        modules = _py_files(folder)
        rows.append(
            {
                "package": folder.name,
                "summary": _readme_summary(readme) if readme.exists() else "",
                "readme": _rel(readme, repo) if readme.exists() else None,
                "modules": len(modules),
                "lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in modules),
                "layer": folder.name in layers,
            }
        )
    return rows


def registry_counts(repo: Path = ROOT) -> list[dict[str, Any]]:
    """What the registries of the code hold, counted when the page is built."""
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
    from hydromodpy.data.source.registry import list_source_ids
    from hydromodpy.display import list_figures
    from hydromodpy.schema.sources import SOURCES
    from hydromodpy.solver.base import registry as solver_registry
    from hydromodpy.workflow.orchestrator import standard_steps

    matrix = load_layer_matrix(repo)
    return [
        {
            "what": "Layers of the import matrix",
            "source": LAYER_MATRIX.as_posix(),
            "names": [layer_label(n) for n in matrix["allowed"]],
        },
        {
            "what": "Pipeline steps of a run, in order",
            "source": "hydromodpy.workflow.orchestrator.standard_steps",
            "names": [step.name for step in standard_steps()],
        },
        {
            "what": "Data variables",
            "source": "hydromodpy.data.loading._dispatch.VARIABLE_SPECS",
            "names": sorted(VARIABLE_SPECS),
        },
        {
            "what": "Data sources with a licence entry",
            "source": "hydromodpy.schema.sources.SOURCES",
            "names": sorted(SOURCES),
        },
        {
            "what": "Sources served through the data-source port",
            "source": "hydromodpy.data.source.registry.list_source_ids",
            "names": list(list_source_ids()),
        },
        {
            "what": "Process and solver pairs",
            "source": "hydromodpy.solver.base.registry.list_pairs",
            "names": [f"{p}/{s}" for p, s in sorted(solver_registry.list_pairs())],
        },
        {
            "what": "Figures",
            "source": "hydromodpy.display.list_figures",
            "names": sorted(spec.name for spec in list_figures()),
        },
    ]


# -- storage tree --------------------------------------------------------------


def constant_docs(path: Path) -> dict[str, str]:
    """Docstring of each module-level constant: a string after it, or ``#:`` lines above."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    docs: dict[str, str] = {}
    body = tree.body
    for i, node in enumerate(body):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        doc = ""
        nxt = body[i + 1] if i + 1 < len(body) else None
        if (
            isinstance(nxt, ast.Expr)
            and isinstance(nxt.value, ast.Constant)
            and isinstance(nxt.value.value, str)
        ):
            doc = first_paragraph(nxt.value.value)
        else:
            comments = []
            j = node.lineno - 2
            while j >= 0 and lines[j].strip().startswith("#:"):
                comments.insert(0, lines[j].strip()[2:].strip())
                j -= 1
            doc = " ".join(comments)
        for name in names:
            docs[name] = doc
    return docs


def _sphinx_roles_to_literals(text: str) -> str:
    return re.sub(r":[a-z]+:`~?([^`]+)`", r"``\1``", text)


def storage_tree() -> dict[str, Any]:
    """The project, run, session and workspace folders, named by their constants."""
    import hydromodpy.core.state.paths as paths
    import hydromodpy.results.storage.contract as contract
    import hydromodpy.schema.generated_views as views

    docs: dict[str, tuple[str, str]] = {}
    for module in (paths, contract, views):
        source = Path(module.__file__)
        for name, doc in constant_docs(source).items():
            docs[name] = (f"{module.__name__}.{name}", _sphinx_roles_to_literals(doc))
    by_value: dict[str, str] = {}
    for module in (views, contract, paths):
        for name in dir(module):
            value = getattr(module, name)
            if name.isupper() and isinstance(value, str) and name in docs:
                by_value.setdefault(value, name)

    def entry(name: str, depth: int, label: str | None = None) -> dict[str, Any]:
        value = label or getattr(paths, name, None) or getattr(contract, name, None)
        value = value or getattr(views, name)
        is_dir = name.endswith("_DIRNAME") or name == "FIELDS_STORE_NAME"
        symbol, doc = docs.get(name, ("", ""))
        return {
            "path": value + ("/" if is_dir else ""),
            "depth": depth,
            "constant": symbol,
            "doc": doc,
        }

    def placeholder(text: str, depth: int, doc: str, symbol: str = "") -> dict[str, Any]:
        return {"path": text, "depth": depth, "constant": symbol, "doc": doc}

    order = [n for n in docs if n in contract.__dict__ or n in views.__dict__]
    run_names = sorted(
        contract.ALLOWED_RUN_ENTRIES,
        key=lambda v: (
            v not in contract.REQUIRED_RUN_ENTRIES,
            order.index(by_value[v]) if v in by_value and by_value[v] in order else 999,
            v,
        ),
    )
    project: list[dict[str, Any]] = [
        placeholder("<project>/", 0, "One project, the root of its runs and sessions."),
        entry("PROJECT_MARKER_FILENAME", 1),
        entry("CONFIGS_DIRNAME", 1),
        entry("RUNS_DIRNAME", 1),
        placeholder(
            "<run>/",
            2,
            "One run, named after the run itself, with its ``.vN`` version suffix.",
        ),
    ]
    for value in run_names:
        row = entry(by_value[value], 3)
        row["required"] = value in contract.REQUIRED_RUN_ENTRIES
        project.append(row)
        if value == contract.TABLES_DIRNAME:
            project.append(
                placeholder(
                    f"<view>{contract.PARQUET_FILE_SUFFIX}",
                    4,
                    docs["PARQUET_FILE_SUFFIX"][1],
                    docs["PARQUET_FILE_SUFFIX"][0],
                )
            )
    for value in sorted(contract.RUN_SCRATCH_ENTRIES):
        symbol, doc = docs["RUN_SCRATCH_ENTRIES"]
        project.append(placeholder(f"{value}/", 3, doc, symbol))
    project += [
        entry("SESSIONS_DIRNAME", 1),
        placeholder("<session>/", 2, "One calibration or spin-up session."),
        entry("SESSION_DESCRIPTOR_FILENAME", 3),
        entry("SESSION_TRIALS_FILENAME", 3),
        entry("SESSION_TRIAL_SERIES_DIRNAME", 3),
        placeholder(
            contract.session_trial_series_filename(1),
            4,
            first_paragraph(contract.session_trial_series_filename.__doc__),
            "hydromodpy.results.storage.contract.session_trial_series_filename",
        ),
        entry("SHARE_DIRNAME", 1),
        entry("REPORTS_DIRNAME", 2),
        entry("INTERNAL_DIRNAME", 1),
        entry("CATALOG_FILENAME", 2),
        placeholder(
            paths.scratch_root_for(Path("p")).name + "/",
            2,
            first_paragraph(paths.scratch_root_for.__doc__),
            "hydromodpy.core.state.paths.scratch_root_for",
        ),
        placeholder(
            "<run>.p<pid>/",
            3,
            first_paragraph(paths.scratch_dir_for.__doc__),
            "hydromodpy.core.state.paths.scratch_dir_for",
        ),
        entry("PREPROCESSING_DIRNAME", 4),
    ]
    workspace = [
        placeholder("<workspace>/", 0, "A folder that holds several projects."),
        entry("WORKSPACE_TOML_FILENAME", 1),
        entry("PROJECTS_DIRNAME", 1),
        placeholder("<project>/", 2, "One project, laid out as above."),
    ]
    machine = [
        placeholder(
            "<state>/",
            0,
            first_paragraph(paths.state_dir.__doc__) + " Set by ``HMP_STATE_HOME``.",
            "hydromodpy.core.state.paths.state_dir",
        ),
        entry("INDEX_FILENAME", 1),
        placeholder(
            "<cache>/",
            0,
            first_paragraph(paths.cache_dir.__doc__) + " Set by ``HMP_CACHE_HOME``.",
            "hydromodpy.core.state.paths.cache_dir",
        ),
    ]
    layers = [
        {
            "name": layer.name,
            "scope": layer.scope,
            "path": layer.path_template,
            "role": layer.role,
        }
        for layer in contract.RESULT_STORAGE_LAYERS
    ]
    return {"project": project, "workspace": workspace, "machine": machine, "layers": layers}


def tree_text(rows: list[dict[str, Any]]) -> str:
    """Draw rows of :func:`storage_tree` as an indented tree."""
    return "\n".join("    " * row["depth"] + row["path"] for row in rows)


# -- environment variables -----------------------------------------------------


def _literals_outside_all(tree: ast.Module) -> list[str]:
    skipped: set[int] = set()
    for node in ast.walk(tree):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign | ast.AugAssign)
            else []
        )
        value = getattr(node, "value", None)
        if value is not None and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in targets
        ):
            skipped.update(id(sub) for sub in ast.walk(value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
        and ENV_NAME.fullmatch(node.value)
    ]


def _env_scan_files(repo: Path) -> list[tuple[Path, bool]]:
    files: list[tuple[Path, bool]] = []
    for base in (*ENV_PY_ROOTS, *ENV_PY_DIRS):
        if (repo / base).is_dir():
            files.extend((p, True) for p in _py_files(repo / base))
    files.extend((repo / f, True) for f in ENV_PY_FILES if (repo / f).is_file())
    for pattern in ENV_TEXT_GLOBS:
        files.extend((p, False) for p in sorted(repo.glob(pattern)) if p.is_file())
    excluded = {repo / f for f in ENV_SCAN_EXCLUDED}
    return [(p, is_py) for p, is_py in files if p not in excluded]


@lru_cache(maxsize=4)
def env_var_references(repo: Path = ROOT) -> dict[str, tuple[str, ...]]:
    """Every ``HMP_*`` name written in the code, with the files that write it.

    In Python files a name counts when it is a whole string literal outside
    ``__all__``. In workflow files, ``docs/Makefile`` and the ``Dockerfile`` a
    name counts wherever it appears.
    """
    found: dict[str, set[str]] = defaultdict(set)
    for path, is_py in _env_scan_files(repo):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "HMP_" not in text:
            continue
        if is_py:
            try:
                names = _literals_outside_all(ast.parse(text))
            except SyntaxError:
                continue
        else:
            names = re.findall(r"\bHMP_[A-Z][A-Z0-9_]*\b", text)
        for name in names:
            found[name].add(_rel(path, repo))
    return {name: tuple(sorted(paths)) for name, paths in sorted(found.items())}


def environment_rows(repo: Path = ROOT) -> list[dict[str, Any]]:
    """The registry of ``hydromodpy.core.env``, with the files that read each variable."""
    from hydromodpy.core.env import ENV_SCOPES, ENV_VARS

    refs = env_var_references(repo)
    rows = []
    for var in sorted(ENV_VARS, key=lambda v: (ENV_SCOPES.index(v.scope), v.name)):
        readers = refs.get(var.name, ())
        if var.prefix:
            readers = tuple(
                sorted({p for name, ps in refs.items() if name.startswith(var.name) for p in ps})
            )
        rows.append(
            {
                "name": var.display_name,
                "scope": var.scope,
                "default": var.default,
                "description": var.description,
                "read_in": list(readers),
                "code_readers": [p for p in readers if not p.startswith("tests/")],
                "test_readers": [p for p in readers if p.startswith("tests/")],
            }
        )
    return rows


# -- extras --------------------------------------------------------------------


def _requirement_name(requirement: str) -> str:
    return re.split(r"[\s\[<>=!~;]", requirement.strip(), maxsplit=1)[0]


@lru_cache(maxsize=1)
def _import_names() -> dict[str, list[str]]:
    from importlib.metadata import packages_distributions

    out: dict[str, list[str]] = defaultdict(list)
    for module, dists in packages_distributions().items():
        for dist in dists:
            out[dist.lower().replace("_", "-")].append(module)
    return out


def _imports_by_package(repo: Path) -> dict[str, set[str]]:
    """Top-level module imported -> the ``hydromodpy`` sub-packages importing it."""
    out: dict[str, set[str]] = defaultdict(set)
    base = repo / "hydromodpy"
    for path in _py_files(base):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(base).parts
        owner = rel[0] if len(rel) > 1 else "(root)"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out[alias.name.split(".")[0]].add(owner)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                out[node.module.split(".")[0]].add(owner)
    return out


def extras(repo: Path = ROOT) -> list[dict[str, Any]]:
    """One row per optional-dependency group, with the packages of the code that import it."""
    data = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data.get("project", {}).get("optional-dependencies", {})
    core = {
        _requirement_name(r).lower().replace("_", "-")
        for r in data.get("project", {}).get("dependencies", [])
    }
    imports = _imports_by_package(repo)
    names = _import_names()
    rows = []
    for extra, requirements in groups.items():
        used: set[str] = set()
        for requirement in requirements:
            dist = _requirement_name(requirement).lower().replace("_", "-")
            modules = names.get(dist) or [dist.replace("-", "_")]
            for module in modules:
                used |= imports.get(module, set())
        rows.append(
            {
                "extra": extra,
                "requirements": list(requirements),
                "used_by": sorted(used),
                "already_required": sorted(
                    _requirement_name(r)
                    for r in requirements
                    if _requirement_name(r).lower().replace("_", "-") in core
                ),
            }
        )
    return rows


__all__ = [
    "architecture_gates",
    "ci_workflows",
    "env_var_references",
    "environment_rows",
    "extras",
    "first_paragraph",
    "layer_dot",
    "layer_graph",
    "layer_label",
    "layout_contracts",
    "package_map",
    "pytest_markers",
    "registry_counts",
    "storage_tree",
    "suite_inventory",
    "tree_text",
]
