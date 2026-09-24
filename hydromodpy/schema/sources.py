"""The licence of each data source this build reads, stated once.

A run used to tell a reader it may be reused under ``CC-BY-4.0``, a licence
nobody chose. The honest answer comes from the inputs: each source states its
licence here as an SPDX id, a run rolls up the licences of what it read, and a
single unknown member makes the whole run ``LicenseRef-undetermined``.

A claim is written here only when it is established by the provider's own
terms as this repository already records them, or by a public fact that can be
named. Every other source stays undetermined, with the reason beside it. A
wrong entry is worse than an absent one: it is a legal statement about
somebody else's data.

The registry is keyed by the slugs the code already writes: the ``source``
field of a data section, of a catalog entry and of a sidecar. The ids of the
data-source port (``ign-bdalti``, ...) are aliases of the same entries.

This module lives in ``schema`` because both ends need it: ``data`` stamps a
licence on a sidecar at fetch time, ``results`` rolls it up at seal time, and
both may import ``schema`` without a new edge in the layer matrix.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.schema.job.inputset import UNDETERMINED, Licence, roll_up_licences

SIDECAR_SUFFIX = ".json"
"""Suffix of the provenance sidecar next to a raw input file.

The same value as ``hydromodpy.data.provenance.sidecars.SIDECAR_SUFFIX``. ``schema`` may
not import ``data``, so a test holds the two equal.
"""

_ETALAB_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One data source: who publishes it, its licence, and why we say so."""

    slug: str
    publisher: str | None
    licence: Licence
    basis: str
    aliases: tuple[str, ...] = ()


def _undetermined(slug: str, publisher: str | None, reason: str, *aliases: str) -> SourceEntry:
    return SourceEntry(slug, publisher, UNDETERMINED, reason, tuple(aliases))


_ENTRIES: tuple[SourceEntry, ...] = (
    SourceEntry(
        slug="brgm_1m",
        publisher="BRGM",
        licence=Licence(
            spdx="etalab-2.0",
            url=_ETALAB_URL,
            attribution="Source: BRGM, 1:1M geological map of France",
            confidence="assumed",
        ),
        basis=(
            "The adapter docstring (data/variables/geology/apis/brgm_1m.py) records "
            "'License: ETALAB Open Licence v2.0 (open data, attribution required)'."
        ),
    ),
    SourceEntry(
        slug="brgm_50k",
        publisher="BRGM",
        licence=Licence(
            spdx="etalab-2.0",
            url=_ETALAB_URL,
            attribution="Source: BRGM, BD Charm-50 harmonised geological map",
            confidence="assumed",
        ),
        basis=(
            "The adapter docstring (data/variables/geology/apis/brgm_50k.py) records "
            "'License: ETALAB Open Licence v2.0 (open data, attribution required)'."
        ),
    ),
    SourceEntry(
        slug="ign_geoplateforme_dem",
        publisher="IGN",
        licence=Licence(
            spdx="etalab-2.0",
            url=_ETALAB_URL,
            attribution="Source: IGN, Geoplateforme elevation data",
            confidence="assumed",
        ),
        basis=(
            "IGN publishes its data under Licence Ouverte Etalab 2.0 since 1 January "
            "2021, and the download endpoint is IGN's own (data.geopf.fr). The same "
            "publisher and licence are recorded in spatial/administrative/france.py."
        ),
        aliases=("ign-bdalti",),
    ),
    SourceEntry(
        slug="osm",
        publisher="OpenStreetMap contributors",
        licence=Licence(
            spdx="ODbL-1.0",
            url="https://www.openstreetmap.org/copyright",
            attribution="© OpenStreetMap contributors",
            share_alike=True,
            confidence="assumed",
        ),
        basis=(
            "OpenStreetMap data is licensed under the Open Database License 1.0, as "
            "stated at openstreetmap.org/copyright. Overpass serves that data."
        ),
    ),
    _undetermined(
        "bdtopage",
        "Sandre / OFB",
        "Sandre states its terms on its own site; this repository does not record "
        "them for BD TOPAGE, so no licence is claimed.",
    ),
    _undetermined(
        "euhydro",
        "Copernicus Land Monitoring Service (EEA)",
        "Copernicus data follows the Copernicus data policy, which has no SPDX id, "
        "and this repository defines no LicenseRef for it.",
    ),
    _undetermined(
        "hubeau",
        "Hub'Eau (OFB / BRGM)",
        "Hub'Eau republishes several upstream databases (ADES, Hydroportail, Naiades) "
        "and this repository records the terms of none of them.",
        "hubeau-piezometry",
    ),
    _undetermined(
        "sim2",
        "Meteo-France, served by GeoSAS",
        "The adapter reads SAFRAN-ISBA through GeoSAS (api.geosas.fr), an "
        "intermediary; this repository records no terms for that copy.",
        "sim2-precipitation",
    ),
    _undetermined(
        "shom",
        "SHOM",
        "SHOM products carry different licences and this repository records none "
        "for the tide-gauge service it reads.",
    ),
    _undetermined(
        "custom",
        None,
        "A file the user supplied. Its licence is the user's to declare, in the "
        "'license' key of its sidecar.",
    ),
    _undetermined(
        "constant",
        None,
        "A value generated from the configuration. Its terms are the author's to choose.",
    ),
    _undetermined(
        "synthetic",
        None,
        "A series generated from the configuration. Its terms are the author's to choose.",
    ),
)


