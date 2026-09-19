"""The second door: a project TOML names the flow-routing engine.

``terrain-delineate`` already lets a ``request.json`` name one (D200). That door
serves an external caller. This one serves the caller that drives HydroModPy
from a project file, and it was deliberately held back until a second engine
was installable -- a selection point nothing can select through is decoration.

Four gates, and they answer different questions.

1. Behavioural, at the document: a project that names an engine this
   installation cannot serve is refused while the TOML is read, with the message
   that says what it does serve.
2. Behavioural, at the runtime object: the name survives the trip from the
   configuration to the object a solver is handed, because a solver reads it off
   that object and not off the configuration.
3. Behavioural, at both solver families: the routing context MODFLOW 6 and
   MODFLOW-NWT build over their own DEM is built with that engine.
4. Derived from the source: every site of ``hydromodpy/`` that calls a flow
   builder by name passes the engine on, and every wrapper that receives one
   through a parameter declares the engine and forwards it.

Gate 4 verifies that nothing on the way down drops the name. It does **not**
verify that something on the way in supplies one: ``hydromodpy/spatial/
site_selection/`` reaches the same two builders through a ``builder=`` parameter
and its callers supply no engine, because ``[site_selection]`` has no field that
names one. That is a third door and it does not exist yet -- see F10f.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.terrain import registry

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Anchored on this file. A tree scan that reads the cwd scans nothing from tests/."""

FLOW_BUILDERS = ("build_regional_flow_products", "extract_catchment_from_point")
"""The two functions that turn a configuration into a terrain engine."""

ROUTING_BUILDERS = ("build_solver_routing_context",)
"""The frame both solver families call instead of reaching a flow builder directly.

Named separately because leaving it out is exactly how the MODFLOW-NWT call site
stayed unplumbed while the gate was green.
"""

SCANNED_BUILDERS = FLOW_BUILDERS + ROUTING_BUILDERS

DIRECT_CALL_FLOOR = 8
"""Anti-vacuity control. A scan that reads nothing satisfies an empty assertion."""

WRAPPER_FLOOR = 3
"""Same, for the indirect form: three wrappers take a builder as a parameter."""


def _standard(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "source_mode": "standard",
        "catchment": {"catch_def": "dem", "dem_init_path": __file__},
    }
    payload.update(overrides)
    return payload


def _an_installed_engine() -> str:
    return registry.builtin_engine_ids()[0]


# --- Gate 1: the document ---------------------------------------------------


def test_a_project_can_name_an_engine_this_installation_serves() -> None:
    engine_id = _an_installed_engine()

    config = GeographicConfig.model_validate(_standard(terrain_engine=engine_id))

    assert config.terrain_engine == engine_id


def test_a_project_that_names_no_engine_carries_none_and_not_a_default() -> None:
    """The default lives in the registry, so the document does not copy it.

    A configuration that wrote the default down would freeze it: the day the
    build changes which engine it defaults to, every project file still naming
    the old one would keep it, silently.
    """
    assert GeographicConfig.model_validate(_standard()).terrain_engine is None


def test_a_project_naming_an_engine_nobody_installed_is_refused_while_reading() -> None:
    """Refused at the document, not at the first delineation.

    A DEM is conditioned before anything routes, and finding out afterwards that
    the engine does not exist costs that conditioning for nothing.
    """
    with pytest.raises(ValidationError) as raised:
        GeographicConfig.model_validate(_standard(terrain_engine="no-such-engine"))

    message = str(raised.value)
    assert "geographic.terrain_engine" in message
    assert registry.ENTRY_POINT_GROUP in message
    for engine_id in registry.builtin_engine_ids():
        assert engine_id in message


# --- Gate 2: the runtime object a solver is handed --------------------------


@pytest.fixture
def delineation(monkeypatch, tmp_path) -> CatchmentDelineation:
    """A runtime geographic object without the delineation behind it.

    ``processing()`` is the whole pipeline and needs a real DEM; what is under
    test is the attribute surface the solver reads, which is written before it
    runs.
    """
    monkeypatch.setattr(CatchmentDelineation, "processing", lambda self: None)
    config = GeographicConfig.model_validate(_standard(terrain_engine=_an_installed_engine()))
    return CatchmentDelineation(config, SimpleNamespace(project_root=str(tmp_path)))


def test_the_runtime_geographic_object_carries_the_engine_the_document_named(
    delineation,
) -> None:
    """The configuration is not what a solver reads.

    A solver receives ``state.setup.geographic``, the runtime object, and reads
    its members by name. The object copies an explicit list of configuration
    attributes onto itself; an engine missing from that list is an engine the
    solver silently replaces with the build default.
    """
    assert delineation.terrain_engine == _an_installed_engine()


# --- Gate 3: both solver families -------------------------------------------


