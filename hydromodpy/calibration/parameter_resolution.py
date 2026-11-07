"""What a calibration parameter means, resolved from the name it was given.

A file used to reach a parameter by its address in the configuration tree,
``path = "flow.param.K.field.value"``. That address is the one line of a
calibration that talks about the Pydantic tree instead of about the aquifer:
renaming a field there expires every file that names it, and nothing in it says
that a conductivity is searched in log space.

The catalog already walks the resolved configuration and knows, for every
value a search could move, the entries it belongs to and what its field
declares about being searched. So a file names the quantity and the resolution
happens here: ``[calibration.parameters.K]`` finds the one target named ``K``
and writes its path into the declaration.

Three rules, and neither of them authorizes anything. The catalog decides
what exists, as it already did. The annotation only fills in what the file left
unsaid, and says which leaf is the value of its entry so that ``K`` does not
have to be written ``K.value``. And ``path``, when a file writes one, decides
the address on its own: it stays the way out for anything the walk does not
reach. It does not opt out of the rest, though, or the same quantity would be
searched in two different spaces depending on how it was spelled.
"""

from __future__ import annotations

import warnings
from typing import Any

from hydromodpy.calibration.targets import (
    CalibrationTarget,
    calibration_targets,
    declared_calibrable,
    targets_by_name,
    targets_by_path,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.model.soil.config import soil_reservoir_of

__all__ = [
    "RECHARGE_FACTOR_PATH",
    "RECHARGE_VALUES_PATH",
    "UnresolvedParameterName",
    "replaced_recharge_rate",
    "resolve_parameter_targets",
    "unresolved_parameter_names",
]

RECHARGE_VALUES_PATH = "flow.sinks_sources.recharge.values"
RECHARGE_FACTOR_PATH = "flow.sinks_sources.recharge.factor"


class UnresolvedParameterName(ConfigError):
    """A parameter names a quantity this project does not carry, or two of them.

    Typed apart from every other configuration failure because the callers that
    tolerate one do not tolerate this one: a loader may forgive a project whose
    data is absent from the machine, and never a file that names something the
    model does not have.
    """


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
            _target_for(name, by_name, catalogue, project_config)
        except UnresolvedParameterName as exc:
            refused[name] = str(exc)
    return refused


def resolve_parameter_targets(
    calibration: Any, project_config: Any, *, strict: bool = True
) -> None:
    """Fill in, from the catalog, what each parameter did not say.

    Every parameter is completed from the target it points at, whether it got
    there by name or by writing its own path. Two spellings of the same
    quantity have to search the same space: a ``K`` that names itself and a
    ``K`` that writes ``flow.param.K.field.value`` both inherit the log space
    the field declares, and a file that states a search space still beats it.

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
    named_at: dict[tuple[str, str | None], str] = {}
    phases = list(getattr(calibration, "phases", None) or ())
    for name, decl in parameters.items():
        # Two names on one path only clash in a search that moves both.
        searched_in = {phase.name for phase in phases if name in phase.parameters} or {None}
        path = decl.resolve_target()
        if path is None:
            try:
                target = _target_for(name, by_name, catalogue, project_config)
            except UnresolvedParameterName:
                if strict:
                    raise
                # Left as declared, so the preflight can report this beside
                # whatever else is wrong with the file rather than instead of it.
                continue
            decl.path = target.path
            _refuse_a_path_named_twice(name, decl.path, searched_in, named_at)
        else:
            _refuse_a_path_named_twice(name, path, searched_in, named_at)
            _refuse_a_name_that_contradicts_its_path(name, path, by_name)
            target = by_path.get(path)
            if target is None:
                _refuse_a_depth_model_path_the_catalogue_does_not_carry(name, path, project_config)
                # A path the catalog does not carry is the documented way out,
                # and the space and the preflight judge it on their own terms.
                if decl.mode == "replace":
                    warnings.warn(
                        f"[calibration.parameters.{name}] writes {path!r}, which the catalogue "
                        "does not carry, so its unit is unknown and the sample is written as drawn.",
                        UserWarning,
                        stacklevel=2,
                    )
                continue
        if decl.mode == "scale" and not target.current:
            raise ConfigError(
                f"[calibration.parameters.{name}] scales {target.path!r}, which holds "
                f"{target.current!r}, so every factor gives the same value. Use "
                'mode = "replace", or give the value a base first.'
            )
        _refuse_a_replaced_recharge_rate(name, target, project_config)
        _convert_bounds_into_the_unit_of_the_target(name, decl, target)
        _fill_what_the_file_left_unsaid(decl, target)
        _refuse_bounds_the_registry_rules_out(name, decl, target)


def _refuse_a_path_named_twice(
    name: str,
    path: str,
    searched_in: set[str | None],
    named_at: dict[tuple[str, str | None], str],
) -> None:
    """Refuse two parameters of one search that move one value, because the later write wins."""
    for phase in searched_in:
        if (path, phase) in named_at:
            raise ConfigError(
                f"[calibration.parameters.{name}] and "
                f"[calibration.parameters.{named_at[path, phase]}] "
                f"both move {path!r}, and the second write would hide the first. Keep one."
            )
        named_at[path, phase] = name


def _refuse_a_name_that_contradicts_its_path(
    name: str,
    path: str,
    by_name: dict[str, CalibrationTarget],
) -> None:
    """Refuse a section whose name and whose path designate two quantities.

    Since the name is an address of its own, a file that writes both says the
    same thing twice and may say it differently. Nothing downstream would
    notice: the path wins, the search moves one quantity and the report labels
    it with the name of another. A name the catalog does not carry is not a
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


def replaced_recharge_rate(project_config: Any) -> str | None:
    """Say what replaces ``flow.sinks_sources.recharge.values`` in this project, or None.

    ``[flow.sinks_sources.recharge.soil]`` computes the recharge itself, and
    ``FlowRechargeConfig`` forbids writing ``values`` beside it (R11). A series
    loaded from ``[data.recharge]`` takes its place in the same way. A search
    that still moves ``values`` would change a rate the solver never reads.
    """
    if soil_reservoir_of(getattr(project_config, "flow", None)) is not None:
        return (
            "the soil reservoir replaces: the search would change nothing. "
            "Calibrate ru instead, with [calibration.parameters.ru] and its bounds in mm."
        )
    data = getattr(project_config, "data", None)
    if "recharge" in set(getattr(data, "types", []) or []):
        return (
            "the series [data.recharge] loads replaces: the search would change nothing. "
            'Remove "recharge" from data.types to calibrate one rate.'
        )
    return None


def _refuse_a_replaced_recharge_rate(
    name: str, target: CalibrationTarget, project_config: Any
) -> None:
    """Refuse calibrating a recharge rate the run replaces."""
    if target.path != RECHARGE_VALUES_PATH:
        return
    replaced_by = replaced_recharge_rate(project_config)
    if replaced_by is not None:
        raise ConfigError(
            f"[calibration.parameters.{name}] moves flow.sinks_sources.recharge.values, "
            f"which {replaced_by}"
        )


def _target_for(
    name: str,
    index: dict[str, CalibrationTarget],
    catalogue: list[CalibrationTarget],
    project_config: Any,
) -> CalibrationTarget:
    """Return the one target ``name`` designates, or refuse by naming why."""
    exact = index.get(name)
    if exact is not None:
        return exact
    if name.startswith("depth_model."):
        # The long spelling of a depth-model target, which is what a file
        # writes when it wants the section in the name.
        spelled = [target for target in catalogue if target.path == f"domain.{name}"]
        if spelled:
            return spelled[0]
    if _names_a_depth_model_field(name):
        # The generic refusal below would list what the project carries and
        # leave the reader wondering why the thickness is not among them.
        why = _why_the_depth_model_is_not_searchable(project_config)
        if why is not None:
            raise UnresolvedParameterName(f"[calibration.parameters.{name}] {why}")
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


_DEPTH_MODEL = "domain.depth_model"


def _depth_model_kinds() -> dict[str, tuple[str, ...]]:
    """Return, per depth-model kind, its fields and which of them are searchable.

    Read off the schema rather than typed here: the fields a kind declares
    calibrable are the ones the catalog lists, and a message that named
    another list would drift from it.
    """
    from hydromodpy.model.domain.depth_model_config import (
        ConstantThicknessDepthModel,
        FlatSubstratumDepthModel,
        RasterSubstratumDepthModel,
        RasterThicknessDepthModel,
    )

    kinds: dict[str, tuple[str, ...]] = {}
    for model in (
        ConstantThicknessDepthModel,
        FlatSubstratumDepthModel,
        RasterSubstratumDepthModel,
        RasterThicknessDepthModel,
    ):
        kind = str(model.model_fields["kind"].default)
        kinds[kind] = tuple(
            field_name
            for field_name, info in model.model_fields.items()
            if declared_calibrable(info) is not None
        )
    return kinds


def _names_a_depth_model_field(name: str) -> bool:
    """Return whether ``name`` spells a depth-model field, bare or under its section."""
    from hydromodpy.model.domain.depth_model_config import (
        ConstantThicknessDepthModel,
        FlatSubstratumDepthModel,
        RasterSubstratumDepthModel,
        RasterThicknessDepthModel,
    )

    leaf = name.removeprefix("depth_model.")
    if leaf == "kind":
        return True
    return any(
        leaf in model.model_fields
        for model in (
            ConstantThicknessDepthModel,
            FlatSubstratumDepthModel,
            RasterSubstratumDepthModel,
            RasterThicknessDepthModel,
        )
    )


def _why_the_depth_model_is_not_searchable(project_config: Any) -> str | None:
    """Say why the active depth model does not offer what was asked, or None.

    Only ``constant_thickness`` and ``flat_substratum`` hold their geometry in one
    number, and only that number is searchable. A raster depth model is a map of
    the site: a scalar written into it would shift or scale the whole map, which
    is not the question its raster answers, so none of its fields is declared
    calibrable.
    """
    domain = getattr(project_config, "domain", None)
    depth_model = getattr(domain, "depth_model", None)
    kind = getattr(depth_model, "kind", None)
    if kind is None:
        return None
    kinds = _depth_model_kinds()
    exposed = kinds.get(str(kind), ())
    offered = (
        f"which exposes {', '.join(repr(field) for field in exposed)} and nothing else"
        if exposed
        else "which exposes nothing to a search"
    )
    searchable = ", ".join(
        f"{fields[0]!r} under kind = {name!r}" for name, fields in kinds.items() if fields
    )
    return (
        f"reaches the depth model, and this project declares [domain.depth_model] "
        f"kind = {kind!r}, {offered}. The geometry is searched as one number: "
        f"{searchable}. A raster depth model is a map of the site and is not "
        "searched; compare one run per raster instead."
    )


def _refuse_a_depth_model_path_the_catalogue_does_not_carry(
    name: str, path: str, project_config: Any
) -> None:
    """Refuse a path into the depth model that the active kind does not expose.

    Anything else a path reaches outside the catalog is the documented way
    out. The depth model is not: its tag decides which field exists, and a
    path to the thickness of a flat substratum, or to the offset of a raster,
    either fails at the first trial or moves a map the search cannot describe.
    Refusing at load says so before a single solve.
    """
    if path != _DEPTH_MODEL and not path.startswith(f"{_DEPTH_MODEL}."):
        return
    why = _why_the_depth_model_is_not_searchable(project_config)
    if why is None:
        return
    raise UnresolvedParameterName(f"[calibration.parameters.{name}] path = {path!r} {why}")


def _convert_bounds_into_the_unit_of_the_target(
    name: str, decl: Any, target: CalibrationTarget
) -> None:
    """Rewrite bounds written in another unit into the unit the target is read in.

    The sampled value is written as it is into the field, which reads it in its
    own unit. Bounds in ``m/s`` on a conductivity the project declares in
    ``m/day`` are multiplied by 86 400 here, so the search draws in ``m/day``
    and the journal says ``m/day``. A unit of another dimension is refused.

    The bounds of ``mode = "scale"`` are factors and carry no unit, so a unit
    written there is refused. Restating the unit of the target is accepted,
    because that is what a configuration sealed after this step holds.

    Runs before the field fills in what the file left unsaid, so only bounds
    the file wrote are converted. Once converted the declaration holds the unit
    of the target, which makes a second pass change nothing.
    """
    if "units" not in decl.model_fields_set or not decl.units:
        return
    written = str(decl.units).strip()
    read = str(target.units).strip() if target.units else None
    if written == read:
        return
    if getattr(decl, "mode", "replace") == "scale":
        raise ConfigError(
            f"[calibration.parameters.{name}] writes units = {written!r} with "
            'mode = "scale". Its bounds are factors applied to the value the project '
            "holds, and a factor has no unit: drop 'units'."
        )
    if read is None:
        return
    from hydromodpy.core.units.parse import convert_between_units

    bounds = decl.bounds if "bounds" in decl.model_fields_set else None
    try:
        converted = [
            convert_between_units(float(bound), from_unit=written, to_unit=read)
            for bound in bounds or ()
        ]
        # A unit that cannot be read must still be refused when no bound is written.
        convert_between_units(1.0, from_unit=written, to_unit=read)
    except ValueError as exc:
        raise ConfigError(
            f"[calibration.parameters.{name}] writes its bounds in {written!r}, and "
            f"{target.name!r} is read in {read!r}: {exc} Write the bounds in {read!r}, "
            "or in a unit of the same quantity."
        ) from None
    if bounds is not None:
        decl.bounds = converted
    decl.units = read


def _refuse_bounds_the_registry_rules_out(name: str, decl: Any, target: CalibrationTarget) -> None:
    """Face the declared bounds with the range the catalog read for this target.

    The guard in :mod:`hydromodpy.calibration.optim.parameters` asks the physical
    registry under the name the file gave the parameter, which is all a bare name
    can do. Here the target is known, so the question is asked under the key the
    catalog itself used, and a zone of a heterogeneous field is faced with the
    ceiling of the property it is a zone of: ``Sy.zone_1`` is a specific yield and
    0.9 is not one, whatever the section is called.

    The bounds of ``mode = "scale"`` are factors, not values of the property,
    and are left alone: the product is faced with the registry when written.
    """
    bounds = list(getattr(decl, "bounds", ()) or ())
    if len(bounds) != 2 or target.registry_id is None:
        return
    if getattr(decl, "mode", "replace") == "scale":
        return
    from hydromodpy.core.units.physical_bounds import PhysicalBoundsError, validate_physical_value

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
    ``search_space = "identity"`` as a default whether or not the file wrote it, so
    only the set of fields the file actually declared can say who wins.
    """
    written = decl.model_fields_set
    annotation = target.calibrable
    if annotation is not None:
        if "search_space" not in written:
            decl.search_space = annotation.search_space
        if "sampling" not in written:
            decl.sampling = annotation.sampling
        if decl.bounds is None and annotation.bounds is not None:
            decl.bounds = list(annotation.bounds)
    if "units" not in written and target.units:
        decl.units = target.units
