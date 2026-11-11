"""Gate: the trial pipeline is the only global the library keeps.

Four rules, measured on the tree of the refactoring.

1. An injection site is a public module-level function of a module of
   ``hydromodpy/``, ``hydromodpy_annex/`` or ``hydromodpy_server/`` that writes a bare parameter
   value into a module global. Each global written on this code is written
   once, by one function.
2. The one global the library keeps is ``install_trial_pipeline`` of
   ``hydromodpy/calibration/runners/trial.py``, and it is called from
   ``hydromodpy/project/`` only.
3. The retired provider files exist nowhere under ``hydromodpy/``.
4. The retired provider names are defined and read nowhere.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TREE = Path(__file__).resolve().parents[3]
_TREE_FILES = _TREE / "hydromodpy"
SIBLINGS = (_TREE / "hydromodpy_annex", _TREE / "hydromodpy_server")

RETIRED_FILES = (
    "hydromodpy/_bootstrap.py",
    "hydromodpy/core/runtime/bootstrap_hook.py",
    "hydromodpy/core/config_kit/root_config_protocol.py",
    "hydromodpy/core/toml_io/dynamic_examples_protocol.py",
    "hydromodpy/catchment/protocols.py",
    "hydromodpy/calibration/runners/contracts.py",
    "hydromodpy/core/contracts/solver_registry.py",
    "hydromodpy/results/run/rerun_contract.py",
)

RETIRED_NAMES = (
    "ensure_bootstrapped",
    "bootstrap_hook",
    "get_root_config_provider",
    "get_root_config",
    "set_root_config",
    "get_trial_pipeline_provider",
    "set_trial_pipeline_provider",
    "get_calibration_provider",
    "get_data_source_provider",
    "get_worker_pool_provider",
    "get_display_provider",
    "get_run_provider",
    "get_fetch_provider",
    "get_observation_provider",
    "get_state_provider",
    "get_signal_provider",
    "get_overview_provider",
    "get_worker_provider",
    "register_calibrate_provider",
    "register_pipeline_provider",
    "register_signal_provider",
    "register_state_provider",
    "register_observation_provider",
    "register_display_provider",
    "register_fetch_provider",
    "register_run_provider",
    "register_overview_provider",
    "register_worker_provider",
)


def _python_files(tree: Path) -> list[Path]:
    """The modules of one tree."""
    if not tree.exists():
        return []
    return sorted(tree.rglob("*.py"))


def _source_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_injection_sites_in_tree(tree_root: Path, repo_root: Path) -> set[tuple[str, str]]:
    """Find public module-level functions that write a bare parameter into a global."""
    found: set[tuple[str, str]] = set()
    for path in _python_files(tree_root):
        rel_path = path.relative_to(repo_root).as_posix()
        try:
            module = ast.parse(_source_of(path))
        except SyntaxError:
            continue
        found.update(_find_injection_sites_in_ast(module, rel_path))
    return found


def _find_injection_sites_in_ast(module: ast.Module, rel_path: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            param_names = {
                arg.arg for arg in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
            }
            globals_in_fn: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Global):
                    globals_in_fn.update(sub.names)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if (
                            isinstance(tgt, ast.Name)
                            and tgt.id in globals_in_fn
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id in param_names
                        ):
                            found.add((rel_path, node.name))
    return found


def test_the_only_injection_site_is_install_trial_pipeline() -> None:
    found = _find_injection_sites_in_tree(_TREE_FILES, _TREE)
    for sibling in SIBLINGS:
        if sibling.exists():
            found |= _find_injection_sites_in_tree(sibling, _TREE)
    expected = {("hydromodpy/calibration/runners/trial.py", "install_trial_pipeline")}
    assert found == expected


def test_a_planted_module_with_a_parameter_written_into_a_global_is_caught() -> None:
    planted_source = """
_SOME_GLOBAL = None

def register_something(value):
    global _SOME_GLOBAL
    _SOME_GLOBAL = value
"""
    mod = ast.parse(planted_source)
    planted = _find_injection_sites_in_ast(mod, "hydromodpy/fake.py")
    assert planted == {("hydromodpy/fake.py", "register_something")}


def test_install_trial_pipeline_is_called_from_project_only() -> None:
    callers: set[str] = set()
    for root in (_TREE_FILES, *SIBLINGS):
        if not root.exists():
            continue
        for path in _python_files(root):
            try:
                mod = ast.parse(_source_of(path))
            except SyntaxError:
                continue
            for node in ast.walk(mod):
                if isinstance(node, ast.Call):
                    name = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name == "install_trial_pipeline":
                        callers.add(path.relative_to(_TREE).as_posix())

    for caller in callers:
        assert caller.startswith("hydromodpy/project/"), (
            f"install_trial_pipeline called from {caller}, only hydromodpy/project allowed"
        )
    assert len(callers) >= 1


def test_retired_provider_files_do_not_exist() -> None:
    for rel_path in RETIRED_FILES:
        path = _TREE / rel_path
        assert not path.exists(), f"Retired provider file still exists: {rel_path}"


def test_retired_provider_names_are_not_used() -> None:
    retired_set = set(RETIRED_NAMES)
    found_uses: dict[str, set[str]] = {}

    for folder in ("hydromodpy", "tests", "tools"):
        root = _TREE / folder
        if not root.exists():
            continue
        for path in _python_files(root):
            if path.name == "test_trial_pipeline_is_the_only_global.py":
                continue
            try:
                mod = ast.parse(_source_of(path))
            except SyntaxError:
                continue
            names_in_mod: set[str] = set()
            for node in ast.walk(mod):
                if isinstance(node, ast.Name):
                    names_in_mod.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names_in_mod.add(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names_in_mod.add(node.name)
                elif isinstance(node, ast.alias):
                    names_in_mod.add(node.name)

            hits = names_in_mod & retired_set
            if hits:
                rel = path.relative_to(_TREE).as_posix()
                found_uses[rel] = hits

    assert not found_uses, f"Retired provider names found: {found_uses}"
