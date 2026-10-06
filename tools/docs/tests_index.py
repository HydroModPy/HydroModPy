"""Index the test suite for the documentation: validation checks and imports.

Usage: python -m tools.docs.tests_index OUT.json [--repo ROOT]

Reads only files, imports nothing from the repository. Two parts:

- validation: one entry per tests/validation/**/test_*.py, with its module
  docstring, its test functions and, when it imports a case of
  validation_cases/, the metadata, README and tolerances of that case;
- imports: for every test file of tests/, the hydromodpy modules it imports,
  so that a page can list the tests of the modules it describes.
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


def decorator_info(tree: ast.AST) -> tuple[list[str], list[str]]:
    """Markers and the solver ids of a solver parametrization."""
    markers, solvers = set(), []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) or not node.name.startswith("test_"):
            continue
        for dec in node.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            name = ast.unparse(call.func if call else dec)
            if not name.startswith("pytest.mark."):
                continue
            mark = name.split(".")[2]
            if mark != "parametrize":
                markers.add(mark)
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
            if (
                not names
                or names[0] != "solver"
                or not isinstance(call.args[1], (ast.List, ast.Tuple))
            ):
                continue
            for elt in call.args[1].elts:
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
                elif isinstance(elt, ast.Constant):
                    ident = elt.value
                elif (
                    isinstance(elt, ast.Tuple)
                    and elt.elts
                    and isinstance(elt.elts[0], ast.Constant)
                ):
                    ident = elt.elts[0].value
                else:
                    ident = None
                if ident and ident not in solvers:
                    solvers.append(str(ident))
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
            and ast.unparse(node.func).endswith("assert_metric_below")
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
        out.append({"label": label, "unit": unit, "section": section, "key": key, "expr": expr})
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


def tolerances(case_dir: Path, default_solver: str) -> dict[str, dict[str, dict[str, float]]]:
    """Map a solver variant to its tolerance tables, by file name."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for f in sorted(case_dir.glob("tolerances*.toml")):
        variant = f.stem.removeprefix("tolerances").lstrip("_") or default_solver or "default"
        data = tomllib.loads(f.read_text())
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
        out[f.name] = tomllib.loads(f.read_text())
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
        tomllib.loads((d / "metadata.toml").read_text()) if (d / "metadata.toml").exists() else {}
    )
    readme = (d / "README.md").read_text() if (d / "README.md").exists() else ""
    title = next((ln[2:].strip() for ln in readme.splitlines() if ln.startswith("# ")), d.name)
    default = meta.get("default_solver", "")
    solvers = list(meta.get("config_files", {}).keys()) or ([default] if default else [])
    rel = d.relative_to(repo)
    return {
        "path": str(rel),
        "id": meta.get("case_id", d.name),
        "title": title,
        "summary": first_paragraph(readme),
        "reference": readme_bullet(readme, "reference"),
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
            tree = ast.parse(f.read_text())
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


def build(repo: Path) -> dict:
    """Return the validation entries and the imports of every test file under ``repo``."""
    validation, imports = [], {}
    tol_md = repo / "tests" / "TOLERANCES.md"
    rows = tolerance_rows(tol_md.read_text()) if tol_md.exists() else []
    for f in sorted((repo / "tests").rglob("test_*.py")):
        rel = f.relative_to(repo)
        text = f.read_text()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        doc = ast.get_docstring(tree) or ""
        tier = rel.parts[1] if rel.parts[1] in TIERS else "other"
        mods = imported_modules(tree)
        tests = test_functions(tree)
        if mods:
            imports[str(rel)] = {
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
                    "file": str(rel),
                    "group": "/".join(rel.parts[2:-1]),
                    "doc": doc,
                    "tests": tests,
                    "markers": markers,
                    "solvers": solvers,
                    "criteria": metric_criteria(tree),
                    "tolerance_rows": [r for r in (match_row(rows, t) for t in tol_names) if r],
                    "launcher": calls_launcher(
                        [f] + [py for d in case_dirs(repo, text) for py in sorted(d.glob("*.py"))]
                    ),
                    "cases": uniq,
                }
            )
    return {"validation": validation, "imports": imports}


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
