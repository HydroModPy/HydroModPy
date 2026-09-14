"""CSV row parsing helpers for the site-selection workflow."""

from __future__ import annotations

from hydromodpy.core.exceptions import DataContractViolation


def _required_text(row: dict[str, str], field: str, *, row_number: int) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing required field {field!r}."
        )
    return value


def _float_from_row(
    row: dict[str, str],
    field: str,
    *,
    fallback_field: str,
    row_number: int,
) -> float:
    value = row.get(field)
    if value in {None, ""}:
        value = row.get(fallback_field)
    number = _optional_float(value)
    if number is None:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing numeric {field!r} "
            f"or fallback {fallback_field!r}."
        )
    return number


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return float(text)