def _fake_routing_builder(captured: dict):
    def build(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    return build


def test_the_mf6_solver_routing_context_is_built_with_the_configured_engine(
    monkeypatch, tmp_path, delineation
) -> None:
    from hydromodpy.solver.modflow6 import build as mf6_build

    captured: dict = {}
    monkeypatch.setattr(mf6_build, "build_solver_routing_context", _fake_routing_builder(captured))
    model = SimpleNamespace(
        routing_ctx=None,
        grid_ctx=SimpleNamespace(),
        dem_watershed_path=str(tmp_path / "dem.tif"),
        full_path=str(tmp_path),
        geographic=delineation,
    )

    mf6_build.ensure_solver_routing_context(model)

    assert captured["engine_id"] == _an_installed_engine()


def test_the_nwt_solver_routing_context_is_built_with_the_configured_engine(
    monkeypatch, tmp_path, delineation
) -> None:
    """The second solver family, because it carries its own copy of the call.

    MODFLOW-NWT does not share ``ensure_solver_routing_context`` with MODFLOW 6;
    it has its own method around the same builder, and plumbing only one of the
    two leaves half the runs routing with the build default.
    """
    from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

    captured: dict = {}
    monkeypatch.setattr(nwt_solver, "build_solver_routing_context", _fake_routing_builder(captured))
    solver = SimpleNamespace(
        routing_ctx=None,
        grid_ctx=SimpleNamespace(),
        dem_watershed_path=str(tmp_path / "dem.tif"),
        full_path=str(tmp_path),
        geographic=delineation,
    )

    nwt_solver.ModflowNwt._ensure_solver_routing_context(solver)

    assert captured["engine_id"] == _an_installed_engine()


# --- Gate 4: derived from the source ----------------------------------------


def _python_files() -> list[Path]:
    return sorted((REPO_ROOT / "hydromodpy").rglob("*.py"))


def _named_here(node: ast.expr | None) -> str | None:
    """The builder a default expression names, through ``x or literal`` too."""
    if isinstance(node, ast.Name) and node.id in FLOW_BUILDERS:
        return node.id
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            found = _named_here(value)
            if found is not None:
                return found
    return None


def _direct_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in SCANNED_BUILDERS
    ]


def test_every_site_that_calls_a_builder_by_name_passes_the_engine_on() -> None:
    """Derived from the source, so a new call site cannot quietly skip it.

    The count floor is the anti-vacuity control: a scan that finds no call site
    would satisfy the assertion below over an empty set, and that is the hollow
    green this campaign has now paid for twice.
    """
    without: list[str] = []
    sites = 0
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _direct_calls(tree):
            sites += 1
            if not any(keyword.arg == "engine_id" for keyword in call.keywords):
                without.append(f"{path.relative_to(REPO_ROOT)}:{call.lineno}")

    assert sites >= DIRECT_CALL_FLOOR, f"found {sites} call sites, the scan read the wrong tree"
    assert without == []


def _builder_parameters(function: ast.FunctionDef) -> list[str]:
    """Parameters whose default is one of the two flow builders."""
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    pairs: list[tuple[ast.arg, ast.expr | None]] = list(
        zip(positional[len(positional) - len(arguments.defaults) :], arguments.defaults)
    )
    pairs += list(zip(arguments.kwonlyargs, arguments.kw_defaults))
    return [arg.arg for arg, default in pairs if _named_here(default) is not None]


def _declared_names(function: ast.FunctionDef) -> set[str]:
    arguments = function.args
    return {arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}


def test_every_wrapper_that_receives_a_builder_declares_the_engine_and_forwards_it() -> None:
    """The indirection the direct scan cannot see.

    ``build_site_selection_flow_products`` and the two delineation helpers never
    write a builder's name at their call: they take it as a parameter and call
    that. A wrapper that cannot pass the engine on is a wrapper through which no
    engine can be substituted, and the direct scan above is blind to it.
    """
    faulty: list[str] = []
    wrappers = 0
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            parameters = _builder_parameters(function)
            if not parameters:
                continue
            wrappers += 1
            where = f"{path.relative_to(REPO_ROOT)}:{function.lineno} {function.name}"
            if "engine_id" not in _declared_names(function):
                faulty.append(f"{where} declares no engine_id")
                continue
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                through_parameter = isinstance(call.func, ast.Name) and call.func.id in parameters
                forwards_parameter = any(
                    isinstance(keyword.value, ast.Name) and keyword.value.id in parameters
                    for keyword in call.keywords
                )
                if not (through_parameter or forwards_parameter):
                    continue
                if not any(keyword.arg == "engine_id" for keyword in call.keywords):
                    faulty.append(f"{where} calls line {call.lineno} without engine_id")

    assert wrappers >= WRAPPER_FLOOR, f"found {wrappers} wrappers, the scan read the wrong tree"
    assert faulty == []
