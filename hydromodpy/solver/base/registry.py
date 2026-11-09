"""The two registries of the solver port: ``solvers`` for the adapters, ``extractors`` for their output readers.

Both are instances of :class:`~hydromodpy.core.plugin_registry.PluginRegistry`.
A backend is keyed on its ``process_type`` and ``name`` joined by ``_``
(``flow_modflow6``), and an extractor on its ``process_type`` and
``solver_name``, so each key finds the adapter that solves and the extractor
that reads it back. ``solvers.get("flow", "modflow6")`` returns the class,
``solvers.create(...)`` a fresh instance for one run, and ``solvers.names("flow")``
the flow solvers. An unknown key raises ``SolverInputError``.

The in-tree classes are declared in ``_BUILTIN_PATHS`` and
``_BUILTIN_EXTRACTOR_PATHS`` and imported on first lookup, so importing this
module pulls no backend. The two entry-point groups are the out-of-tree surface
only. An in-tree backend is never declared there too, because the name once
gave a backend a second key: ``flow_modflownwt`` minted ``flow/modflownwt`` beside
``flow/modflow_nwt``, with an adapter and no extractor.
"""

from __future__ import annotations

import inspect

from pandas.tseries.frequencies import to_offset
from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.solver.base.adapter_protocol import (
    CATEGORIES,
    GEOMETRIES,
    NULLABLE_ATTRIBUTES,
    extractor_members,
    solver_members,
)

ENTRY_POINT_GROUP = "hydromodpy.solver"
"""The out-of-tree adapters. One entry point per backend, named ``<process_type>_<name>``."""

EXTRACTOR_ENTRY_POINT_GROUP = "hydromodpy.solver.extractor"
"""The out-of-tree extractors. One entry point per backend, named like its adapter."""

DEFAULT_FLOW_SOLVER = "modflow6"
"""The flow backend a document or a factory reads when it names none.

One write, here: the default of ``solver.backend``, the ``solvers`` entry of
a flow process and the convenience builders of the simulation configuration
all read this constant. A backend that cannot be the two-sided default (a
transport, an extractor) has no entry here.
"""

_BUILTIN_PATHS: dict[str, str] = {
    "flow_modflow_nwt": "hydromodpy.solver.modflow_nwt.adapter:ModflowNwtFlowAdapter",
    "flow_modflow6": "hydromodpy.solver.modflow6.adapter:Modflow6FlowAdapter",
    "flow_boussinesq": "hydromodpy.solver.boussinesq.adapter:BoussinesqFlowAdapter",
    "flow_linear_reservoir": "hydromodpy.solver.linear_reservoir.adapter:LinearReservoirFlowAdapter",
    "transport_modpath": "hydromodpy.solver.modflow_nwt.modpath.modpath:ModpathTransportAdapter",
    "transport_mt3dms": "hydromodpy.solver.modflow_nwt.mt3dms.mt3dms:Mt3dmsTransportAdapter",
    "transport_modflow6": "hydromodpy.solver.modflow6.transport:Modflow6GwtTransportAdapter",
    "transport_modflow6_prt": "hydromodpy.solver.modflow6.prt:Modflow6PrtTransportAdapter",
}
"""Dotted ``"<module>:<class>"`` paths to the in-tree adapters, imported on first lookup."""

_BUILTIN_EXTRACTOR_PATHS: dict[str, str] = {
    "flow_modflow_nwt": "hydromodpy.solver.modflow_nwt.extractors.flow:ModflowNwtOutputAdapter",
    "flow_modflow6": "hydromodpy.solver.modflow6.extractors.flow:Modflow6OutputAdapter",
    "flow_boussinesq": "hydromodpy.solver.boussinesq.extractors.flow:BoussinesqOutputAdapter",
    "flow_linear_reservoir": "hydromodpy.solver.linear_reservoir.extractor:LinearReservoirExtractor",
    "transport_mt3dms": "hydromodpy.solver.modflow_nwt.extractors.mt3dms:Mt3dmsOutputAdapter",
    "transport_modflow6": "hydromodpy.solver.modflow6.extractors.transport:Modflow6GwtOutputAdapter",
    "transport_modflow6_prt": "hydromodpy.solver.modflow6.extractors.prt:Modflow6PrtOutputAdapter",
    "transport_modpath": "hydromodpy.solver.modflow_nwt.extractors.modpath:ModpathOutputAdapter",
}
"""Dotted paths to the in-tree extractors, under the same keys as the adapters."""

