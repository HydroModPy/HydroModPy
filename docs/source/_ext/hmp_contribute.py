"""Contributor pages generated at build time from the files that own their facts.

Each directive renders what ``tools/docs/contribute_data.py`` reads from one
source of truth: the layer matrix, the architecture gates, the CI workflows,
the test files, the package registries, the storage contract, the registry of
environment variables and the extras of ``pyproject.toml``. A wrong row is
fixed in that source, never in a page.

The pages under ``contribute/architecture/generated/`` hold one directive each
and are read again at every build, because their sources are not pages.

The layer graph needs Graphviz. When ``dot`` cannot be found the figure is
left out with an info message and the tables still render, so a strict build
does not fail on a machine without Graphviz.
"""

from __future__ import annotations

import re
import shutil
from typing import Any

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)

GENERATED_PREFIX = "contribute/architecture/generated/"
INLINE = re.compile(r"(``.+?``|:[a-z]+(?::[a-z]+)?:`[^`]+`|`[^`]+`|\*\*[^*]+\*\*)")


def _data():
    from tools.docs import contribute_data

    return contribute_data


# -- node helpers --------------------------------------------------------------


def inline(text: str) -> list[nodes.Node]:
    """Text with ``code``, `code`, :role:`x` and **bold** turned into nodes."""
    out: list[nodes.Node] = []
    for part in INLINE.split(text or ""):
        if not part:
            continue
        if part.startswith("``") and part.endswith("``") and len(part) > 4:
            out.append(nodes.literal(part[2:-2], part[2:-2]))
        elif part.startswith(":") and part.endswith("`") and ":`" in part:
            target = part.split(":`", 1)[1][:-1].lstrip("~")
            out.append(nodes.literal(target, target))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(nodes.literal(part[1:-1], part[1:-1]))
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(nodes.strong(part[2:-2], part[2:-2]))
        else:
            out.append(nodes.Text(part))
    return out


def para(text: str) -> nodes.paragraph:
    node = nodes.paragraph()
    node.extend(inline(text))
    return node


def literal(text: str) -> nodes.literal:
    return nodes.literal(text, text)


def literal_list(items: list[str], limit: int | None = None) -> nodes.paragraph:
    """Comma-separated literals, cut after *limit* with a count of the rest."""
    node = nodes.paragraph()
    shown = items if limit is None else items[:limit]
    for i, item in enumerate(shown):
        if i:
            node += nodes.Text(", ")
        node += literal(item)
    if limit is not None and len(items) > limit:
        node += nodes.Text(f" and {len(items) - limit} more")
    if not items:
        node += nodes.Text("none")
    return node


def bullets(items: list[nodes.Node | str]) -> nodes.bullet_list:
    out = nodes.bullet_list()
    for item in items:
        li = nodes.list_item()
        li += para(item) if isinstance(item, str) else item
        out += li
    return out


Cell = str | int | nodes.Node | list[nodes.Node]


def _cell(value: Cell) -> nodes.entry:
    entry = nodes.entry()
    if isinstance(value, int):
        entry += nodes.paragraph(text=f"{value:,}".replace(",", " "))
    elif isinstance(value, str):
        entry += para(value)
    elif isinstance(value, list):
        entry.extend(value)
    else:
        entry += value
    return entry


def table(headers: list[str], rows: list[list[Cell]], widths: list[int]) -> nodes.table:
    tbl = nodes.table(classes=["hmp-contribute-table"])
    group = nodes.tgroup(cols=len(headers))
    tbl += group
    for width in widths:
        group += nodes.colspec(colwidth=width)
    head = nodes.thead()
    row = nodes.row()
    for title in headers:
        row += _cell(title)
    head += row
    group += head
    body = nodes.tbody()
    for values in rows:
        row = nodes.row()
        for value in values:
            row += _cell(value)
        body += row
    group += body
    return tbl


class _Generated(SphinxDirective):
    """Base of the directives: sections with unique ids and links to pages."""

    has_content = False
    required_arguments = 0
    optional_arguments = 0

    def section(self, title: str, children: list[nodes.Node]) -> nodes.section:
        ident = nodes.make_id(f"{self.name}-{title}")
        node = nodes.section(ids=[ident], names=[nodes.fully_normalize_name(title)])
        node += nodes.title(title, title)
        node.extend(children)
        self.state.document.note_implicit_target(node, node)
        return node

    def doc_link(self, docname: str, text: str) -> nodes.Node:
        """A link to *docname* when it exists, else the text alone."""
        if docname not in self.env.found_docs:
            return nodes.Text(text)
        ref = addnodes.pending_xref(
            "",
            refdomain="std",
            reftype="doc",
            reftarget="/" + docname,
            refexplicit=True,
            refdoc=self.env.docname,
        )
        ref += nodes.inline(text, text)
        return ref

    def source_note(self, sources: str) -> nodes.paragraph:
        return para(f"Built from {sources} each time the site is built. Fix a wrong row there.")


