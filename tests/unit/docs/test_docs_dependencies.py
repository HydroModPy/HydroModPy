from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT_PATH = ROOT / "pyproject.toml"
DOCS_REQUIREMENTS_PATH = ROOT / "docs" / "requirements.txt"
EDITABLE_ENVIRONMENT_PATHS = [
    ROOT / "install" / "env_hydromodpy_pkg.yml",
    ROOT / "install" / "env_hydromodpy_light_pkg.yml",
]
CONF_PATH = ROOT / "docs" / "source" / "conf.py"
LOCAL_EXTENSION_DIR = ROOT / "docs" / "source" / "_ext"
# Namespace packages whose distribution name cannot be derived from the module
# path by replacing separators with dashes.
MODULE_TO_DISTRIBUTION: dict[str, str] = {}


def _normalize_requirement(requirement: str) -> str:
    requirement = requirement.split(";", 1)[0].strip()
    requirement = re.split(r"[<>=!~]", requirement, maxsplit=1)[0]
    requirement = requirement.split("[", 1)[0]
    return requirement.strip().lower().replace("_", "-")


def test_docs_extra_covers_local_sphinx_notebook_and_uml_build_deps() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    docs_extra = {
        _normalize_requirement(requirement)
        for requirement in pyproject["project"]["optional-dependencies"]["docs"]
    }

    required_for_local_docs_build = {
        "sphinx",
        "pydata-sphinx-theme",
        "myst-parser",
        "sphinx-copybutton",
        "sphinx-design",
        "sphinx-polyversion",
        "sphinxcontrib-plantuml",
    }
    docs_requirements = {
        _normalize_requirement(line)
        for line in DOCS_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    expected = required_for_local_docs_build & docs_requirements
    missing = expected - docs_extra

    assert not missing, (
        "The docs extra should install the core local Sphinx/PlantUML/notebook "
        f"build dependencies. Missing: {sorted(missing)}"
    )


def test_editable_conda_environments_install_docs_extra() -> None:
    expected_pattern = re.compile(
        r'^\s*-\s+-e\s+["\']?\.\.\[(?:[A-Za-z0-9_-]+,)*docs'
        r'(?:,[A-Za-z0-9_-]+)*\]["\']?\s*$',
        re.MULTILINE,
    )

    missing_docs_extra = [
        environment_path.name
        for environment_path in EDITABLE_ENVIRONMENT_PATHS
        if expected_pattern.search(environment_path.read_text(encoding="utf-8")) is None
    ]

    assert not missing_docs_extra, (
        "Editable conda environments should install the repository docs extra "
        f"so local Sphinx builds include notebook extensions. Missing: {missing_docs_extra}"
    )


def _string_list_assignment(tree: ast.Module, name: str) -> list[str]:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        assert isinstance(node.value, ast.List), f"{name} in conf.py is not a list literal"
        return [
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    raise AssertionError(f"conf.py no longer assigns {name}")


def _distribution_for(module: str) -> str:
    return MODULE_TO_DISTRIBUTION.get(module, module.replace(".", "-").replace("_", "-"))


def test_docs_extra_installs_every_third_party_sphinx_extension() -> None:
    """An extension the extra never installs stays green on a developer machine.

    The leftover wheel in the conda environment hides it until CI runs.
    """

    tree = ast.parse(CONF_PATH.read_text(encoding="utf-8"))
    local_extensions = {path.stem for path in LOCAL_EXTENSION_DIR.glob("*.py")}
    modules = {
        module
        for name in ("extensions", "_DOC_REQUIRED_EXTENSIONS")
        for module in _string_list_assignment(tree, name)
        if not module.startswith("sphinx.ext.") and module not in local_extensions
    }

    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    docs_extra = {
        _normalize_requirement(requirement)
        for requirement in pyproject["project"]["optional-dependencies"]["docs"]
    }

    missing = sorted(
        f"{module} (expected the {_distribution_for(module)} distribution)"
        for module in modules
        if _distribution_for(module) not in docs_extra
    )

    assert not missing, (
        "Every Sphinx extension conf.py loads or requires must come from the "
        f"docs extra, otherwise `pip install -e '.[docs]'` cannot build. Missing: {missing}"
    )