_MISSING = object()


def _check_backend(cls: type) -> None:
    """Refuse a backend whose attributes have the wrong type or leave their vocabulary.

    The member check of the registry has already refused an absent attribute.
    ``options`` and ``native_step`` may be ``None``, so their presence is
    checked here, on the class.
    """
    # Imported here, at the first registration, so importing the registry
    # stays as light as before: model.supports pulls the whole Model.
    from hydromodpy.model.supports import SUPPORTS

    label = getattr(cls, "__qualname__", cls)
    problems: list[str] = []
    for attribute in NULLABLE_ATTRIBUTES:
        if inspect.getattr_static(cls, attribute, _MISSING) is _MISSING:
            problems.append(f"{attribute} is not declared (None is allowed, absence is not)")

    def _strings(attribute: str, container: type) -> None:
        value = getattr(cls, attribute, None)
        if not isinstance(value, container) or not all(isinstance(item, str) for item in value):
            problems.append(f"{attribute} is {value!r}, a {container.__name__} of str")

    for attribute in ("accepted_meshes", "supports", "mutable"):
        _strings(attribute, frozenset)
    for attribute in ("writes", "reads"):
        _strings(attribute, tuple)
    geometry = getattr(cls, "geometry", None)
    if geometry not in GEOMETRIES:
        problems.append(f"geometry is {geometry!r}, one of {', '.join(GEOMETRIES)}")
    category = getattr(cls, "category", None)
    if category not in CATEGORIES:
        problems.append(f"category is {category!r}, one of {', '.join(CATEGORIES)}")
    supports = getattr(cls, "supports", None)
    if isinstance(supports, frozenset):
        unknown = sorted(str(item) for item in supports - SUPPORTS)
        if unknown:
            problems.append(
                f"supports names {', '.join(unknown)}, outside the traits of "
                "hydromodpy.model.supports.SUPPORTS"
            )
    requires = getattr(cls, "requires", None)
    if not isinstance(requires, tuple) or not all(
        isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(p, str) for p in pair)
        for pair in requires
    ):
        problems.append(f"requires is {requires!r}, a tuple of (process_type, name) pairs")
    options = getattr(cls, "options", None)
    if options is not None and not (isinstance(options, type) and issubclass(options, BaseModel)):
        problems.append(f"options is {options!r}, a Pydantic model class or None")
    native_step = getattr(cls, "native_step", None)
    if native_step is not None:
        try:
            to_offset(native_step)
        except (TypeError, ValueError):
            problems.append(f"native_step is {native_step!r}, a pandas frequency alias or None")
    if problems:
        raise TypeError(f"{label!r} declares a solver backend wrongly: {'; '.join(problems)}.")


solvers = PluginRegistry(
    kind="solver backend",
    id_attributes=("process_type", "name"),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=solver_members,
    error=SolverInputError,
    validate=_check_backend,
)
"""The solver adapters, keyed on ``<process_type>_<name>``."""

extractors = PluginRegistry(
    kind="output extractor",
    id_attributes=("process_type", "solver_name"),
    group=EXTRACTOR_ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_EXTRACTOR_PATHS,
    members=extractor_members,
    error=SolverInputError,
)
"""The output extractors, keyed like the adapter whose run they read."""


def backends_honoring(trait: str) -> tuple[str, ...]:
    """The flow backends of this installation that list *trait* in ``supports``.

    One write of the question "which ones can do it": a refusal, a message or
    an option card names the backends through this call instead of a written
    list, so a backend that joins or leaves a trait never leaves a sentence
    behind. In registry order, plugins included.
    """
    return tuple(
        name for name in solvers.names("flow") if trait in solvers.get("flow", name).supports
    )


__all__ = [
    "DEFAULT_FLOW_SOLVER",
    "ENTRY_POINT_GROUP",
    "EXTRACTOR_ENTRY_POINT_GROUP",
    "backends_honoring",
    "extractors",
    "solvers",
]
