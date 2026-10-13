"""Index the test suite for the documentation: validation checks and imports.

Usage: python -m tools.docs.tests_index OUT.json [--repo ROOT]

Reads only files, imports nothing from the repository. Two parts:

- validation: one entry per tests/validation/**/test_*.py, with its module
  docstring, its test functions and, when it imports a case of
  validation_cases/, the metadata, README and tolerances of that case;
- imports: for every test file of tests/, the hydromodpy modules it imports,
  so that a page can list the tests of the modules it describes;
- schedule: the CI jobs that run tests/validation, read from
  .github/workflows: when they run, on which branches, which paths and
  markers they select, and whether the job installs petsc4py.

A case README gives its reference solution (a "- reference:" bullet) and its
equations (a "## Equations" section). A test without a case gives its
reference in a "Compared with:" paragraph of its module docstring. A
tolerance file explains itself in a [doc] table: "reason" says why a
threshold has its value, "gap" names a known discrepancy the threshold
lets through.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path

TIERS = ("validation", "integration", "unit", "regression", "e2e", "contract")


def slugify(label: str) -> str:
    """Same rule as tests/_helpers/tolerances.py."""
    text = label.strip().lower().replace("`", "")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def split_row(line: str) -> list[str]:
    """Split a Markdown row on pipes outside code spans."""
    out, buf, in_code = [], [], False
    for ch in line:
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf).strip())
    return out


def tolerance_rows(md: str) -> list[dict]:
    """Every row of the table of tests/TOLERANCES.md, with its slug."""
    rows = []
    for line in md.splitlines():
        cells = split_row(line.strip())
        if len(cells) < 8 or not cells[1].isdigit():
            continue
        n, domain, metric, value, source, notes = cells[1:7]
        rows.append(
            {
                "n": int(n),
                "domain": domain,
                "metric": metric,
                "tolerance": value,
                "source": source,
                "notes": notes,
                "slug": f"{slugify(domain)}__{slugify(metric)}",
            }
        )
    return rows


def match_row(rows: list[dict], name: str) -> dict | None:
    """Resolve a tol() argument the way tol() does: exact slug, then unique substring."""
    needle = slugify(name)
    exact = [r for r in rows if r["slug"] in (name, needle)]
    if exact:
        return exact[0]
    hits = [r for r in rows if needle in r["slug"]]
    return hits[0] if len(hits) == 1 else None


def module_markers(tree: ast.Module) -> set[str]:
    """The marks of a module-level ``pytestmark``."""
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            for m in re.finditer(r"pytest\.mark\.(\w+)", ast.unparse(node.value)):
                out.add(m.group(1))
    out.discard("parametrize")
    return out


def _param_id(elt: ast.expr) -> tuple[str | None, set[str]]:
    """The id of one ``solver`` parameter and the marks it carries."""
    marks: set[str] = set()
    if isinstance(elt, ast.Call) and ast.unparse(elt.func).endswith("param"):
        ident = next(
            (
                k.value.value
                for k in elt.keywords
                if k.arg == "id" and isinstance(k.value, ast.Constant)
            ),
            None,
        )
        if ident is None and elt.args and isinstance(elt.args[0], ast.Constant):
            ident = elt.args[0].value
        for k in elt.keywords:
            if k.arg == "marks":
                marks |= set(re.findall(r"pytest\.mark\.(\w+)", ast.unparse(k.value)))
        return (str(ident) if ident else None), marks
    if isinstance(elt, ast.Constant):
        return str(elt.value), marks
    if isinstance(elt, ast.Tuple) and elt.elts and isinstance(elt.elts[0], ast.Constant):
        return str(elt.elts[0].value), marks
    return None, marks


def function_info(tree: ast.Module) -> list[dict]:
    """Per test function: its marks and the ``solver`` parameters it runs, with their marks."""
    module = module_markers(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) or not node.name.startswith("test_"):
            continue
        marks, solvers = set(module), []
        for dec in node.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            name = ast.unparse(call.func if call else dec)
            if not name.startswith("pytest.mark."):
                continue
            mark = name.split(".")[2]
            if mark != "parametrize":
                marks.add(mark)
                continue
            if not call or len(call.args) < 2:
                continue
            try:
                argnames = ast.literal_eval(call.args[0])
            except ValueError:
                continue
            names = (
                [a.strip() for a in argnames.split(",")]
                if isinstance(argnames, str)
                else list(argnames)
            )
            if names and names[0] == "solver" and isinstance(call.args[1], (ast.List, ast.Tuple)):
                for elt in call.args[1].elts:
                    ident, param_marks = _param_id(elt)
                    if ident:
                        solvers.append({"id": ident, "marks": sorted(param_marks)})
        out.append({"name": node.name, "markers": sorted(marks), "solvers": solvers})
    return out


def decorator_info(tree: ast.Module) -> tuple[list[str], list[str]]:
    """Markers of all test functions and the solver ids of their solver parametrization."""
    markers: set[str] = set(module_markers(tree))
    solvers: list[str] = []
    for fn in function_info(tree):
        markers |= set(fn["markers"])
        for s in fn["solvers"]:
            if s["id"] not in solvers:
                solvers.append(s["id"])
    return sorted(markers), solvers


def metric_criteria(tree: ast.AST) -> list[dict]:
    """The assert_metric_below calls: label, unit and the tolerance key they read."""
    section_of: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            m = re.search(r"tolerances(?:\.get\(|\[)\s*['\"]([\w-]+)['\"]", ast.unparse(node.value))
            if m:
                section_of[node.targets[0].id] = m.group(1)
    out = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith(("assert_metric_below", "assert_metric_above"))
            and len(node.args) >= 3
        ):
            continue
        label = (
            node.args[0].value
            if isinstance(node.args[0], ast.Constant)
            else ast.unparse(node.args[0])
        )
        unit = next(
            (
                k.value.value
                for k in node.keywords
                if k.arg == "unit" and isinstance(k.value, ast.Constant)
            ),
            "",
        )
        expr = ast.unparse(node.args[2])
        section = key = None
        m = re.search(
            r"tolerances(?:\.get\(|\[)\s*['\"]([\w-]+)['\"].*?\[\s*['\"]([\w-]+)['\"]\s*\]", expr
        )
        if m:
            section, key = m.group(1), m.group(2)
        else:
            m = re.search(r"(\w+)\[\s*['\"]([\w-]+)['\"]\s*\]", expr)
            if m and m.group(1) in section_of:
                section, key = section_of[m.group(1)], m.group(2)
        op = ">" if ast.unparse(node.func).endswith("above") else "<"
        out.append(
            {"label": label, "unit": unit, "section": section, "key": key, "expr": expr, "op": op}
        )
    return out


def first_paragraph(text: str) -> str:
    """Return the first paragraph of a README, after its title."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    para: list[str] = []
    for ln in lines:
        if ln.strip():
            para.append(ln.strip())
        elif para:
            break
    return " ".join(para)


