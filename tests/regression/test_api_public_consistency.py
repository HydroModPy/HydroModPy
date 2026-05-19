"""CI lint: enforce ``__all__`` ⟷ ``_LAZY_IMPORTS`` ∪ ``_MODULE_EXPORTS``.

Every key in ``hydromodpy._LAZY_IMPORTS`` and ``hydromodpy._MODULE_EXPORTS``
must appear in ``hydromodpy.__all__`` and resolve via ``hmp.<name>``. Any
direct (non-lazy) export defined in ``hydromodpy/__init__.py`` must be
listed in ``_DIRECT_EXPORTS`` below so additions are explicitly registered.
"""

from __future__ import annotations

import pytest

import hydromodpy as hmp
from hydromodpy import _LAZY_IMPORTS, _MODULE_EXPORTS

pytestmark = [pytest.mark.regression, pytest.mark.fast]


# Symbols defined inline in ``hydromodpy/__init__.py`` (not via lazy import or
# module re-export). Adding or removing one here is a deliberate API change.
_DIRECT_EXPORTS = frozenset(
    {
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
        "export_schema",
        "validate_field",
        "rank_simulations",
        "install_binaries",
        "lock_update",
        "lock_archive",
        "lock_restore",
        "lock_verify",
        "config_template",
        "config_check",
        "run_tests",
        "doctor",
        "bootstrap_proj",
        "log_manager",
        "__version__",
    }
)


@pytest.mark.parametrize("name", sorted(_LAZY_IMPORTS))
def test_lazy_import_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"_LAZY_IMPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", sorted(_MODULE_EXPORTS))
def test_module_export_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"_MODULE_EXPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", sorted(set(_LAZY_IMPORTS) | set(_MODULE_EXPORTS)))
def test_lazy_or_module_resolves(name: str) -> None:
    assert getattr(hmp, name) is not None


def test_all_set_equals_lazy_union_module_union_direct() -> None:
    expected = set(_LAZY_IMPORTS) | set(_MODULE_EXPORTS) | set(_DIRECT_EXPORTS)
    actual = set(hmp.__all__)
    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"__all__ drift detected. missing={sorted(missing)} extra={sorted(extra)}"
    )


def test_all_has_no_duplicates() -> None:
    assert len(hmp.__all__) == len(set(hmp.__all__))


def test_lazy_and_module_keys_disjoint() -> None:
    overlap = set(_LAZY_IMPORTS) & set(_MODULE_EXPORTS)
    assert not overlap, f"keys present in both _LAZY_IMPORTS and _MODULE_EXPORTS: {sorted(overlap)}"
