"""Unit tests for the ``SolverAdapter`` Protocol and ``RunResult`` dataclass."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import hydromodpy.solver as solver_root
import hydromodpy.solver.modflow6.extractors.lake as lake_extractor
import hydromodpy.solver.modflow_common.calibration_extractors as calibration_extractors
import hydromodpy.solver.modflow_common.observable_extraction as observable_extraction
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError
from hydromodpy.solver.base import (
    SolverAdapter as BaseSolverAdapter,
)
from hydromodpy.solver.base import (
    SolverConfig as BaseSolverConfig,
)
from hydromodpy.solver.base import registry
from hydromodpy.solver.base.adapter_protocol import RunResult, SolverAdapter
from hydromodpy.solver.contracts import (
    SolverAdapter as ContractSolverAdapter,
)
from hydromodpy.solver.contracts import (
    SolverConfig as ContractSolverConfig,
)
from hydromodpy.solver.modflow_common import binaries
from hydromodpy.solver.modflow_common.flow_translator import (
    MF6_PACKAGES,
    NWT_PACKAGES,
    BoundaryKind,
    resolve_package,
    resolve_packages,
)


class DummyAdapter:
    """Minimal structural conformer used to exercise the Protocol."""

    process_type = "flow"
    solver_name = "dummy"
    requires: tuple[tuple[str, str], ...] = ()

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, ctx: object) -> None:
        self.calls.append("validate")

    def execute(self, ctx: object) -> object:
        self.calls.append("execute")
        return object()

    def cleanup(self, ctx: object) -> None:
        self.calls.append("cleanup")

    def extract_observables(
        self, ctx: object, store: object, requests: object, **kwargs: object
    ) -> object:
        self.calls.append("extract_observables")
        return {}


class PartialAdapter:
    """Missing ``execute`` on purpose to check structural conformance."""

    process_type = "flow"
    solver_name = "partial"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: object) -> None:  # pragma: no cover - not exercised
        pass

    def cleanup(self, ctx: object) -> None:  # pragma: no cover
        pass


def test_dummy_adapter_is_recognised_as_solver_adapter() -> None:
    assert isinstance(DummyAdapter(), SolverAdapter)


def test_partial_adapter_fails_structural_check() -> None:
    assert not isinstance(PartialAdapter(), SolverAdapter)


def test_lifecycle_order_on_dummy_adapter() -> None:
    adapter = DummyAdapter()
    adapter.validate(ctx=None)
    adapter.execute(ctx=None)
    adapter.cleanup(ctx=None)

    assert adapter.calls == ["validate", "execute", "cleanup"]


def test_run_result_defaults() -> None:
    result = RunResult(converged=True)
    assert result.output_dir is None
    assert result.iterations is None
    assert result.residual is None
    assert result.diagnostics == {}


def test_run_result_accepts_output_dir(tmp_path: Path) -> None:
    result = RunResult(converged=True, output_dir=tmp_path)
    assert result.output_dir == tmp_path


def test_run_result_is_frozen() -> None:
    result = RunResult(converged=True)
    with pytest.raises(Exception):
        result.converged = False  # type: ignore[misc]


# Compatibility checks for solver contract imports.


def test_solver_contracts_module_reexports_base_symbols() -> None:
    assert ContractSolverAdapter is BaseSolverAdapter
    assert ContractSolverConfig is BaseSolverConfig


def test_solver_root_reexports_contract_symbols() -> None:
    assert solver_root.SolverAdapter is ContractSolverAdapter
    assert solver_root.SolverConfig is ContractSolverConfig


# The engine a run records must be the one it executed.
#
# An ``api`` run solves through ``libmf6``; recording the ``mf6`` executable
# instead makes the provenance sha256 and version describe a file the solve never
# opened. These checks pin the resolution and its two failure modes.


def _stub_engine_files(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    exe = tmp_path / "mf6"
    lib = tmp_path / "libmf6.so"
    exe.write_bytes(b"exe")
    lib.write_bytes(b"lib")
    monkeypatch.setattr(binaries, "ensure_solver_binary", lambda *_a, **_k: exe)
    monkeypatch.setattr(binaries, "ensure_solver_library", lambda *_a, **_k: lib)
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: "6.6.3")
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: "6.6.3")
    return exe, lib


def test_api_mode_resolves_the_shared_library(monkeypatch, tmp_path: Path) -> None:
    _, lib = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow6", execution_mode="api")

    assert engine is not None
    assert engine.kind == "library"
    assert engine.execution_mode == "api"
    assert engine.path == lib
    assert engine.version == "6.6.3"


def test_subprocess_mode_resolves_the_executable(monkeypatch, tmp_path: Path) -> None:
    exe, _ = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow6", execution_mode="subprocess")

    assert engine is not None
    assert engine.kind == "executable"
    assert engine.execution_mode == "subprocess"
    assert engine.path == exe


def test_api_mode_on_a_non_mf6_solver_falls_back_to_its_executable(
    monkeypatch, tmp_path: Path
) -> None:
    """Only MODFLOW 6 ships a shared library; NWT keeps its executable."""
    exe, _ = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow_nwt", execution_mode="api")

    assert engine is not None
    assert engine.kind == "executable"
    assert engine.execution_mode == "subprocess"
    assert engine.path == exe


def test_solver_without_a_bundled_binary_has_no_engine() -> None:
    assert binaries.resolve_solver_engine("boussinesq") is None
    assert binaries.resolve_solver_engine("gr4j", execution_mode="api") is None


def test_an_unresolvable_engine_never_raises(monkeypatch) -> None:
    """Provenance must never be the reason a run refuses to start."""

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("no binary here")

    monkeypatch.setattr(binaries, "ensure_solver_binary", boom)
    monkeypatch.setattr(binaries, "ensure_solver_library", boom)

    assert binaries.resolve_solver_engine("modflow6") is None
    assert binaries.resolve_solver_engine("modflow6", execution_mode="api") is None


# Every registered solver adapter must structurally conform to ``SolverAdapter``.
#
# The test is parametrized on :func:`registry.list_pairs` so it covers
# both eagerly-registered adapters and lazily-loaded built-ins. A new
# adapter that lands in ``_BUILTIN_PATHS`` without honoring the
# ``validate / execute / cleanup / extract_observables`` quartet
# would surface here immediately.


@pytest.mark.parametrize("pair", registry.list_pairs(), ids=lambda p: f"{p[0]}/{p[1]}")
def test_registered_adapter_conforms_to_protocol(pair: tuple[str, str]) -> None:
    adapter = registry.get_solver_adapter(*pair)
    assert isinstance(adapter, SolverAdapter)


@pytest.mark.parametrize("pair", registry.list_pairs(), ids=lambda p: f"{p[0]}/{p[1]}")
def test_registered_adapter_advertises_pair(pair: tuple[str, str]) -> None:
    cls = registry.get(*pair)
    process_type, solver_name = pair
    assert cls.process_type == process_type
    assert cls.solver_name == solver_name
    assert isinstance(cls.requires, tuple)


@pytest.mark.parametrize(
    "pair",
    [("flow", "modflow_nwt"), ("flow", "modflow6"), ("flow", "boussinesq")],
    ids=lambda p: f"{p[0]}/{p[1]}",
)
def test_flow_adapter_exposes_extract_observables(pair: tuple[str, str]) -> None:
    """The 3 flow backends must each expose ``extract_observables``."""
    adapter = registry.get_solver_adapter(*pair)
    method = getattr(adapter, "extract_observables", None)
    assert callable(method), f"{pair} must define extract_observables"
    sig = inspect.signature(method)
    assert "ctx" in sig.parameters
    assert "store" in sig.parameters
    assert "requests" in sig.parameters
    assert "time_index" in sig.parameters
    # The old per-variable signature must be gone, not shadowed by an alias.
    assert not hasattr(adapter, "extract_calibration_series")


# An adapter that cannot serve an observable refuses with one named exception.
#
# ``SolverAdapter.extract_observables`` promises that a caller never reads a
# signature to learn what a backend supports: it asks, and an unavailable
# observable comes back as :class:`ObservableNotAvailableError`. That promise only
# holds if every refusal path raises that one type. The config-dependent paths did
# not: whether a run built a DRAIN package, a LAK sidecar or a solver mesh decided
# between ``RuntimeError``, ``KeyError`` and ``FileNotFoundError``, so a caller had
# to catch three unrelated types and could not tell a refusal from a bug.

# Refusing to serve an observable is not a programming error, so these types
# must not appear on that path. ValueError stays legal: it guards arguments the
# caller built wrong, which is a bug and not a missing capability.
_WRONG_ON_A_REFUSAL_PATH = {"RuntimeError", "KeyError", "FileNotFoundError"}


_MODULES = (observable_extraction, calibration_extractors, lake_extractor)


def _raised_type_names(module: object) -> list[str]:
    source_file = getattr(module, "__file__", None)
    assert source_file is not None, f"{module!r} has no source file to read"
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        target = exc.func if isinstance(exc, ast.Call) else exc
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def test_the_refusal_is_a_solver_error() -> None:
    """The type a caller catches sits under the solver error family."""
    assert issubclass(ObservableNotAvailableError, SolverError)


def test_extraction_refuses_with_one_named_type() -> None:
    """No extraction module refuses through a bare built-in exception."""
    offenders = {
        getattr(module, "__name__", str(module)): sorted(
            set(_raised_type_names(module)) & _WRONG_ON_A_REFUSAL_PATH
        )
        for module in _MODULES
    }
    assert not {name: raised for name, raised in offenders.items() if raised}


# Guard tests for the supported MODFLOW solver variants.
#
# HydroModPy only wraps MODFLOW-NWT and MODFLOW 6. Older MODFLOW 2000/2005
# binaries and the MODFLOW-USG unstructured branch are explicitly out of scope:
# no adapter, no translator, no solver config exists for them. These tests make
# sure the ``flow_translator`` rejects these names fast, before the planner
# commits to a simulation that no solver can run.


@pytest.mark.parametrize(
    "solver_key",
    ["modflow_nwt", "nwt", "modflow6", "mf6"],
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