def readme_bullet(text: str, key: str) -> str:
    """Return the value of a '- key: value' bullet, joined over its indented lines."""
    m = re.search(rf"^- {re.escape(key)}:\s*(.+(?:\n  \S.*)*)", text, flags=re.M)
    return " ".join(m.group(1).split()) if m else ""


BOILERPLATE = ("The equations of the reference solution the comparison uses.",)


def readme_section(text: str, heading: str) -> str:
    """Body of a level-2 section of a README, without its heading."""
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    if not m:
        return ""
    body = m.group(1)
    for line in BOILERPLATE:
        body = body.replace(line, "")
    return body.strip()


def docstring_paragraph(doc: str, key: str) -> str:
    """The paragraph of a docstring that starts with ``key:``, without the key."""
    for block in re.split(r"\n\s*\n", doc):
        text = " ".join(block.split())
        if text.lower().startswith(key.lower() + ":"):
            return text[len(key) + 1 :].strip()
    return ""


def tolerance_notes(case_dir: Path) -> dict[str, dict[str, str]]:
    """The [doc] table of each tolerance file: reason and gap, by file name."""
    out = {}
    for f in sorted(case_dir.glob("tolerances*.toml")):
        doc = tomllib.loads(f.read_text(encoding="utf-8")).get("doc", {})
        if isinstance(doc, dict):
            notes = {k: " ".join(str(v).split()) for k, v in doc.items() if k in ("reason", "gap")}
            if notes:
                out[f.name] = notes
    return out


