"""Notation tables of the theory pages, from one registry of symbols.

``docs/source/theory/symbols.yaml`` holds one entry per meaning: the symbol in
LaTeX, the meaning, the unit, what sets it and the pages that use it. The
``hmp-notation`` directive renders the table of a page from it, and
``theory/notation`` renders every group.

The build fails when one symbol has two meanings, unless the pair is declared
under ``collisions`` and the two meanings never share a page. A page listed by
an entry must exist.

Text fields are reStructuredText inline markup (``:math:``, ``:toml:``,
``:doc:``, double backquotes), so one table parses the same way on a Markdown
page and on a reStructuredText page.

The same module renders ``hmp-solver-matrix``, the table of the validation
cases that run on each solver, from ``_data/tests.json`` and the threshold
files of each case folder. The solver pages compare solvers with it, so their
comparison cannot announce a case that does not run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("theory") / "symbols.yaml"
PAGE_PREFIX = "theory/"
_REQUIRED = ("id", "symbol", "meaning", "unit", "group", "pages")
_HEADER = ("Symbol", "Meaning", "Unit", "Set by")


@dataclass(frozen=True)
class Symbol:
    id: str
    symbol: str
    meaning: str
    unit: str
    set_by: str
    group: str
    pages: tuple[str, ...]


@dataclass(frozen=True)
class Registry:
    groups: dict[str, str]
    symbols: tuple[Symbol, ...]
    collisions: tuple[frozenset[str], ...]


def _page(name: str) -> str:
    name = str(name).strip()
    return name[1:] if name.startswith("/") else PAGE_PREFIX + name


def normalize(symbol: str) -> str:
    """Return the symbol with the spaces removed, the key of the collision rule."""
    return "".join(str(symbol).split())


def parse_registry(data: dict[str, Any]) -> Registry:
    """Build a registry from the loaded YAML. Raise ``ValueError`` on a bad entry."""
    groups = {str(k): str(v) for k, v in (data.get("groups") or {}).items()}
    symbols: list[Symbol] = []
    seen: set[str] = set()
    for raw in data.get("symbols") or []:
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise ValueError(f"symbol entry {raw.get('id', raw)!r} lacks {missing}")
        sid = str(raw["id"])
        if sid in seen:
            raise ValueError(f"symbol id {sid!r} is declared twice")
        seen.add(sid)
        group = str(raw["group"])
        if group not in groups:
            raise ValueError(f"symbol {sid!r} names an unknown group {group!r}")
        symbols.append(
            Symbol(
                id=sid,
                symbol=str(raw["symbol"]),
                meaning=str(raw["meaning"]).strip(),
                unit=str(raw["unit"]),
                set_by=str(raw.get("set_by") or "").strip(),
                group=group,
                pages=tuple(_page(p) for p in raw["pages"]),
            )
        )
    collisions = tuple(frozenset(str(i) for i in pair) for pair in data.get("collisions") or [])
    return Registry(groups=groups, symbols=tuple(symbols), collisions=collisions)


def load_registry(path: Path) -> Registry:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return parse_registry(yaml.safe_load(fh) or {})


def find_collisions(registry: Registry) -> list[str]:
    """Return one message per symbol that carries two meanings without leave.

    A pair of meanings is allowed when ``collisions`` declares it and the two
    entries share no page. A declared pair that names an unknown id is an error
    too, so a renamed symbol does not leave a stale exemption behind.
    """
    by_id = {s.id: s for s in registry.symbols}
    problems: list[str] = []
    for pair in registry.collisions:
        unknown = sorted(i for i in pair if i not in by_id)
        if unknown or len(pair) != 2:
            problems.append(f"declared collision {sorted(pair)} names unknown ids {unknown}")
    declared = set(registry.collisions)
    by_symbol: dict[str, list[Symbol]] = {}
    for s in registry.symbols:
        by_symbol.setdefault(normalize(s.symbol), []).append(s)
    for key, entries in by_symbol.items():
        for i, a in enumerate(entries):
            for b in entries[i + 1 :]:
                shared = sorted(set(a.pages) & set(b.pages))
                if frozenset((a.id, b.id)) not in declared:
                    problems.append(
                        f"symbol ${key}$ means both {a.id!r} ({a.meaning}) and "
                        f"{b.id!r} ({b.meaning}); rename one or declare the pair"
                    )
                elif shared:
                    problems.append(
                        f"symbol ${key}$ has two meanings, {a.id!r} and {b.id!r}, "
                        f"on the same page: {', '.join(shared)}"
                    )
    return problems


def select(
    registry: Registry, *, page: str | None = None, groups: tuple[str, ...] = ()
) -> list[Symbol]:
    """Return the entries of a page, or of groups, in registry order."""
    out = list(registry.symbols)
    if groups:
        out = [s for s in out if s.group in groups]
    if page is not None:
        out = [s for s in out if page in s.pages]
    return out


def table_rst(entries: list[Symbol], *, title: str | None = None) -> str:
    """Return the entries as an RST list-table."""
    lines = [
        f".. list-table:: {title or ''}".rstrip(),
        "   :header-rows: 1",
        "   :widths: 16 50 10 24",
        "",
    ]
    lines.append("   * - " + "\n     - ".join(_HEADER))
    for s in entries:
        cells = (f":math:`{s.symbol}`", s.meaning, s.unit, s.set_by or "\\-")
        lines.append("   * - " + "\n     - ".join(c.replace("\n", " ") for c in cells))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- Sphinx


def _registry(app) -> Registry:
    reg = getattr(app.env, "hmp_notation_registry", None)
    if reg is None:
        reg = load_registry(Path(app.srcdir) / REGISTRY_PATH)
        app.env.hmp_notation_registry = reg
    return reg


def on_builder_inited(app) -> None:
    from sphinx.errors import ExtensionError

    reg = load_registry(Path(app.srcdir) / REGISTRY_PATH)
    app.env.hmp_notation_registry = reg
    problems = find_collisions(reg)
    if problems:
        raise ExtensionError("notation registry: " + "; ".join(problems))


def on_check_consistency(app, env) -> None:
    from sphinx.util import logging

    logger = logging.getLogger(__name__)
    reg = _registry(app)
    for s in reg.symbols:
        for page in s.pages:
            if page not in env.found_docs:
                logger.warning(
                    f"[hmp] symbol {s.id!r} lists page {page!r}, which does not exist",
                    location=str(REGISTRY_PATH),
                )


def _make_directive():
    from docutils import nodes
    from docutils.parsers.rst import Parser, directives
    from docutils.utils import new_document
    from sphinx.util import logging
    from sphinx.util.docutils import SphinxDirective

    logger = logging.getLogger(__name__)

    class NotationDirective(SphinxDirective):
        """Render the notation table of the page, or of the named groups.

        Options: ``:groups:`` a comma list of group names; ``:page:`` another
        page's table; ``:all:`` every group, one table each, with its title.
        """

        has_content = False
        option_spec = {
            "groups": directives.unchanged,
            "page": directives.unchanged,
            "all": directives.flag,
        }

        def _parse(self, text: str) -> list[nodes.Node]:
            settings = self.state.document.settings
            doc = new_document(self.env.docname, settings)
            Parser().parse(text, doc)
            return list(doc.children)

        def run(self) -> list[nodes.Node]:
            reg = _registry(self.env.app)
            self.env.note_dependency(str(Path(self.env.srcdir) / REGISTRY_PATH))
            groups = tuple(
                g.strip() for g in (self.options.get("groups") or "").split(",") if g.strip()
            )
            unknown = [g for g in groups if g not in reg.groups]
            if unknown:
                logger.warning(
                    f"[hmp] unknown notation group(s) {unknown}", location=self.get_location()
                )
            if "all" in self.options:
                out: list[nodes.Node] = []
                for key, title in reg.groups.items():
                    entries = select(reg, groups=(key,))
                    if entries:
                        out += self._parse(table_rst(entries, title=title))
                return out
            page = None
            if not groups:
                given = self.options.get("page")
                page = _page(given) if given else self.env.docname
            entries = select(reg, page=page, groups=groups)
            if not entries:
                logger.warning("[hmp] the notation table is empty", location=self.get_location())
                return []
            return self._parse(table_rst(entries))

    return NotationDirective


# ---------------------------------------------------------------- solver matrix

TESTS_JSON = Path("_data") / "tests.json"
MATRIX_SOLVERS = {
    "modflow_nwt": ("MODFLOW-NWT", "tolerances_modflownwt.toml"),
    "modflow6": ("MODFLOW 6", "tolerances_modflow6.toml"),
    "modflow6_irregular_tri": ("MODFLOW 6, triangles", "tolerances_modflow6_irregular_tri.toml"),
    "boussinesq": ("Boussinesq", "tolerances_boussinesq.toml"),
    "boussinesq_local": ("Boussinesq, default engine", "tolerances_boussinesq_local.toml"),
}


def solver_matrix_rows(
    tests: list[dict], repo_root: Path, *, solvers: tuple[str, ...], require: tuple[str, ...]
) -> list[tuple[str, list[str]]]:
    """Return one row per validation case that runs every solver of ``require``.

    A cell is ``yes`` when the test runs the solver, ``yes, own threshold`` when
    the case folder also holds a threshold file for that solver, and empty
    otherwise.
    """
    rows: list[tuple[str, list[str]]] = []
    for entry in tests:
        ran = set(entry.get("solvers") or [])
        if not set(require) <= ran:
            continue
        for case in entry.get("cases") or [{"id": Path(entry["file"]).stem, "path": ""}]:
            folder = repo_root / case.get("path", "") if case.get("path") else None
            cells = []
            for solver in solvers:
                if solver not in ran:
                    cells.append("")
                    continue
                own = folder is not None and (folder / MATRIX_SOLVERS[solver][1]).exists()
                cells.append("yes, own threshold" if own else "yes")
            rows.append((str(case["id"]), cells))
    return rows


def matrix_rst(rows: list[tuple[str, list[str]]], solvers: tuple[str, ...]) -> str:
    head = ["Case"] + [MATRIX_SOLVERS[s][0] for s in solvers]
    lines = [".. list-table::", "   :header-rows: 1", ""]
    lines.append("   * - " + "\n     - ".join(head))
    for case, cells in rows:
        lines.append("   * - " + "\n     - ".join([f"``{case}``"] + [c or "\\-" for c in cells]))
    lines.append("")
    return "\n".join(lines)


def _make_matrix_directive():
    import json

    from docutils.parsers.rst import Parser, directives
    from docutils.utils import new_document
    from sphinx.util import logging
    from sphinx.util.docutils import SphinxDirective

    logger = logging.getLogger(__name__)

    class SolverMatrixDirective(SphinxDirective):
        """Table of the validation cases by solver.

        ``:require:`` keeps the cases that run every solver of a comma list.
        """

        option_spec = {"require": directives.unchanged}

        def run(self):
            path = Path(self.env.srcdir) / TESTS_JSON
            if not path.exists():
                logger.warning(f"[hmp] {TESTS_JSON} is missing", location=self.get_location())
                return []
            self.env.note_dependency(str(path))
            tests = json.loads(path.read_text()).get("validation") or []
            require = tuple(
                s.strip() for s in (self.options.get("require") or "").split(",") if s.strip()
            )
            solvers = tuple(MATRIX_SOLVERS)
            repo_root = Path(self.env.srcdir).parents[1]
            rows = solver_matrix_rows(tests, repo_root, solvers=solvers, require=require)
            if not rows:
                logger.warning("[hmp] no validation case matches", location=self.get_location())
                return []
            doc = new_document(self.env.docname, self.state.document.settings)
            Parser().parse(matrix_rst(rows, solvers), doc)
            return list(doc.children)

    return SolverMatrixDirective


def setup(app) -> dict[str, Any]:
    app.add_directive("hmp-notation", _make_directive())
    app.add_directive("hmp-solver-matrix", _make_matrix_directive())
    app.connect("builder-inited", on_builder_inited)
    app.connect("env-check-consistency", on_check_consistency)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