# -- layer graph ---------------------------------------------------------------


def _dot_available(app: Sphinx) -> bool:
    command = getattr(app.config, "graphviz_dot", "dot") or "dot"
    return shutil.which(command) is not None


class LayersDirective(_Generated):
    """The layer matrix drawn as a reduced graph, with the edges the drawing drops."""

    def run(self) -> list[nodes.Node]:
        data = _data()
        graph = data.layer_graph()
        label = data.layer_label
        out: list[nodes.Node] = [
            self.source_note("``tests/unit/architecture/layer_matrix.yaml``"),
            para(
                f"{len(graph['layers'])} layers, {graph['granted']} granted imports between two "
                f"different layers. The figure keeps {len(graph['reduced'])} arrows: an arrow is "
                "left out when a longer path of arrows joins the same two layers. A path in the "
                "figure is not a grant, and a missing arrow is not a ban. The contract is the "
                "matrix."
            ),
        ]
        if _dot_available(self.env.app):
            from sphinx.ext.graphviz import graphviz

            node = graphviz()
            node["code"] = data.layer_dot(graph)
            node["options"] = {"docname": self.env.docname}
            node["alt"] = "Layers of HydroModPy and the imports they are granted"
            node["align"] = "center"
            node["classes"] = ["hmp-layer-graph"]
            out.append(node)
            out.append(
                para(
                    "A plain arrow points from a layer to a layer it may import. A dashed "
                    "arrow is a granted import that points up, against the order of the "
                    "figure. A dotted arrow is a tolerated edge."
                )
            )
        else:
            logger.info("[hmp_contribute] Graphviz dot not found: layer figure left out")

        targets: dict[str, list[str]] = {name: [] for name in graph["layers"]}
        for u, v in graph["reduced"]:
            targets[u].append(label(v))
        rows = [
            [literal(label(name)), literal_list(targets[name]) if targets[name] else "-"]
            for name in graph["layers"]
        ]
        out.append(
            self.section(
                "Arrows of the figure",
                [
                    para("Layers from the top of the figure to the bottom."),
                    table(["Layer", "Arrow to"], rows, [25, 75]),
                ],
            )
        )
        up_rows = [[literal(label(u)), literal(label(v))] for u, v in graph["upward"]]
        children: list[nodes.Node] = [
            para(
                "The matrix is a set of grants, not a strict order: these pairs close a "
                "cycle. They are drawn dashed."
            ),
            table(["Layer", "May import"], up_rows, [50, 50]),
        ]
        out.append(self.section("Grants that point up", children))
        if graph["tolerated"]:
            tol_rows = [
                [literal(label(u)), literal(label(v)), reason]
                for u, v, reason in graph["tolerated"]
            ]
            out.append(
                self.section(
                    "Tolerated edges",
                    [
                        para(
                            "Edges the matrix does not grant but tolerates, each with its reason."
                        ),
                        table(["From", "To", "Why"], tol_rows, [15, 15, 70]),
                    ],
                )
            )
        link = para("The full matrix, row by row: ")
        link += self.doc_link(
            "contribute/architecture/layered-architecture", "Layered architecture"
        )
        link += nodes.Text(".")
        out.append(link)
        return out


# -- architecture gates --------------------------------------------------------


def _humanize(test_name: str) -> str:
    name = test_name.split(".")[-1].removeprefix("test_").replace("_", " ")
    return name[:1].upper() + name[1:]


