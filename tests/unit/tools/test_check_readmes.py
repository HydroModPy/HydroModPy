"""The README gate computes which READMEs may exist and refuses the others.

The permitted set is read from the layer matrix and from the code, so these
tests build a small repository under ``tmp_path`` that holds one of each kind
(package, registry folder, backend, closed table, sibling) and compare the set
with the one the gate returns. A second table holds one README per refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs import check_readmes

ROOT = Path(__file__).resolve().parents[3]

MATRIX = """\
allowed:
  core:   [core]
  data:   [core, data]
  mesh:   [core, mesh]
  solver: [core, data, mesh, solver]
  "<root>": ["<root>", core]
  "<main>": ["<main>", core]
siblings:
  hydromodpy_server: ["<root>", core]
"""

FILES = {
    "tests/unit/architecture/layer_matrix.yaml": MATRIX,
    # A closed table in a folder of a package.
    "hydromodpy/core/scoring/metric_table.py": "class MetricSpec:\n    pass\n",
    "hydromodpy/core/plugin_registry.py": "class PluginRegistry:\n    pass\n",
    # A registry in a folder below the package, with a literal behind a name.
    "hydromodpy/data/source/registry.py": (
        "_PATHS = {'a': 'hydromodpy.data.source.file:File'}\n"
        "data_sources: object = PluginRegistry(kind='x', builtin_paths=_PATHS)\n"
    ),
    # A registry at the root of its package: the package README is its port.
    "hydromodpy/mesh/registry.py": "mesh_engines = PluginRegistry(kind='x', builtin_paths={})\n",
    # The solver registry, whose built-in adapters sit in folders beside it.
    "hydromodpy/solver/base/registry.py": (
        "_PATHS = {\n"
        "    'flow_alpha': 'hydromodpy.solver.alpha.adapter:Alpha',\n"
        "    'flow_beta': 'hydromodpy.solver.beta.deep.adapter:Beta',\n"
        "    'flow_base': 'hydromodpy.solver.base.adapter:Base',\n"
        "}\n"
        "solvers = PluginRegistry(kind='x', builtin_paths=_PATHS)\n"
    ),
    "hydromodpy/solver/alpha/adapter.py": "",
    "hydromodpy/solver/beta/deep/adapter.py": "",
    "hydromodpy/solver/base/adapter.py": "",
    # A registry that is not the solver registry keeps its members as modules.
    "hydromodpy/data/variables/registry.py": (
        "variables = PluginRegistry(kind='y', builtin_paths={'v': 'hydromodpy.data.other.v:V'})\n"
    ),
    "hydromodpy/data/other/v.py": "",
}

ALLOWED = {
    "hydromodpy/core/README.md": "package",
    "hydromodpy/data/README.md": "package",
    "hydromodpy/mesh/README.md": "package",
    "hydromodpy/solver/README.md": "package",
    "hydromodpy/core/scoring/README.md": "port",
    "hydromodpy/data/source/README.md": "port",
    "hydromodpy/data/variables/README.md": "port",
    "hydromodpy/solver/base/README.md": "port",
    "hydromodpy/solver/alpha/README.md": "port",
    "hydromodpy/solver/beta/README.md": "port",
    "hydromodpy_server/README.md": "sibling",
}

GOOD = "# Title\n\nOne short paragraph in English that says what the folder does.\n"


def build_repo(root: Path) -> Path:
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name in ALLOWED:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(GOOD, encoding="utf-8")
    return root


def test_the_permitted_set_is_read_from_the_matrix_and_the_code(tmp_path: Path) -> None:
    repo = build_repo(tmp_path)
    got = {path.as_posix(): kind for path, kind in check_readmes.allowed_readmes(repo).items()}
    assert got == ALLOWED


def test_the_real_set_holds_the_packages_the_registries_and_the_backends() -> None:
    got = {p.as_posix(): kind for p, kind in check_readmes.allowed_readmes(ROOT).items()}
    for name in ("core", "model", "solver", "results", "calibration", "cli", "project"):
        assert got[f"hydromodpy/{name}/README.md"] == "package"
    for folder in (
        "solver/base",
        "solver/modflow6",
        "solver/modflow_nwt",
        "solver/boussinesq",
        "solver/linear_reservoir",
        "data/source",
        "catchment/terrain",
        "calibration/evaluation",
        "calibration/optim",
        "results/exporters",
        "core/scoring",
        "model/boundaries",
    ):
        assert got[f"hydromodpy/{folder}/README.md"] == "port"
    assert got["hydromodpy_server/README.md"] == "sibling"
    assert got["hydromodpy_annex/README.md"] == "sibling"
    assert len(got) == 28


def test_the_real_registries_are_the_eight_of_the_code() -> None:
    names = sorted(ref.name for ref in check_readmes.plugin_registries(ROOT))
    assert names == [
        "data_sources",
        "evaluators",
        "export_formats",
        "extractors",
        "mesh_engines",
        "optimizers",
        "solvers",
        "terrain_engines",
    ]


def test_a_clean_fake_repository_has_no_problem(tmp_path: Path) -> None:
    assert check_readmes.check(build_repo(tmp_path)) == []


def test_the_real_repository_has_no_problem() -> None:
    assert check_readmes.check(ROOT) == []


LONG_PORT = "# Port\n\n" + "\n".join(f"Line {i} of a port contract." for i in range(29)) + "\n"

REFUSALS = [
    pytest.param(
        "hydromodpy/core/extra/README.md",
        GOOD,
        "hydromodpy/core/extra/README.md: a README goes in a package or a port folder only "
        "(rule 17); move what it says to the package page or to the module docstring",
        id="a README outside the set",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        None,
        "hydromodpy/core/README.md: this package or port has no README (rule 17)",
        id="a permitted README that is absent",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\n" + "\n".join(f"Line {i} of the package." for i in range(20)) + "\n",
        "hydromodpy/core/README.md: 21 lines, a package README holds about ten and a port README "
        "about twenty (rule 17)",
        id="a package of 21 lines",
    ),
    pytest.param(
        "hydromodpy/core/scoring/README.md",
        LONG_PORT + "One more line.\n",
        "hydromodpy/core/scoring/README.md: 31 lines, a package README holds about ten and a "
        "port README about twenty (rule 17)",
        id="a port of 31 lines",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\n- **Name** what it is.\n",
        "hydromodpy/core/README.md:3: a bullet with a bold label (rule 17)",
        id="a bullet with a bold label",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\nThe kernel — and nothing else.\n",
        "hydromodpy/core/README.md:3: a dash used as punctuation (rule 17)",
        id="an em dash",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\nPages 3 – 5 hold the table.\n",
        "hydromodpy/core/README.md:3: a dash used as punctuation (rule 17)",
        id="an en dash",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\nThe kernel.\n\n## Summary\n",
        "hydromodpy/core/README.md:5: a closing summary (rule 17)",
        id="a closing summary",
    ),
    pytest.param(
        "hydromodpy/core/README.md",
        "# core\n\nLe noyau est une couche sans voisin.\n",
        "hydromodpy/core/README.md:3: French text, a README is in English (rule 17)",
        id="French text",
    ),
]


@pytest.mark.parametrize(("name", "text", "expected"), REFUSALS)
def test_a_readme_is_refused_with_its_sentence(
    tmp_path: Path, name: str, text: str | None, expected: str
) -> None:
    repo = build_repo(tmp_path)
    path = repo / name
    if text is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert check_readmes.check(repo) == [expected]


def test_a_port_of_thirty_lines_and_a_package_of_twenty_pass(tmp_path: Path) -> None:
    repo = build_repo(tmp_path)
    (repo / "hydromodpy/core/scoring/README.md").write_text(LONG_PORT, encoding="utf-8")
    package = "# core\n\n" + "\n".join(f"Line {i} of the package." for i in range(19)) + "\n"
    (repo / "hydromodpy/core/README.md").write_text(package, encoding="utf-8")
    assert check_readmes.check(repo) == []


def test_a_french_looking_line_in_a_code_block_is_not_read(tmp_path: Path) -> None:
    repo = build_repo(tmp_path)
    text = "# core\n\nA run reads one table.\n\n```toml\nname = 'la le des'\n```\n"
    (repo / "hydromodpy/core/README.md").write_text(text, encoding="utf-8")
    assert check_readmes.check(repo) == []
