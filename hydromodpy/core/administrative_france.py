"""French administrative region name registry shared by config layers."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

_FRENCH_REGION_CANONICAL_BY_CODE: dict[str, str] = {
    "01": "Guadeloupe",
    "02": "Martinique",
    "03": "Guyane",
    "04": "La-Reunion",
    "06": "Mayotte",
    "11": "Ile-de-France",
    "24": "Centre-Val-de-Loire",
    "27": "Bourgogne-Franche-Comte",
    "28": "Normandie",
    "32": "Hauts-de-France",
    "44": "Grand-Est",
    "52": "Pays-de-la-Loire",
    "53": "Bretagne",
    "75": "Nouvelle-Aquitaine",
    "76": "Occitanie",
    "84": "Auvergne-Rhone-Alpes",
    "93": "Provence-Alpes-Cote-d-Azur",
    "94": "Corse",
}

_REGION_CODE_BY_KEY: dict[str, str] = {
    "auvergne-rhone-alpes": "84",
    "bourgogne-franche-comte": "27",
    "bretagne": "53",
    "centre-val-de-loire": "24",
    "corse": "94",
    "grand-est": "44",
    "hauts-de-france": "32",
    "ile-de-france": "11",
    "normandie": "28",
    "nouvelle-aquitaine": "75",
    "occitanie": "76",
    "pays-de-la-loire": "52",
    "provence-alpes-cote-d-azur": "93",
    "guadeloupe": "01",
    "martinique": "02",
    "guyane": "03",
    "la-reunion": "04",
    "reunion": "04",
    "mayotte": "06",
}


def normalize_french_region_key(value: str) -> str:
    """Normalize a French region label for registry lookups."""

    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = "".join(
        char.lower() if char.isalnum() else "-" for char in ascii_text.replace("'", " ")
    )
    parts = [part for part in normalized.split("-") if part]
    return "-".join(parts)


def french_region_code(region: str) -> str:
    """Return the INSEE region code for a supported French region label or code."""

    text = str(region).strip()
    if text.isdigit():
        code = text.zfill(2)
        if code in _FRENCH_REGION_CANONICAL_BY_CODE:
            return code
        known = ", ".join(known_french_region_names())
        raise ValueError(f"Unknown French region {region!r}. Known regions: {known}")
    key = normalize_french_region_key(text)
    code = _REGION_CODE_BY_KEY.get(key)
    if code is None:
        known = ", ".join(known_french_region_names())
        raise ValueError(f"Unknown French region {region!r}. Known regions: {known}")
    return code


def validate_french_regions(regions: Sequence[str]) -> list[str]:
    """Validate French region labels and return canonical labels."""

    canonical: list[str] = []
    seen: set[str] = set()
    for region in regions:
        code = french_region_code(region)
        label = _FRENCH_REGION_CANONICAL_BY_CODE[code]
        if code not in seen:
            canonical.append(label)
            seen.add(code)
    return canonical


def known_french_region_names() -> list[str]:
    """Return canonical French administrative region labels accepted in configs."""

    return sorted(_FRENCH_REGION_CANONICAL_BY_CODE.values())


__all__ = [
    "french_region_code",
    "known_french_region_names",
    "normalize_french_region_key",
    "validate_french_regions",
]
