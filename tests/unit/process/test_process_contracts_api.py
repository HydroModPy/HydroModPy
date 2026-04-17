"""Compatibility checks for process contract imports."""

from __future__ import annotations

import warnings

import hydromodpy.process as process_root
from hydromodpy.process.contracts import (
    Process as ContractProcess,
    ProcessSpatial as ContractProcessSpatial,
    ProcessSpatialConfig as ContractProcessSpatialConfig,
)
from hydromodpy.process.prototype import (
    Process as PrototypeProcess,
    ProcessSpatial as PrototypeProcessSpatial,
    ProcessSpatialConfig as PrototypeProcessSpatialConfig,
)


def test_process_contracts_module_reexports_prototype_symbols() -> None:
    assert ContractProcess is PrototypeProcess
    assert ContractProcessSpatial is PrototypeProcessSpatial
    assert ContractProcessSpatialConfig is PrototypeProcessSpatialConfig


def test_process_root_reexports_contract_symbols_for_compatibility() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        process = process_root.Process
        process_spatial = process_root.ProcessSpatial
        process_spatial_config = process_root.ProcessSpatialConfig

    assert process is ContractProcess
    assert process_spatial is ContractProcessSpatial
    assert process_spatial_config is ContractProcessSpatialConfig
    assert len(caught) == 3
    for warning in caught:
        assert issubclass(warning.category, DeprecationWarning)
        assert "hydromodpy.process.contracts" in str(warning.message)


def test_process_root_keeps_concrete_process_exports_non_deprecated() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        flow = process_root.Flow
        transport = process_root.Transport

    assert flow.__name__ == "Flow"
    assert transport.__name__ == "Transport"
    assert caught == []
