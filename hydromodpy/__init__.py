"""Public entry points for HydroModPy."""

from __future__ import annotations

import importlib

# Public API facade. This is the single allowed exception to the
# "no aliases / no re-exports" rule in CLAUDE.md. CLI verbs and Python
# user code must reach the same canonical symbols through this module,
# so the verbs in `hydromodpy/_api` are re-exported here on purpose.
from hydromodpy import catalog  # noqa: F401  --  expose ``hmp.catalog`` namespace
from hydromodpy._api import (
    add_data_entry,
    archive_data_cache,
    audit_list,
    audit_verify,
    calibrate,
    check_data_cache,
    clean_workspace,
    compare,
    compare_pair,
    create_project,
    delete_project,
    delete_simulation,
    doctor,
    export_simulation_package,
    fetch_data_variable,
    forget_workspace,
    gc,
    import_package,
    index,
    init_workspace,
    list_data_cache,
    list_projects,
    list_simulations,
    list_workspaces,
    mesh,
    open,
    open_catalog,
    overview,
    prune_data_cache,
    prune_workspaces,
    purge_simulation,
    query_catalog,
    read,
    register_workspace,
    remove_data_entries,
    render_figure,
    render_gallery,
    report,
    restore_data_cache,
    run,
    search_workspaces,
    show_project,
    show_simulation,
    testbed,
    vacuum,
    verify_purge_certificate,
)
from hydromodpy._bootstrap import bootstrap
from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS
from hydromodpy._lazy import MODULE_EXPORTS as _MODULE_EXPORTS
from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
from hydromodpy.core.logging import LogManager
from hydromodpy.core.version import __version__

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager

_DIRECT_EXPORTS = [
    "open",
    "open_catalog",
    "catalog",
    "read",
    "run",
    "calibrate",
    "index",
    "overview",
    "compare",
    "compare_pair",
    "mesh",
    "testbed",
    "report",
    "list_simulations",
    "show_simulation",
    "query_catalog",
    "create_project",
    "list_projects",
    "show_project",
    "delete_project",
    "init_workspace",
    "list_workspaces",
    "register_workspace",
    "search_workspaces",
    "forget_workspace",
    "prune_workspaces",
    "clean_workspace",
    "gc",
    "vacuum",
    "delete_simulation",
    "list_data_cache",
    "fetch_data_variable",
    "check_data_cache",
    "add_data_entry",
    "remove_data_entries",
    "prune_data_cache",
    "archive_data_cache",
    "restore_data_cache",
    "import_package",
    "export_simulation_package",
    "render_figure",
    "render_gallery",
    "audit_list",
    "audit_verify",
    "purge_simulation",
    "verify_purge_certificate",
    "bootstrap_proj",
    "doctor",
    "log_manager",
    "__version__",
]


def __getattr__(name: str):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        target = _LAZY_IMPORTS[name]
        if ":" in target:
            module_path, attr_name = target.split(":", 1)
        else:
            module_path, attr_name = target, name
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")


__all__ = [*_DIRECT_EXPORTS, *_LAZY_IMPORTS, *_MODULE_EXPORTS]

bootstrap()