def _index(entries: Iterable[SourceEntry]) -> Mapping[str, SourceEntry]:
    table: dict[str, SourceEntry] = {}
    for entry in entries:
        for name in (entry.slug, *entry.aliases):
            if name in table:
                raise ValueError(f"source slug {name!r} is declared twice")
            table[name] = entry
    return MappingProxyType(table)


SOURCES: Mapping[str, SourceEntry] = _index(_ENTRIES)
"""Every known slug and alias, mapped to its entry."""


def source_entry(slug: str | None) -> SourceEntry | None:
    """Return the entry of *slug*, or ``None`` when it is not known here."""
    if not slug:
        return None
    return SOURCES.get(str(slug).strip())


def licence_for_source(slug: str | None) -> Licence:
    """Return the licence of *slug*. An unknown slug is undetermined."""
    entry = source_entry(slug)
    return entry.licence if entry is not None else UNDETERMINED


def is_determined(spdx: str | None) -> bool:
    """Whether *spdx* names a licence someone actually stated."""
    return bool(spdx) and str(spdx).strip() != UNDETERMINED_LICENSE


def sidecar_path(path: Path) -> Path:
    """Return the sidecar path of *path* (``foo.tif`` -> ``foo.tif.json``)."""
    return path.with_name(path.name + SIDECAR_SUFFIX)


def licence_from_sidecar(payload: Mapping[str, object]) -> Licence:
    """Return the licence a sidecar payload states.

    A ``license`` key naming a real licence wins: the user may declare it for
    a file they supplied. Otherwise the ``source`` slug is looked up here, so
    a sidecar written before this registry existed still counts.
    """
    declared = payload.get("license")
    if isinstance(declared, str) and is_determined(declared):
        entry = source_entry(str(payload.get("source") or ""))
        if entry is not None and entry.licence.spdx == declared.strip():
            return entry.licence
        return Licence(spdx=declared.strip(), confidence="declared")
    return licence_for_source(str(payload.get("source") or ""))


def _read_sidecar(path: Path) -> Licence:
    target = sidecar_path(path)
    if not target.is_file():
        return UNDETERMINED
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNDETERMINED
    if not isinstance(payload, dict):
        return UNDETERMINED
    return licence_from_sidecar(payload)


def _is_sidecar(path: Path) -> bool:
    return (
        path.name.endswith(SIDECAR_SUFFIX)
        and path.with_name(path.name[: -len(SIDECAR_SUFFIX)]).exists()
    )


def input_licence(path: Path | str) -> Licence:
    """Return the licence of one input file or directory, from its sidecars.

    A file without a sidecar is undetermined. A directory is the roll-up of
    every file in it, so one file without a sidecar makes it undetermined.
    """
    target = Path(path)
    if target.is_file():
        return _read_sidecar(target)
    if not target.is_dir():
        return UNDETERMINED
    members = [
        _read_sidecar(item)
        for item in sorted(target.rglob("*"))
        if item.is_file() and not _is_sidecar(item)
    ]
    if not members:
        return UNDETERMINED
    rollup = roll_up_licences(members)
    if not is_determined(rollup.expression) or not rollup.redistributable:
        return UNDETERMINED
    return Licence(
        spdx=rollup.expression,
        share_alike=rollup.share_alike,
        confidence=rollup.confidence,
        attribution="; ".join(rollup.attribution) or None,
    )


def derived_licence(licences: Iterable[Licence]) -> str:
    """Return the SPDX expression a run may state, from the licences of its inputs.

    No input, or one undetermined input, gives ``LicenseRef-undetermined``:
    a run cannot promise more than its least known input allows.
    """
    members = tuple(licences)
    if not members:
        return UNDETERMINED_LICENSE
    rollup = roll_up_licences(members)
    if not rollup.redistributable:
        return UNDETERMINED_LICENSE
    return rollup.expression


__all__ = [
    "SIDECAR_SUFFIX",
    "SOURCES",
    "SourceEntry",
    "derived_licence",
    "input_licence",
    "is_determined",
    "licence_for_source",
    "licence_from_sidecar",
    "sidecar_path",
    "source_entry",
]
