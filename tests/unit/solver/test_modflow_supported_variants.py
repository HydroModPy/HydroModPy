"""Guard tests for the supported MODFLOW solver variants.

HydroModPy only wraps MODFLOW-NWT and MODFLOW 6. Older MODFLOW 2000/2005
binaries and the MODFLOW-USG unstructured branch are explicitly out of scope:
no adapter, no translator, no solver config exists for them. These tests make
sure the ``flow_translator`` rejects these names fast, before the planner
commits to a simulation that no solver can run.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_common.flow_translator import (
    MF6_PACKAGES,
    NWT_PACKAGES,
    BoundaryKind,
    resolve_package,
    resolve_packages,
)


@pytest.mark.parametrize(
    "solver_key",
    ["modflownwt", "modflow-nwt", "nwt", "modflow6", "mf6"],
)
def test_resolve_package_accepts_supported_solver_keys(solver_key: str) -> None:
    """Every officially supported solver alias resolves without error."""
    assert resolve_package(BoundaryKind.STREAM, solver=solver_key) == "Riv"


@pytest.mark.parametrize(
    "legacy_key",
    [
        "modflow2000",
        "modflow-2000",
        "mf2000",
        "modflow2005",
        "mf2005",
        "modflowusg",
        "modflow-usg",
        "mfusg",
    ],
)
def test_resolve_package_rejects_unsupported_modflow_variants(legacy_key: str) -> None:
    """Legacy MODFLOW-2000 / MODFLOW-USG aliases are refused at translation time."""
    with pytest.raises(ValueError, match="Unknown MODFLOW solver key"):
        resolve_package(BoundaryKind.DRAIN, solver=legacy_key)


def test_dispatch_tables_expose_only_nwt_and_mf6() -> None:
    """Dispatch tables are limited to the two solvers HydroModPy ships with."""
    assert set(NWT_PACKAGES).issubset(set(BoundaryKind))
    assert set(MF6_PACKAGES).issubset(set(BoundaryKind))
    # Every BoundaryKind must be covered so we cannot silently fall back on a
    # non-existent legacy package for either solver.
    assert set(NWT_PACKAGES) == set(BoundaryKind)
    assert set(MF6_PACKAGES) == set(BoundaryKind)


def test_resolve_packages_rejects_legacy_variant_in_list() -> None:
    """Batch resolution also guards against unsupported solver keys."""
    with pytest.raises(ValueError, match="Unknown MODFLOW solver key"):
        resolve_packages([BoundaryKind.WELL, BoundaryKind.CHD], solver="mfusg")