def tolerances(case_dir: Path, default_solver: str) -> dict[str, dict[str, dict[str, float]]]:
    """Map a solver variant to its tolerance tables, by file name."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for f in sorted(case_dir.glob("tolerances*.toml")):
        variant = f.stem.removeprefix("tolerances").lstrip("_") or default_solver or "default"
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        table: dict[str, dict[str, float]] = {}
        for section, metrics in data.items():
            if isinstance(metrics, dict):
                table[section] = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
            elif isinstance(metrics, (int, float)):
                table.setdefault("all", {})[section] = metrics
        out[variant] = table
    return out


def tolerance_file(case_dir: Path, solver: str) -> str | None:
    """Same choice as load_case_tolerances: tolerances_<solver>.toml, then tolerances.toml."""
    name = solver.strip().lower()
    for cand in dict.fromkeys([name, name.replace("_", "")]):
        if (case_dir / f"tolerances_{cand}.toml").exists():
            return f"tolerances_{cand}.toml"
    return "tolerances.toml" if (case_dir / "tolerances.toml").exists() else None


def tolerance_tables(case_dir: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(case_dir.glob("tolerances*.toml")):
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        data.pop("doc", None)
        out[f.name] = data
    return out


def case_info(repo: Path, dotted: str) -> dict | None:
    """Find the case directory of a validation_cases import and read it."""
    parts = dotted.split(".")
    for n in range(len(parts), 0, -1):
        d = repo / "validation_cases" / Path(*parts[:n])
        if (d / "README.md").exists() or (d / "metadata.toml").exists():
            break
    else:
        return None
    meta = (
        tomllib.loads((d / "metadata.toml").read_text(encoding="utf-8"))
        if (d / "metadata.toml").exists()
        else {}
    )
    readme = (d / "README.md").read_text(encoding="utf-8") if (d / "README.md").exists() else ""
    title = next((ln[2:].strip() for ln in readme.splitlines() if ln.startswith("# ")), d.name)
    default = meta.get("default_solver", "")
    solvers = list(meta.get("config_files", {}).keys()) or ([default] if default else [])
    rel = d.relative_to(repo)
    return {
        "path": rel.as_posix(),
        "id": meta.get("case_id", d.name),
        "title": title,
        "summary": first_paragraph(readme),
        "reference": readme_bullet(readme, "reference"),
        "equations": readme_section(readme, "Equations"),
        "tolerance_notes": tolerance_notes(d),
        "observable": readme_bullet(readme, "simulated observable"),
        "regime": meta.get("regime", ""),
        "dimension": meta.get("dimension", ""),
        "default_solver": default,
        "solvers": solvers,
        "tolerance_files": tolerance_tables(d),
        "dir": str(d),
        "run": f"python -m {'.'.join(rel.parts)}.run_case" if (d / "run_case.py").exists() else "",
    }


def imported_modules(tree: ast.AST) -> list[str]:
    """Return the hydromodpy modules and names a test file imports."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names if a.name.startswith("hydromodpy"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("hydromodpy")
            and not node.level
        ):
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return sorted(mods)


def case_dirs(repo: Path, text: str) -> list[Path]:
    """Deepest existing folder of each validation_cases import of a test file."""
    out = []
    for m in re.finditer(r"validation_cases\.([\w.]+)", text):
        parts = m.group(1).split(".")
        for n in range(len(parts), 0, -1):
            d = repo / "validation_cases" / Path(*parts[:n])
            if d.is_dir():
                if d not in out:
                    out.append(d)
                break
    return out


def calls_launcher(files: list[Path]) -> bool:
    """True when one of the files calls run_launcher_validation_case."""
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).split(".")[-1] == "run_launcher_validation_case"
            ):
                return True
    return False


def test_functions(tree: ast.AST) -> list[str]:
    return [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    ]


DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def cron_words(cron: str) -> str:
    """Say a simple cron line in words: daily or weekly at a UTC time."""
    parts = cron.split()
    if len(parts) != 5 or not (parts[0].isdigit() and parts[1].isdigit()):
        return f"cron {cron}"
    at = f"{int(parts[1]):02d}:{int(parts[0]):02d} UTC"
    if parts[2:] == ["*", "*", "*"]:
        return f"every day at {at}"
    if parts[2:4] == ["*", "*"] and parts[4].isdigit():
        return f"every {DAYS[int(parts[4]) % 7]} at {at}"
    return f"cron {cron}"


def _pytest_commands(text: str) -> list[str]:
    """Each ``python -m pytest`` command of a shell text, joined over its line breaks."""
    joined = re.sub(r"\\\s*\n\s*", " ", text)
    return [m.group(0) for m in re.finditer(r"python -m pytest[^\n]*", joined)]


def _selection(command: str) -> tuple[list[str], str] | None:
    """The paths and the -m expression of one pytest command, None when it runs no test."""
    args = command.split("pytest", 1)[1]
    if "--collect-only" in args or "--doctest-modules" in args:
        return None
    marks = re.search(r"(?:^|\s)-m\s+(\"[^\"]*\"|'[^']*'|\S+)", args)
    paths = [t for t in args.split() if not t.startswith("-") and ("/" in t or t == "tests")]
    return paths or ["tests"], (marks.group(1).strip("\"'") if marks else "")


def job_name(name: str, workflow_name: str) -> str:
    """A job name without its GitHub expressions."""
    clean = re.sub(r"\s*(?:on|py)?\s*\$\{\{[^}]*\}\}", "", name).strip(" /")
    return clean if len(clean) > 12 else workflow_name or clean


def marks_match(expr: str, marks: set[str]) -> bool:
    """Evaluate a pytest ``-m`` expression (and, or, not, parentheses) on a marker set."""
    if not expr.strip():
        return True
    words = []
    for tok in re.findall(r"\(|\)|[\w.]+", expr):
        words.append(tok if tok in ("(", ")", "and", "or", "not") else str(tok in marks))
    try:
        return bool(eval(" ".join(words), {"__builtins__": {}}))  # noqa: S307
    except SyntaxError:
        return True


def runs_in(file: str, functions: list[dict], jobs: list[dict]) -> dict:
    """For each solver of a test file, the jobs that select one of its tests.

    A job selects a test when one of its paths contains the file and its
    marker expression accepts the marks of the test. The test suite marks the
    Boussinesq variant of an analytical case ``petsc``; a job without petsc4py
    skips a ``petsc`` test.
    """
    variants: dict[str, list[set[str]]] = {}
    for fn in functions:
        base = set(fn["markers"]) | {"validation"}
        for s in fn["solvers"] or [{"id": "", "marks": []}]:
            marks = base | set(s["marks"])
            if s["id"] == "boussinesq" and "/analytical/" in file:
                marks.add("petsc")
            variants.setdefault(s["id"], []).append(marks)
    out: dict[str, list[dict]] = {}
    for solver, mark_sets in variants.items():
        hits = []
        for i, job in enumerate(jobs):
            if not any(file == p or file.startswith(p.rstrip("/") + "/") for p in job["paths"]):
                continue
            chosen = [m for m in mark_sets if marks_match(job["markers"], m)]
            if chosen:
                skipped = all("petsc" in m for m in chosen) and not job["petsc4py"]
                hits.append({"job": i, "skipped": skipped})
        out[solver] = hits
    return out


def installs_petsc4py(job: dict) -> bool:
    """Whether a job installs or imports petsc4py in its own steps.

    The job is read from the parsed YAML, so a comment never counts, and another
    job of the same workflow file does not either.
    """
    return "petsc4py" in json.dumps(job.get("steps") or [], default=str)


