"""How this boundary refuses one member of a request document.

The config boundary already refuses in one shape: a
:class:`~hydromodpy.core.exceptions.ConfigValidationError` carrying one record
per fault, each with the RFC 6901 pointer of the key the document wrote. A
refusal written by hand here must carry the same shape, or a caller would have
to parse two vocabularies to find out which member it got wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.error_locator import format_loc, json_pointer


def refuse_request(
    message: str,
    *,
    loc: Sequence[str],
    msg: str,
    source: str | None = None,
) -> ConfigValidationError:
    """Build the refusal of the request member at *loc*.

    Returned rather than raised, so the raising site stays visible at the
    place that decided the member was wrong.
    """
    return ConfigValidationError(
        message,
        details=(
            {
                "pointer": json_pointer(loc),
                "loc": format_loc(loc) or "<root>",
                "msg": msg,
                "type": "value_error",
            },
        ),
        source=source,
    )


__all__ = ["refuse_request"]
