"""When the runner solves a model again from a solved run instead of building it.

A calibration trial changes a few properties of one ``Model`` between two
solves, by its profiles (``Model.with_profiles``) or by values per cell
(``Model.with_properties``). A backend whose ``mutable`` names those properties can rewrite only the
input files they touch, which is ``rerun``. ``changed_properties`` says what
differs between two models, and ``chooses_rerun`` is the rule the runner
applies before it calls ``rerun``. The backend still refuses, by returning
``None``, what only it can see, such as a steady start that depends on K.

The calibration is the only caller of ``rerun``. Its trials that change ``K`` or ``Sy``
alone go through it, one lane per trial in flight, and the result is the same to the bit
as a build. ``rerun`` returns ``None`` when the simulation of the earlier run already
carries a model of another process, so it never replays a transport. It consumes the
earlier run, so only the returned ``SolverRun`` serves as a parent. ``hmp catalog
rerun`` replays a sealed run from its configuration, and the two share only the word.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Any

import numpy as np

from hydromodpy.solver.base.adapter_protocol import RERUN_MEMBERS
from hydromodpy.solver.base.plan import SolverRun

_COMPARED_APART = frozenset({"properties", "boundaries"})


def _same(left: Any, right: Any) -> bool:
    """Whether two members hold the same objects.

    A mapping holds the same keys and, under each key, the same object. A tuple
    holds the same objects in the same order. Anything else is the same object.
    ``Model`` rebuilds its read-only mappings on every ``dataclasses.replace``
    without copying their values, so a model made by ``with_properties`` keeps
    the values and loses the identity of the mappings.
    """
    if left is right:
        return True
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(left[key] is right[key] for key in left)
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(a is b for a, b in zip(left, right, strict=True))
    return False


def _changed_overrides(left: Mapping[str, Any], right: Mapping[str, Any]) -> frozenset[str]:
    """The override names whose values differ, a name set on one side only included."""
    changed = set(left.keys() ^ right.keys())
    for name in left.keys() & right.keys():
        if left[name] is not right[name] and not np.array_equal(
            np.asarray(left[name]), np.asarray(right[name])
        ):
            changed.add(name)
    return frozenset(changed)


def changed_properties(previous: Any, model: Any) -> frozenset[str] | None:
    """Return the property names whose profile or per-cell overrides differ between two models.

    A profile differs when its ``[flow.param]`` id holds another object, as
    ``Model.with_profiles`` replaces it, and the name is that id. An override
    name is a key of ``Model.properties.overrides``, as ``Model.with_properties``
    was given it, and its values are compared with ``numpy.array_equal``. The
    answer is ``None`` as soon as any other member differs: the set of profile
    ids, a boundary condition, the recharge, the wells, the time, the initial
    state, the geometry or the options. A member is the same when it holds the
    same objects, so two models built apart from the same files differ in every
    profile. That is the safe side, because a backend reruns only the names its
    ``mutable`` holds and builds otherwise.
    """
    if previous is None or model is None or type(previous) is not type(model):
        return None
    for member in fields(model):
        if member.name in _COMPARED_APART:
            continue
        if not _same(getattr(previous, member.name), getattr(model, member.name)):
            return None
    left, right = previous.boundaries, model.boundaries
    if not (_same(left.conditions, right.conditions) and _same(left.active_ids, right.active_ids)):
        return None
    profiles, others = previous.properties.profiles, model.properties.profiles
    if profiles.keys() != others.keys():
        return None
    replaced = frozenset(name for name in profiles if profiles[name] is not others[name])
    return replaced | _changed_overrides(previous.properties.overrides, model.properties.overrides)


def chooses_rerun(adapter: object, previous: SolverRun | None, model: Any) -> bool:
    """Whether the runner asks ``adapter`` to rerun ``previous`` for ``model``.

    It does when a solved run is given, the backend carries ``rerun`` and
    declares a non-empty ``mutable``, and the two models differ only by
    properties ``mutable`` names. No difference at all also reruns, which
    rewrites nothing. The backend checks the rest and may still decline.
    """
    if previous is None:
        return False
    mutable = frozenset(getattr(type(adapter), "mutable", frozenset()))
    if not mutable or not all(callable(getattr(adapter, name, None)) for name in RERUN_MEMBERS):
        return False
    changed = changed_properties(previous.model, model)
    return changed is not None and changed <= mutable


__all__ = ["changed_properties", "chooses_rerun"]