def schedule(repo: Path) -> list[dict]:
    """The CI jobs that run validation tests, read from the workflow files."""
    import yaml

    out = []
    for wf in sorted((repo / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        on = data.get("on", data.get(True, {})) or {}
        if isinstance(on, (str, list)):
            on = {k: {} for k in ([on] if isinstance(on, str) else on)}
        when = [cron_words(c["cron"]) for c in on.get("schedule") or [] if "cron" in c]
        push = on.get("push") or {}
        if "push" in on:
            target = ", ".join(push.get("branches", [])) or "any branch"
            limited = " that touches listed paths" if push.get("paths") else ""
            when.append(f"on every push to {target}{limited}")
        if "pull_request" in on:
            limited = (
                " that touches listed paths" if (on["pull_request"] or {}).get("paths") else ""
            )
            when.append(f"on every pull request{limited}")
        for job_id, job in (data.get("jobs") or {}).items():
            branches = ((job.get("strategy") or {}).get("matrix") or {}).get("target_branch")
            for step in job.get("steps") or []:
                run = step.get("run") or ""
                script = re.search(r"bash\s+(tools/\S+\.sh)", run)
                if script and (repo / script.group(1)).exists():
                    run = (repo / script.group(1)).read_text(encoding="utf-8")
                for command in _pytest_commands(run):
                    selection = _selection(command)
                    if selection is None:
                        continue
                    paths, marks = selection
                    if not any(
                        p.startswith("tests/validation")
                        or "tests/validation".startswith(p.rstrip("/"))
                        for p in paths
                    ):
                        continue
                    out.append(
                        {
                            "workflow": wf.name,
                            "job": job_name(str(job.get("name") or job_id), data.get("name", "")),
                            "when": when,
                            "branches": list(branches) if isinstance(branches, list) else [],
                            "paths": paths,
                            "markers": marks,
                            "petsc4py": installs_petsc4py(job),
                        }
                    )
    return out


def build(repo: Path) -> dict:
    """Return the validation entries and the imports of every test file under ``repo``."""
    validation, imports = [], {}
    tol_md = repo / "tests" / "TOLERANCES.md"
    rows = tolerance_rows(tol_md.read_text(encoding="utf-8")) if tol_md.exists() else []
    for f in sorted((repo / "tests").rglob("test_*.py")):
        rel = f.relative_to(repo)
        text = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        doc = ast.get_docstring(tree) or ""
        tier = rel.parts[1] if rel.parts[1] in TIERS else "other"
        mods = imported_modules(tree)
        tests = test_functions(tree)
        if mods:
            imports[rel.as_posix()] = {
                "tier": tier,
                "modules": mods,
                "tests": tests,
                "doc": doc.strip().splitlines()[0] if doc.strip() else "",
            }
        if tier == "validation":
            cases = sorted({m.group(1) for m in re.finditer(r"validation_cases\.([\w.]+)", text)})
            infos = [c for c in (case_info(repo, d) for d in cases) if c]
            seen, uniq = set(), []
            for c in infos:
                if c["path"] not in seen:
                    seen.add(c["path"])
                    uniq.append(c)
            functions = function_info(tree)
            markers, solvers = decorator_info(tree)
            for c in uniq:
                case_dir = Path(c.pop("dir"))
                c["solver_files"] = {
                    sv: tolerance_file(case_dir, sv)
                    for sv in (solvers or [c["default_solver"]])
                    if sv
                }
            tol_names = [m.group(1) for m in re.finditer(r"\btol\(\s*[\"']([^\"']+)[\"']", text)]
            validation.append(
                {
                    "file": rel.as_posix(),
                    "group": "/".join(rel.parts[2:-1]),
                    "doc": doc,
                    "tests": tests,
                    "markers": markers,
                    "solvers": solvers,
                    "functions": functions,
                    "criteria": metric_criteria(tree),
                    "tolerance_rows": [r for r in (match_row(rows, t) for t in tol_names) if r],
                    "reference": docstring_paragraph(doc, "Compared with"),
                    "launcher": calls_launcher(
                        [f] + [py for d in case_dirs(repo, text) for py in sorted(d.glob("*.py"))]
                    ),
                    "cases": uniq,
                }
            )
    jobs = schedule(repo)
    for entry in validation:
        entry["runs_in"] = runs_in(entry["file"], entry["functions"], jobs)
    return {"validation": validation, "imports": imports, "schedule": jobs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    payload = build(Path(args.repo))
    Path(args.out).write_text(json.dumps(payload, indent=1))
    print(
        f"validation files: {len(payload['validation'])}, test files with imports: {len(payload['imports'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
