"""Which import paths are public, and which port is stable.

``contracts.rst`` holds the list, so this file reads it and repeats nothing. A listed
module has to exist, and a page of the reference or of the how-to guides can only
teach an import that the list or the facade answers for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.calibration.evaluation import forward_registry
from hydromodpy.calibration.evaluation import registry as evaluator_registry
from hydromodpy.catchment.terrain import registry as terrain_registry
from hydromodpy.data.source import registry as source_registry
from hydromodpy.mesh import registry as mesh_registry
from hydromodpy.solver.base import registry as solver_registry

pytestmark = pytest.mark.fast

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "source"
CONTRACTS = DOCS / "contribute" / "architecture" / "contracts.rst"
TAUGHT_IN = (DOCS / "reference", DOCS / "contribute" / "architecture" / "how-to")

# The how-to of a data source builds this package as its worked example.
THE_PAGE_CREATES_IT = ("hydromodpy.data.variables.wind",)

IMPORT = re.compile(
    r"^\s*(?:from\s+(hydromodpy[\w.]*)\s+import\s+([^#\n]+)|import\s+(hydromodpy[\w.]*))", re.M
)

# Decision D10 of the campaign before 2.0.0. A port changes here and on the page together.
PORT_STABILITY = {
    terrain_registry.ENTRY_POINT_GROUP: "stable",
    mesh_registry.ENTRY_POINT_GROUP: "stable",
    source_registry.ENTRY_POINT_GROUP: "stable",
    forward_registry.ENTRY_POINT_GROUP: "stable signature, experimental construction options",
    evaluator_registry.ENTRY_POINT_GROUP: "experimental",
    solver_registry.ENTRY_POINT_GROUP: "experimental",
    solver_registry.EXTRACTOR_ENTRY_POINT_GROUP: "experimental",
}


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def listed_modules() -> list[str]:
    """The modules of the public list, read from the page."""
    text = CONTRACTS.read_text(encoding="utf-8")
    block = _section(text, ".. public-modules-start", ".. public-modules-end")
    return re.findall(r"^- ``(hydromodpy[\w.]*)``", block, re.M)


def _source_of(module: str) -> Path | None:
    base = ROOT / Path(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def test_the_list_is_read() -> None:
    assert len(listed_modules()) > 20
    assert len(set(listed_modules())) == len(listed_modules())


@pytest.mark.parametrize("module", listed_modules())
def test_a_listed_module_exists_and_is_not_private(module: str) -> None:
    assert _source_of(module) is not None, f"{module} is on the public list and does not exist."
    assert not any(part.startswith("_") for part in module.split(".")), module


def _taught_imports() -> list[tuple[str, str, str]]:
    """Each (page, module, imported names) of the pages that teach an import."""
    found = []
    for directory in TAUGHT_IN:
        for page in sorted(directory.rglob("*")):
            if page.suffix in (".md", ".rst") and page.is_file():
                for from_module, names, plain in IMPORT.findall(page.read_text(encoding="utf-8")):
                    found.append((page.relative_to(DOCS).as_posix(), from_module or plain, names))
    return found


def test_the_pages_teach_an_import() -> None:
    assert {module for _, module, _ in _taught_imports()} >= {"hydromodpy", "hydromodpy.schema"}


def test_a_page_imports_only_what_the_list_or_the_facade_answers_for() -> None:
    allowed = set(listed_modules())
    outside = [
        f"{page}: {module}"
        for page, module, _ in _taught_imports()
        if module != "hydromodpy"
        and module not in allowed
        and not module.startswith(THE_PAGE_CREATES_IT)
    ]
    assert outside == [], (
        f"{outside} teach a module outside the public list. Import from the facade, or add the "
        "module to the list in docs/source/contribute/architecture/contracts.rst."
    )


def test_a_name_imported_from_the_package_is_in_the_facade() -> None:
    names = [
        name.split(" as ")[0].strip()
        for _, module, imported in _taught_imports()
        if module == "hydromodpy"
        for name in imported.strip(" ()").split(",")
        if name.strip()
    ]
    assert sorted(set(names) - set(hmp.__all__)) == []


def test_the_page_states_the_stability_of_every_port() -> None:
    text = _section(
        CONTRACTS.read_text(encoding="utf-8"), "Plugin ports\n", "Changing a contract\n"
    )
    rows = re.findall(r"\* - ``(hydromodpy[\w.]*)``\n\s+- ``\w+``, ``[\w.]+``\n\s+- ([^\n]+)", text)
    assert dict(rows) == PORT_STABILITY


def test_a_port_named_on_the_page_lives_in_a_listed_module() -> None:
    text = _section(
        CONTRACTS.read_text(encoding="utf-8"), "Plugin ports\n", "Changing a contract\n"
    )
    modules = re.findall(r"- ``\w+``, ``(hydromodpy[\w.]*)``", text)
    assert len(modules) == len(PORT_STABILITY)
    assert sorted(set(modules) - set(listed_modules())) == []
