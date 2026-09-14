"""One statement of precision, whatever engine walks the search.

Nine engines stop for nine different reasons and name the rule nine different
ways: a relative bracket width for the root search, ``xatol`` in the transformed
variable for the simplex, a spread of population energies for differential
evolution. Asking a hydrogeologist which of those they meant is asking the wrong
person: what they know is how precisely they need the conductivity, and that
sentence has to survive a change of engine.

So the file states the precision once, on the parameter, and each engine declares
in its traits which of its own options that writes and in which units. An engine
whose stopping rule is a budget and not a precision declares nothing, and a
precision handed to it is refused rather than dropped: silently ignoring it would
report a search that honoured a request it never read.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from hydromodpy.calibration.optim.optimizer import engine_traits

TOLERANCE_FIELD = "calibration.tolerance"
"""Where the precision is declared, for the message an engine refusal prints."""


def stopping_kwargs(
    method: str,
    space: Any,
    *,
    tolerance: float | None,
    declared: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the engine kwargs with *tolerance* written in the engine's own option.

    ``declared`` is what the file wrote under ``optimizer_kwargs``, which stays
    the escape hatch for reproducing a published call in the engine's own units.
    Stating both the precision and the option it writes is refused: two numbers
    for one rule, silently ranked, is how a configuration stops meaning what it
    says.
    """
    kwargs = dict(declared or {})
    if tolerance is None:
        return kwargs

    value = float(tolerance)
    if value <= 0.0:
        raise ValueError(f"{TOLERANCE_FIELD} must be strictly positive, got {value!r}.")

    traits = engine_traits(method)
    option = traits.tolerance_option
    if option is None:
        raise ValueError(
            f"{TOLERANCE_FIELD} asks {method!r} to stop at a precision on the "
            "parameter, and that engine has no such rule: it stops on its "
            "evaluation budget, or on the spread of its own population. Set "
            "max_iter to say how long it may run, or run a phase on an engine "
            "that converges on the parameter ('bisection', 'scipy_nelder_mead')."
        )
    if option in kwargs:
        raise ValueError(
            f"{TOLERANCE_FIELD} and optimizer_kwargs.{option} both set the "
            f"stopping rule of {method!r}. Keep one: the precision, read on the "
            "parameter, or the engine's own option, which reproduces a published "
            "call verbatim."
        )
    kwargs[option] = engine_stopping_value(method, space, tolerance=value)
    return kwargs


def engine_stopping_value(method: str, space: Any, *, tolerance: float) -> float:
    """Return what *method* wants written in its stopping option for *tolerance*."""
    traits = engine_traits(method)
    reads = traits.tolerance_reads
    if reads == "relative_value":
        # The option is already a relative width on the parameter's own value, and
        # the engine declaring it walks log10, so the number carries over.
        return float(tolerance)
    if reads == "search_width":
        return _narrowest_search_width(space, tolerance)
    raise ValueError(
        f"engine {method!r} names {traits.tolerance_option!r} as its stopping rule "
        "without declaring how that option reads its number; set tolerance_reads "
        "in its EngineTraits."
    )


def _narrowest_search_width(space: Any, tolerance: float) -> float:
    """Return the strictest per-parameter width, in the space the search walks.

    One number stops the search for every parameter at once, so the precision has
    to be the one that satisfies all of them, which is the smallest.
    """
    widths = [search_width(parameter, tolerance) for parameter in getattr(space, "parameters", ())]
    if not widths:
        raise ValueError(
            f"{TOLERANCE_FIELD} is a precision on a parameter, and the search space declares none."
        )
    return min(widths)


def search_width(parameter: Any, tolerance: float) -> float:
    """Return *tolerance* as a width in the variable the search walks.

    On a log-transformed parameter a relative precision is a ratio, and the search
    variable is the decade, so the width is exact and needs no bound at all: a
    conductivity known to ten per cent is 0.0414 decades wide wherever it sits. On
    any other transform there is no scale on the value to be relative to before
    the search has a value, so the declared interval is the scale.
    """
    if getattr(parameter, "transform", "identity") == "log":
        return math.log10(1.0 + float(tolerance))
    low = float(parameter.lower_transformed)
    high = float(parameter.upper_transformed)
    return float(tolerance) * abs(high - low)


__all__ = ["TOLERANCE_FIELD", "engine_stopping_value", "search_width", "stopping_kwargs"]
