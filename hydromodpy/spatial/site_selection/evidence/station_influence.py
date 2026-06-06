"""Station hydrologic-influence normalization helpers."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.core.json_safe import json_safe_value

STATION_INFLUENCE_FIELDS: tuple[str, ...] = (
    "influence_generale_site",
    "commentaire_influence_generale_site",
    "influence_locale_station",
    "commentaire_influence_locale_station",
    "commentaire_station",
)

DEFAULT_INFLUENCE_COMMENT_KEYWORDS: tuple[str, ...] = (
    "barrage",
    "retenue",
    "derivation",
    "canal",
    "ecluse",
    "ouvrage",
    "regulation",
    "turbinage",
    "hydroelectrique",
    "usine",
)

_NO_INFLUENCE_VALUES = {
    "0",
    "false",
    "faux",
    "n",
    "no",
    "non",
    "none",
    "aucun",
    "aucune",
    "sans influence",
    "pas d influence",
    "non influence",
}
_INFLUENCE_VALUES = {
    "1",
    "true",
    "vrai",
    "o",
    "oui",
    "y",
    "yes",
    "influence",
    "influencee",
    "influencee hydrologiquement",
    "ouvrage",
}
_UNKNOWN_VALUES = {
    "",
    "9",
    "unknown",
    "inconnu",
    "inconnue",
    "indetermine",
    "indeterminee",
    "non renseigne",
    "non renseignee",
    "null",
    "none",
}


@dataclass(frozen=True)
class StationInfluenceDiagnostics:
    """Normalized view of flow-station influence metadata."""

    status: str = "unknown"
    flags: list[str] = field(default_factory=list)
    raw_fields: dict[str, Any] = field(default_factory=dict)
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def has_raw_evidence(self) -> bool:
        return bool(self.raw_fields)


def station_influence_diagnostics(
    attributes: Mapping[str, Any],
    *,
    comment_keywords: Sequence[str] | None = None,
) -> StationInfluenceDiagnostics:
    """Normalize station influence metadata from provider or imported attributes."""

    raw_fields = _station_influence_raw_fields(attributes)
    keywords = tuple(comment_keywords or DEFAULT_INFLUENCE_COMMENT_KEYWORDS)
    general_value = _first_value(
        attributes,
        "influence_generale_site",
        "flow_station_influence_generale_site",
        "hydro_station_influence_generale_site",
        "station_influence_generale_site",
        "general_influence",
        "flow_station_general_influence",
    )
    local_value = _first_value(
        attributes,
        "influence_locale_station",
        "flow_station_influence_locale_station",
        "hydro_station_influence_locale_station",
        "station_influence_locale_station",
        "local_influence",
        "flow_station_local_influence",
    )
    general_comment = _first_text(
        attributes,
        "commentaire_influence_generale_site",
        "flow_station_commentaire_influence_generale_site",
        "hydro_station_commentaire_influence_generale_site",
        "station_commentaire_influence_generale_site",
        "general_influence_comment",
        "flow_station_general_influence_comment",
    )
    local_comment = _first_text(
        attributes,
        "commentaire_influence_locale_station",
        "flow_station_commentaire_influence_locale_station",
        "hydro_station_commentaire_influence_locale_station",
        "station_commentaire_influence_locale_station",
        "local_influence_comment",
        "flow_station_local_influence_comment",
    )
    station_comment = _first_text(
        attributes,
        "commentaire_station",
        "flow_station_commentaire_station",
        "hydro_station_commentaire_station",
        "station_commentaire_station",
        "station_comment",
        "flow_station_comment",
    )

    general_state = _influence_state(general_value)
    local_state = _influence_state(local_value)
    general_keywords = _matched_keywords(general_comment, keywords)
    local_keywords = _matched_keywords(local_comment, keywords)
    station_keywords = _matched_keywords(station_comment, keywords)

    flags: list[str] = []
    matched_keywords = _stable_unique([*general_keywords, *local_keywords, *station_keywords])
    if general_state is True:
        flags.append("general_influence")
    if local_state is True:
        flags.append("local_influence")
    if general_keywords:
        flags.append("general_influence_comment_keyword")
    if local_keywords:
        flags.append("local_influence_comment_keyword")
    if station_keywords:
        flags.append("station_comment_keyword")

    if general_state is True:
        status = "general_influence"
    elif local_state is True:
        status = "local_influence"
    elif general_state is False or local_state is False:
        status = "no_known_influence"
    else:
        status = "unknown"

    return StationInfluenceDiagnostics(
        status=status,
        flags=_stable_unique(flags),
        raw_fields=raw_fields,
        matched_keywords=matched_keywords,
    )


def station_influence_metadata_from_hubeau(info: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Hub'Eau station influence fields that should be kept."""

    return {
        key: info.get(key) for key in STATION_INFLUENCE_FIELDS if info.get(key) not in (None, "")
    }


def _station_influence_raw_fields(attributes: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    suffixes = set(STATION_INFLUENCE_FIELDS) | {
        "general_influence",
        "local_influence",
        "general_influence_comment",
        "local_influence_comment",
        "station_comment",
    }
    prefixes = ("", "flow_station_", "hydro_station_", "station_")
    for suffix in suffixes:
        for prefix in prefixes:
            key = f"{prefix}{suffix}"
            value = attributes.get(key)
            if value not in (None, ""):
                fields[key] = json_safe_value(value)
    return fields


def _influence_state(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = _normalize_text(value)
    if text in _UNKNOWN_VALUES:
        return None
    if text in _NO_INFLUENCE_VALUES:
        return False
    if text in _INFLUENCE_VALUES:
        return True
    try:
        return float(text.replace(",", ".")) > 0.0
    except ValueError:
        pass
    if "sans influence" in text or "pas d influence" in text:
        return False
    if "influence" in text:
        return True
    return None


def _matched_keywords(text: str | None, keywords: Sequence[str]) -> list[str]:
    if not text:
        return []
    normalized = _normalize_text(text)
    matches = []
    for keyword in keywords:
        token = _normalize_text(keyword)
        if token and token in normalized:
            matches.append(token)
    return _stable_unique(matches)


def _first_value(attributes: Mapping[str, Any], *keys: str) -> object | None:
    for key in keys:
        value = attributes.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_text(attributes: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_text(value: object) -> str:
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def _stable_unique(values: Sequence[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


__all__ = [
    "DEFAULT_INFLUENCE_COMMENT_KEYWORDS",
    "STATION_INFLUENCE_FIELDS",
    "StationInfluenceDiagnostics",
    "station_influence_diagnostics",
    "station_influence_metadata_from_hubeau",
]