class GuardsDirective(_Generated):
    """One row per module of tests/unit/architecture, and the layout contracts."""

    def run(self) -> list[nodes.Node]:
        data = _data()
        gates = data.architecture_gates()
        layouts = data.layout_contracts()
        rows = []
        for gate in gates:
            name = gate["file"].rsplit("/", 1)[-1]
            rows.append(
                [
                    literal(name),
                    gate["rule"] or "-",
                    literal_list(gate["contracts"]) if gate["contracts"] else "-",
                    bullets([_humanize(t) for t in gate["tests"]]),
                ]
            )
        out: list[nodes.Node] = [
            self.source_note(
                "the module docstrings of ``tests/unit/architecture/test_*.py`` and the YAML "
                "contracts beside them"
            ),
            para(
                f"{len(gates)} gate modules and {len(layouts) + 1} YAML contracts. Run them all "
                "with ``pytest tests/unit/architecture -q``. The rule is the first paragraph "
                "of the module docstring; the checks are its test functions."
            ),
            self.section(
                "Gates",
                [table(["Module", "Rule", "Contract", "Checks"], rows, [20, 35, 15, 30])],
            ),
        ]
        layout_rows = [
            [
                literal(row["file"].rsplit("/", 1)[-1]),
                literal(f"hydromodpy/{row['package']}"),
                literal_list(row["parts"]),
                literal_list(row["other_keys"]) if row["other_keys"] else "-",
            ]
            for row in layouts
        ]
        out.append(
            self.section(
                "Import rules inside a package",
                [
                    para(
                        "``layer_matrix.yaml`` treats each package as one block. A package "
                        "whose parts are ordered carries a ``<package>_layout.yaml``, checked "
                        "by ``test_package_layouts.py``. Parts are listed lowest first: a part "
                        "may import only parts listed above it."
                    ),
                    table(
                        ["Contract", "Package", "Parts", "Other keys"],
                        layout_rows,
                        [18, 17, 50, 15],
                    ),
                ],
            )
        )
        return out


# -- CI workflows --------------------------------------------------------------


class CiDirective(_Generated):
    """Every workflow file, its triggers and what each job runs."""

    def run(self) -> list[nodes.Node]:
        workflows = _data().ci_workflows()
        summary = [
            [
                wf["name"],
                literal(wf["file"].rsplit("/", 1)[-1]),
                bullets(wf["triggers"]),
                len(wf["jobs"]),
            ]
            for wf in workflows
        ]
        out: list[nodes.Node] = [
            self.source_note("``.github/workflows/*.yml``"),
            para(
                f"{len(workflows)} workflows. A trigger with path filters runs only when a "
                "changed file matches one of them; the filters are in the file."
            ),
            table(["Workflow", "File", "Triggers", "Jobs"], summary, [32, 22, 38, 8]),
        ]
        for wf in workflows:
            rows = []
            for job in wf["jobs"]:
                name = job["name"]
                notes = []
                if job["matrix"]:
                    notes.append("matrix")
                if job["needs"]:
                    notes.append("after " + ", ".join(job["needs"]))
                label: list[nodes.Node] = [para(name)]
                if notes:
                    label.append(para("(" + "; ".join(notes) + ")"))
                steps = bullets(job["steps"]) if job["steps"] else para(f"calls {job['uses']}")
                rows.append([label, steps])
            out.append(
                self.section(
                    wf["name"],
                    [
                        para(f"File ``{wf['file']}``."),
                        table(["Job", "Steps"], rows, [35, 65]),
                    ],
                )
            )
        return out


# -- test inventory ------------------------------------------------------------


class SuiteDirective(_Generated):
    """Test files and functions per tier and folder, and the markers."""

    def run(self) -> list[nodes.Node]:
        inv = _data().suite_inventory()
        total_files = sum(t["files"] for t in inv["tiers"])
        total_functions = sum(t["functions"] for t in inv["tiers"])
        tier_rows = [
            [literal(f"tests/{t['tier']}/"), t["files"], t["functions"], t["parametrized"]]
            for t in inv["tiers"]
        ]
        tier_rows.append(
            [
                "All tiers",
                total_files,
                total_functions,
                sum(t["parametrized"] for t in inv["tiers"]),
            ]
        )
        out: list[nodes.Node] = [
            self.source_note(
                "the test files of ``tests/``, read without running them, and ``pytest.ini``"
            ),
            para(
                "A test function is counted once. pytest collects one item per parameter "
                "set of a parametrized function, so ``pytest --collect-only`` reports more "
                "items than this page counts functions."
            ),
            self.section(
                "Tiers",
                [
                    table(
                        ["Tier", "Files", "Test functions", "Parametrized"],
                        tier_rows,
                        [40, 20, 20, 20],
                    )
                ],
            ),
        ]
        folder_sections = []
        for tier in inv["tiers"]:
            rows = [
                [literal(f["folder"]), f["files"], f["functions"]]
                for f in inv["folders"][tier["tier"]]
            ]
            folder_sections.append(
                self.section(
                    f"tests/{tier['tier']}",
                    [table(["Folder", "Files", "Test functions"], rows, [60, 20, 20])],
                )
            )
        out.append(self.section("Folders", folder_sections))
        marker_rows = [
            [literal(m["name"]), m["description"], m["functions"], m["files"]]
            for m in inv["markers"]
        ]
        children: list[nodes.Node] = [
            para(
                "Declared in ``pytest.ini``. A function counts when the mark decorates it; a "
                "file counts when its ``pytestmark`` carries the mark. ``tests/conftest.py`` "
                "also adds the mark of the tier to every test by path."
            ),
            table(["Marker", "Meaning", "Functions", "Files"], marker_rows, [18, 54, 14, 14]),
        ]
        if inv["undeclared_marks"]:
            note = para("Marks used in the tests and not declared in ``pytest.ini``: ")
            note += literal_list(inv["undeclared_marks"]).children
            note += nodes.Text(". A pytest plugin may declare them.")
            children.append(note)
        out.append(self.section("Markers", children))
        return out


