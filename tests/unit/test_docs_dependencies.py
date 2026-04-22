from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = ROOT / "pyproject.toml"
RTD_REQUIREMENTS_PATH = ROOT / "docs" / "readthedocs" / "readthedocs_requirements.txt"


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
        "nbsphinx",
        "nbconvert",
        "nbformat",
        "jupyter-client",
        "sphinx-gallery",
        "sphinx-copybutton",
        "sphinx-design",
        "sphinx-tabs",
        "sphinx-togglebutton",
        "sphinx-multiversion",
        "sphinxcontrib-plantuml",
        "autodoc-pydantic",
    }
    rtd_requirements = {
        _normalize_requirement(line)
        for line in RTD_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    expected = required_for_local_docs_build & rtd_requirements
    missing = expected - docs_extra

    assert not missing, (
        "The docs extra should install the core local Sphinx/PlantUML/notebook "
        f"build dependencies. Missing: {sorted(missing)}"
    )
