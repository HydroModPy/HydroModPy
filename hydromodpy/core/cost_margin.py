"""The margin a cost may sit from the best before a trial stops counting as tied with it.

A margin carries its unit. ``"5%"`` is a share of the best cost, which suits an
efficiency score. ``"75 m"`` is a length, which suits a criterion that is a
network distance in meters and is solved at zero, where a share of the best has
nothing to take a fraction of. A bare number is refused: it said nothing about
which of the two it was.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from hydromodpy.core.units.length import convert_to_m

MarginKind = Literal["relative", "absolute"]

NEEDS_A_UNIT = "write '5%' or '25 m', a share of the best cost or a length"

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_SHARE = re.compile(rf"^({_NUMBER})\s*%$")
_LENGTH = re.compile(rf"^({_NUMBER})\s*([A-Za-z]+)$")


@dataclass(frozen=True)
class CostMargin:
    """A margin read: a fraction of the best cost, or a length in meters."""

    kind: MarginKind
    value: float


def parse_cost_margin(value: object, *, label: str = "cost_margin") -> CostMargin:
    """Return the margin *value* writes, or raise ``ValueError`` naming *label*.

    ``"5%"`` reads as a fraction, 0.05, of the best cost. ``"75 m"``, or any
    other length unit, reads as meters.
    """
    if not isinstance(value, str):
        raise ValueError(f"{label} = {value!r} has no unit: {NEEDS_A_UNIT}.")
    text = value.strip()
    share = _SHARE.match(text)
    if share is not None:
        fraction = float(share.group(1)) / 100.0
        return CostMargin("relative", _positive(fraction, text, label))
    length = _LENGTH.match(text)
    if length is not None:
        try:
            metres = convert_to_m(float(length.group(1)), unit=length.group(2), label=label)
        except ValueError as exc:
            raise ValueError(f"{label} = {value!r}: {exc}") from None
        return CostMargin("absolute", _positive(metres, text, label))
    if re.fullmatch(_NUMBER, text):
        raise ValueError(f"{label} = {value!r} has no unit: {NEEDS_A_UNIT}.")
    raise ValueError(f"{label} = {value!r} is not a share or a length: {NEEDS_A_UNIT}.")


def _positive(number: float, text: str, label: str) -> float:
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} = {text!r} must be strictly positive: {NEEDS_A_UNIT}.")
    return number


__all__ = ["NEEDS_A_UNIT", "CostMargin", "MarginKind", "parse_cost_margin"]