# -- packages and registries ---------------------------------------------------


class PackagesDirective(_Generated):
    """What the registries hold, and one row per package of hydromodpy."""

    def run(self) -> list[nodes.Node]:
        data = _data()
        counts = data.registry_counts()
        packages = data.package_map()
        count_rows = [
            [r["what"], len(r["names"]), literal(r["source"]), literal_list(r["names"], limit=30)]
            for r in counts
        ]
        package_rows = []
        for p in packages:
            doc = f"contribute/architecture/packages/{p['package']}"
            name = nodes.paragraph()
            name += (
                self.doc_link(doc, p["package"])
                if doc in self.env.found_docs
                else literal(p["package"])
            )
            package_rows.append(
                [
                    [name],
                    "yes" if p["layer"] else "no",
                    p["modules"],
                    p["lines"],
                    p["summary"] or "-",
                ]
            )
        return [
            self.source_note("the registries of the code and the folders of ``hydromodpy/``"),
            self.section(
                "Registries",
                [
                    para("Counted when the site is built. A name list longer than 30 is cut."),
                    table(["What", "Count", "Source", "Names"], count_rows, [20, 8, 27, 45]),
                ],
            ),
            self.section(
                "Packages",
                [
                    para(
                        "One row per sub-package of ``hydromodpy``. The summary is the first "
                        "paragraph of its ``README.md``, the map of the package."
                    ),
                    table(
                        ["Package", "Layer", "Modules", "Lines", "Summary"],
                        package_rows,
                        [13, 8, 9, 9, 61],
                    ),
                ],
            ),
        ]


# -- storage tree --------------------------------------------------------------


class StorageDirective(_Generated):
    """The folders of a project, a workspace and the machine, named by their constants."""

    def run(self) -> list[nodes.Node]:
        data = _data()
        tree = data.storage_tree()

        def block(rows: list[dict[str, Any]], title: str, intro: str) -> nodes.section:
            text = data.tree_text(rows)
            code = nodes.literal_block(text, text, language="text")
            table_rows = []
            for row in rows:
                label = [nodes.paragraph("", "", literal(row["path"]))]
                if row.get("required"):
                    label.append(para("always written"))
                symbol = ".".join(row["constant"].split(".")[-2:]) if row["constant"] else ""
                table_rows.append([label, literal(symbol) if symbol else "-", row["doc"] or "-"])
            return self.section(
                title,
                [
                    para(intro),
                    code,
                    table(["Entry", "Declared by", "Meaning"], table_rows, [25, 30, 45]),
                ],
            )

        layer_rows = [
            [literal(r["name"]), r["scope"], literal(r["path"]), r["role"]] for r in tree["layers"]
        ]
        return [
            self.source_note(
                "``hydromodpy/results/storage/contract.py``, ``hydromodpy/core/state/paths.py`` "
                "and ``hydromodpy/schema/generated_views.py``"
            ),
            para(
                "Each name below is a constant or a path helper of one of these modules, "
                "named as ``<module>.<name>``; the meaning is its docstring. The tables list "
                "the entries in the order of the tree. ``tests/unit/results/test_run_layout_contract.py`` checks a "
                "real run against the same constants."
            ),
            block(
                tree["project"],
                "Project",
                "A run directory may hold only the entries listed under ``<run>/``.",
            ),
            block(tree["workspace"], "Workspace", "A workspace groups projects."),
            block(
                tree["machine"],
                "Machine",
                "Folders outside any project, shared by every project of the machine.",
            ),
            self.section(
                "Storage layers",
                [
                    para("Where each kind of result is stored."),
                    table(["Layer", "Scope", "Path", "Role"], layer_rows, [12, 10, 38, 40]),
                ],
            ),
        ]


