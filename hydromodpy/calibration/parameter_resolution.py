"""What a calibration parameter means, resolved from the name it was given.

A file used to reach a parameter by its address in the configuration tree,
``path = "flow.param.K.field.value"``. That address is the one line of a
calibration that talks about the Pydantic tree instead of about the aquifer:
renaming a field there expires every file that names it, and nothing in it says
that a conductivity is searched in log space.

The catalogue already walks the resolved configuration and knows, for every
value a search could move, the entries it belongs to and what its field
declares about being searched. So a file names the quantity and the resolution
happens here: ``[calibration.parameters.K]`` finds the one target named ``K``
and writes its path into the declaration.

Three rules, and neither of them authorises anything. The catalogue decides
what exists, as it already did. The annotation only fills in what the file left
unsaid, and says which leaf is the value of its entry so that ``K`` does not
have to be written ``K.value``. And ``path``, when a file writes one, decides
the address on its own: it stays the way out for anything the walk does not
reach. It does not opt out of the rest, though, or the same quantity would be
searched in two different spaces depending on how it was spelled.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.calibration.targets import (
    CalibrationTarget,
    calibration_targets,
    targets_by_name,
    targets_by_path,
)
from hydromodpy.core.exceptions import ConfigError

__all__ = [
    "UnresolvedParameterName",
    "parameters_awaiting_resolution",
    "resolve_parameter_targets",
    "unresolved_parameter_names",
]


class UnresolvedParameterName(ConfigError):
    """A parameter names a quantity this project does not carry, or two of them.

    Typed apart from every other configuration failure because the callers that
    tolerate one do not tolerate this one: a loader may forgive a project whose
    data is absent from the machine, and never a file that names something the
    model does not have.
    """


def parameters_awaiting_resolution(calibration: Any) -> list[str]:
    """Return the parameters that named a quantity instead of a path."""
    parameters = getattr(calibration, "parameters", None) or {}
    return [name for name, decl in parameters.items() if not decl.resolve_target()]


def unresolved_parameter_names(calibration: Any, project_config: Any) -> dict[str, str]:
    """Return, per parameter, why its name reaches nothing. Empty when all resolve.

    The same lookup as :func:`resolve_parameter_targets`, asked to report rather
    than to stop. The preflight exists so a file with three mistakes comes back
    with three findings, and a name it cannot resolve has to be one of the three
    instead of the reason the other two were never looked for.
    """
    parameters = getattr(calibration, "parameters", None) or {}
    pending = [(name, decl) for name, decl in parameters.items() if not decl.resolve_target()]
    if not pending:
        return {}
    catalogue = calibration_targets(project_config)
    by_name = targets_by_name(catalogue)
    refused: dict[str, str] = {}
    for name, _decl in pending:
        try:
            _target_for(name, by_name, catalogue)
        except UnresolvedParameterName as exc:
            refused[name] = str(exc)
    return refused


def resolve_parameter_targets(
    calibration: Any, project_config: Any, *, strict: bool = True
) -> None:
    """Fill in, from the catalogue, what each parameter did not say.

    Every parameter is completed from the target it points at, whether it got
    there by name or by writing its own path. Two spellings of the same
    quantity have to search the same space: a ``K`` that names itself and a
    ``K`` that writes ``flow.param.K.field.value`` both inherit the log space
    the field declares, and a file that states a transform still beats it.

    Mutates the declarations in place and re-reads nothing it already wrote, so
    running twice changes nothing. That is what lets both loaders call it
    without either having to know whether the other did.

    ``strict`` decides what an unresolvable name does. A run refuses it, because
    it would search nothing. Loading the configuration does not, because the
    preflight is the thing that reports every fault of a file at once, and it
    needs the file to have loaded.
    """
    parameters = getattr(calibration, "parameters", None) or {}
    if not parameters:
        return
    catalogue = calibration_targets(project_config)
    by_name = targets_by_name(catalogue)
    by_path = targets_by_path(catalogue)
    for name, decl in parameters.items():
        path = decl.resolve_target()
        if path is None:
            try:
                target = _target_for(name, by_name, catalogue)
            except UnresolvedParameterName:
                if strict:
                    raise
                # Left as declared, so the preflight can report this beside
                # whatever else is wrong with the file rather than instead of it.
                continue
            decl.path = target.path
        else:
            _refuse_a_name_that_contradicts_its_path(name, path, by_name)
            target = by_path.get(path)
            if target is None:
                # A path the catalogue does not carry is the documented way out,
                # and the space and the preflight judge it on their own terms.
                continue
        _fill_what_the_file_left_unsaid(decl, target)
        _refuse_bounds_the_registry_rules_out(name, decl, target)


def _refuse_a_name_that_contradicts_its_path(
    name: str,
    path: str,
    by_name: dict[str, CalibrationTarget],
) -> None:
    """Refuse a section whose name and whose path designate two quantities.

    Since the name is an address of its own, a file that writes both says the
    same thing twice and may say it differently. Nothing downstream would
    notice: the path wins, the search moves one quantity and the report labels
    it with the name of another. A name the catalogue does not carry is not a
    contradiction, only a label, and that is what a file states when it wants
    its own vocabulary.
    """
    named = by_name.get(name)
    if named is None or named.path == path:
        return
    raise UnresolvedParameterName(
        f"[calibration.parameters.{name}] says two different things: the name "
        f"{name!r} is {named.path!r} in this project, and the section writes "
        f"path = {path!r}. The search would move the second and the report would "
        f"call it the first. Drop the path to calibrate {name!r}, or rename the "
        "section after what the path points at."
    )


def _target_for(
    name: str,
    index: dict[str, CalibrationTarget],
    catalogue: list[CalibrationTarget],
) -> CalibrationTarget:
    """Return the one target ``name`` designates, or refuse by naming why."""
    exact = index.get(name)
    if exact is not None:
        return exact
    ending = [target for target in catalogue if target.name.endswith(f".{name}")]
    if len(ending) == 1:
        return ending[0]
    if len(ending) > 1:
        spellings = ", ".join(repr(target.name) for target in ending)
        raise UnresolvedParameterName(
            f"[calibration.parameters.{name}] names a quantity this project carries "
            f"several times: {spellings}. Write one of those, or a path, rather than "
            "have the choice made here."
        )
    known = ", ".join(repr(target.name) for target in catalogue) or "nothing"
    raise UnresolvedParameterName(
        f"[calibration.parameters.{name}] names nothing this project carries. It "
        f"holds {known}. `hmp config targets` prints them with their current value, "
        "and 'path' still reaches anything the catalogue does not."
    )


def _refuse_bounds_the_registry_rules_out(name: str, decl: Any, target: CalibrationTarget) -> None:
    """Face the declared bounds with the range the catalogue read for this target.

    The guard in :mod:`hydromodpy.calibration.optim.parameters` asks the physical
    registry under the name the file gave the parameter, which is all a bare name
    can do. Here the target is known, so the question is asked under the key the
    catalogue itself used, and a zone of a heterogeneous field is faced with the
    ceiling of the property it is a zone of: ``Sy.zone_1`` is a specific yield and
    0.9 is not one, whatever the section is called.
    """
    bounds = list(getattr(decl, "bounds", ()) or ())
    if len(bounds) != 2 or target.registry_id is None:
        return
    from hydromodpy.spatial.field.core.physical_bounds import (
        PhysicalBoundsError,
        validate_physical_value,
    )

    for edge, value in (("lower", bounds[0]), ("upper", bounds[1])):
        try:
            validate_physical_value(
                param_id=target.registry_id, value=float(value), unit=decl.units
            )
        except PhysicalBoundsError as exc:
            raise ConfigError(
                f"[calibration.parameters.{name}] {edge} bound {value!r} is outside what "
                f"{target.name!r} can physically be: {exc}"
            ) from None


def _fill_what_the_file_left_unsaid(decl: Any, target: CalibrationTarget) -> None:
    """Complete a declaration from its target, never overriding what it states.

    ``model_fields_set`` is what makes this safe: a declaration carries
    ``transform = "identity"`` as a default whether or not the file wrote it, so
    only the set of fields the file actually declared can say who wins.
    """
    written = decl.model_fields_set
    annotation = target.calibrable
    if annotation is not None:
        if "transform" not in written:
            decl.transform = annotation.transform
        if "prior" not in written:
            decl.prior = annotation.prior
        if decl.bounds is None and annotation.bounds is not None:
            decl.bounds = list(annotation.bounds)
    if "units" not in written and target.units:
        decl.units = target.units