# -- environment variables -----------------------------------------------------


_SCOPE_TITLES = {
    "user": ("For users", "Variables a person running HydroModPy may set."),
    "dev": (
        "For debugging",
        "Variables that trace or keep intermediate files, or that HydroModPy sets itself.",
    ),
    "test": ("For the test suite", "Variables read by the tests and the validation cases."),
    "docs": ("For the documentation build", "Variables read by the build of this site."),
}


def _readers(code: list[str], tests: list[str]) -> nodes.paragraph:
    """The code files that read a variable, then the number of test files.

    A variable read only by tests lists the test files instead.
    """
    if not code:
        return literal_list(tests, limit=3)
    node = literal_list(code, limit=3)
    if tests:
        node += nodes.Text(f"; {len(tests)} test file" + ("s" if len(tests) > 1 else ""))
    return node


class EnvDirective(_Generated):
    """The registry of environment variables, one section per scope."""

    def run(self) -> list[nodes.Node]:
        rows = _data().environment_rows()
        out: list[nodes.Node] = [
            self.source_note(
                "``hydromodpy/core/env.py``; the files that read each variable come from a scan "
                "of the code"
            ),
            para(
                f"{len(rows)} variables. "
                "``tests/unit/architecture/test_env_vars_are_registered.py`` fails when the "
                "code names a ``HMP_*`` variable that has no row in the registry, or when a "
                "row names a variable nothing reads."
            ),
        ]
        for scope, (title, intro) in _SCOPE_TITLES.items():
            scoped = [r for r in rows if r["scope"] == scope]
            if not scoped:
                continue
            table_rows = [
                [
                    literal(r["name"]),
                    r["default"],
                    r["description"],
                    _readers(r["code_readers"], r["test_readers"]),
                ]
                for r in scoped
            ]
            out.append(
                self.section(
                    title,
                    [
                        para(intro),
                        table(
                            ["Variable", "When unset", "What it does", "Read in"],
                            table_rows,
                            [24, 16, 36, 24],
                        ),
                    ],
                )
            )
        return out


# -- extras --------------------------------------------------------------------


class ExtrasDirective(_Generated):
    """The optional-dependency groups of pyproject.toml."""

    def run(self) -> list[nodes.Node]:
        rows = []
        for r in _data().extras():
            note = "-"
            if r["already_required"]:
                note = (
                    "Already a dependency of the base install: "
                    + ", ".join(f"``{n}``" for n in r["already_required"])
                    + "."
                )
            rows.append(
                [
                    literal(r["extra"]),
                    literal(f'pip install "hydromodpy[{r["extra"]}]"'),
                    bullets([f"``{req}``" for req in r["requirements"]]),
                    literal_list(r["used_by"]) if r["used_by"] else "no package of ``hydromodpy``",
                    note,
                ]
            )
        return [
            self.source_note("``[project.optional-dependencies]`` of ``pyproject.toml``"),
            para(
                "Imported by: the sub-packages of ``hydromodpy`` that import a module of the "
                "group, found by reading the imports. A group that no package imports serves "
                "the tools around the code: tests, documentation, editors."
            ),
            table(
                ["Extra", "Install", "Requirements", "Imported by", "Note"],
                rows,
                [10, 25, 30, 15, 20],
            ),
        ]


# -- setup ---------------------------------------------------------------------


def _always_reread(app: Sphinx, env, added, changed, removed) -> list[str]:
    """The sources of these pages are not pages: read them again at every build."""
    return [doc for doc in env.found_docs if doc.startswith(GENERATED_PREFIX)]


DIRECTIVES = {
    "hmp-contribute-layers": LayersDirective,
    "hmp-contribute-guards": GuardsDirective,
    "hmp-contribute-ci": CiDirective,
    "hmp-contribute-tests": SuiteDirective,
    "hmp-contribute-packages": PackagesDirective,
    "hmp-contribute-storage": StorageDirective,
    "hmp-contribute-env": EnvDirective,
    "hmp-contribute-extras": ExtrasDirective,
}


def setup(app: Sphinx) -> dict[str, Any]:
    app.setup_extension("sphinx.ext.graphviz")
    for name, directive in DIRECTIVES.items():
        app.add_directive(name, directive)
    app.connect("env-get-outdated", _always_reread)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
