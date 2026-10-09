"""The licence and the facts of each data source this build reads, stated once.

A run used to tell a reader it may be reused under ``CC-BY-4.0``, a licence
nobody chose. The honest answer comes from the inputs: each source states its
licence here as an SPDX id, a run rolls up the licences of what it read, and a
single unknown member makes the whole run ``LicenseRef-undetermined``.

A claim is written here only when the publisher states it, on a page this
module names (``licence_pages``) and was read on the date it names
(``licence_checked``). The confidence stays ``assumed``: the publisher states
the licence of its dataset, and no file this build fetched is checked one by
one. ``declared`` is kept for a licence a user writes in a sidecar. A source
whose licence cannot be established stays undetermined, with the reason
beside it. A wrong entry is worse than an absent one: it is a legal statement
about somebody else's data.

Beside the licence, an entry carries what a reference page needs about the
source: ``coverage``, ``resolution``, ``period``, ``update``,
``authentication``, ``limits`` and the ``cache`` layout of the files a fetch
leaves in a workspace. A field is filled only with what the publisher's page
or the adapter code says, and stays ``None`` otherwise. ``facts_pages`` lists
the pages the facts were read on.

The registry is keyed by the slugs the code already writes: the ``source``
field of a data section, of a catalog entry and of a sidecar. The three
sources of the data-source port (``bdtopage``, ``euhydro``, ``osm``) carry the
same slugs.

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
from typing import Any

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.schema.job.inputset import UNDETERMINED, Licence, roll_up_licences

SIDECAR_SUFFIX = ".json"
"""Suffix of the provenance sidecar next to a raw input file.

The same value as ``hydromodpy.data.provenance.sidecars.SIDECAR_SUFFIX``. ``schema`` may
not import ``data``, so a test holds the two equal.
"""

CACHE_INDEX = "data/cache.duckdb"
"""The DuckDB index of the downloaded files, under the workspace root.

The files and their sidecars stay the truth; the index is derived.
"""

LICENCES_CHECKED = "2026-10-09"
"""The day the licences below were read on the publishers' pages."""

COPERNICUS_LICENCE_ID = "LicenseRef-Copernicus-1159-2013"
"""Free, full and open access under Delegated Regulation (EU) No 1159/2013.

SPDX has no id for it, so it is a ``LicenseRef``: the conditions are to inform
the public of the source, to state any adaptation, and not to suggest an EU
endorsement.
"""

_ETALAB_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
_COPERNICUS_URL = "https://eur-lex.europa.eu/eli/reg_del/2013/1159/oj"
_ODBL_URL = "https://www.openstreetmap.org/copyright"


@dataclass(frozen=True, slots=True)
class CacheLayout:
    """Where a fetch leaves its files under a workspace, and how they are named."""

    folder: str
    """The folder under the workspace root, for example ``data/hydrography``."""
    pattern: str
    """A glob that matches the file names, ``<...>`` standing for a token."""
    format: str
    """The file format."""
    note: str | None = None
    """What else sits beside the files."""

    def to_document(self) -> dict[str, Any]:
        return {
            "folder": self.folder,
            "pattern": self.pattern,
            "format": self.format,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One data source: who publishes it, its licence, why we say so, and where it is read."""

    slug: str
    publisher: str | None
    licence: Licence
    basis: str
    hosts: tuple[str, ...] = ()
    """The network hosts a fetch contacts; empty for a source read or built locally."""
    licence_pages: tuple[str, ...] = ()
    """The pages that state the licence, on or about the publisher's own site."""
    licence_checked: str | None = None
    """The ISO date those pages were read."""
    facts_pages: tuple[str, ...] = ()
    """The pages the coverage, resolution, period and limits were read on."""
    coverage: str | None = None
    resolution: str | None = None
    period: str | None = None
    update: str | None = None
    authentication: str | None = None
    limits: str | None = None
    cache: tuple[CacheLayout, ...] = ()
    """The files a fetch leaves in a workspace; empty when it leaves none."""

    def to_document(self) -> dict[str, Any]:
        """Render the entry as the plain object a documentation generator reads."""
        return {
            "slug": self.slug,
            "publisher": self.publisher,
            "licence": self.licence.to_document(),
            "basis": self.basis,
            "hosts": list(self.hosts),
            "licence_pages": list(self.licence_pages),
            "licence_checked": self.licence_checked,
            "facts_pages": list(self.facts_pages),
            "coverage": self.coverage,
            "resolution": self.resolution,
            "period": self.period,
            "update": self.update,
            "authentication": self.authentication,
            "limits": self.limits,
            "cache": [layout.to_document() for layout in self.cache],
        }


def _undetermined(
    slug: str,
    publisher: str | None,
    reason: str,
    *,
    hosts: tuple[str, ...] = (),
    **facts: Any,
) -> SourceEntry:
    return SourceEntry(slug, publisher, UNDETERMINED, reason, hosts, **facts)


def _etalab(attribution: str) -> Licence:
    return Licence(
        spdx="etalab-2.0", url=_ETALAB_URL, attribution=attribution, confidence="assumed"
    )


_WORKSPACE_NOTE = (
    "Each file has a sidecar named after it with a '.json' suffix, which holds its "
    "source, digest and licence."
)

_GEOPF_RATE_LIMITS = (
    "cartes.gouv.fr terms: WFS 30 requests/s, WMS-Raster 40 requests/s, download "
    "5 requests per 5 s with a 5 minute ban; over the limit the service answers 429."
)

# The sentences below were read on LICENCES_CHECKED. Each licence line names the
# page that states it. Nothing is copied from memory.

_ENTRIES: tuple[SourceEntry, ...] = (
    SourceEntry(
        slug="brgm_1m",
        publisher="BRGM",
        licence=_etalab("Source: BRGM, 1:1M geological map of France"),
        basis=(
            "BRGM states on InfoTerre: 'Les Données disponibles sur le site InfoTerre "
            "sont soumises à la licence Ouverte / Open Licence Etalab Version 2.0', "
            "unless an exception is shown, with the source (BRGM) and the date of last "
            "update to cite and the data not to be altered. The 1:1M download form "
            "points to those terms and links the archive the adapter fetches "
            "(data/variables/geology/apis/brgm_1m.py)."
        ),
        hosts=("infoterre.brgm.fr",),
        licence_pages=(
            "https://infoterre.brgm.fr/page/conditions-dutilisation-donnees",
            "https://infoterre.brgm.fr/formulaire/telechargement-carte-geologique-metropolitaine-11-000-000",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://infoterre.brgm.fr/formulaire/telechargement-carte-geologique-metropolitaine-11-000-000",
        ),
        coverage="Metropolitan France.",
        resolution="Vector map at 1:1 000 000, 6th revised edition, six information layers.",
        period="One edition of a map, not a time series.",
        authentication="None: the adapter fetches the archive by plain HTTP.",
        cache=(
            CacheLayout(
                folder="data/geology",
                pattern="geology_brgm_1m_*.gpkg",
                format="GeoPackage",
                note=(
                    "geology_brgm_1m_france.gpkg is the whole country, built once from the "
                    "archive FR_vecteur.zip kept beside it; geology_brgm_1m_<bbox hash>.gpkg "
                    "is the crop of one request. " + _WORKSPACE_NOTE
                ),
            ),
        ),
    ),
    SourceEntry(
        slug="brgm_50k",
        publisher="BRGM",
        licence=_etalab("Source: BRGM, BD Charm-50 harmonised geological map"),
        basis=(
            "BRGM states on InfoTerre: 'Les Données disponibles sur le site InfoTerre "
            "sont soumises à la licence Ouverte / Open Licence Etalab Version 2.0', "
            "unless an exception is shown, with the source (BRGM) and the date of last "
            "update to cite and the data not to be altered. The BD Charm-50 download "
            "form points to those terms."
        ),
        hosts=("infoterre.brgm.fr",),
        licence_pages=(
            "https://infoterre.brgm.fr/page/conditions-dutilisation-donnees",
            "https://infoterre.brgm.fr/formulaire/telechargement-cartes-geologiques-departementales-150-000-bd-charm-50",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://infoterre.brgm.fr/formulaire/telechargement-cartes-geologiques-departementales-150-000-bd-charm-50",
        ),
        coverage="Metropolitan France: 95 departments available, one archive each.",
        resolution=(
            "Vector, harmonised departmental maps at 1:50 000, six information layers; "
            "the adapter reads the S_FGEOL layer in EPSG:2154."
        ),
        period="One edition of a map, not a time series.",
        update="The BRGM download page was last updated on 2021-05-06.",
        authentication="None: the adapter fetches each department archive by plain HTTP.",
        cache=(
            CacheLayout(
                folder="data/geology",
                pattern="geology_brgm_50k_*.gpkg",
                format="GeoPackage",
                note=(
                    "geology_brgm_50k_<bbox hash>.gpkg is the merged crop of one request. "
                    "The departments it was built from stay in departments_50k/ "
                    "(GEO050K_HARM_<code>.zip and one GeoPackage per department). "
                    + _WORKSPACE_NOTE
                ),
            ),
        ),
    ),
    SourceEntry(
        slug="ign_geoplateforme_dem",
        publisher="IGN",
        licence=_etalab("Source: IGN, Geoplateforme elevation data"),
        basis=(
            "IGN, publishing on data.gouv.fr under its own organisation, gives BD ALTI "
            "and RGE ALTI the 'Licence Ouverte / Open Licence version 2.0'. The "
            "cartes.gouv.fr terms add that a Geoplateforme dataset without another "
            "licence falls under the Licence Ouverte Etalab."
        ),
        hosts=("data.geopf.fr",),
        licence_pages=(
            "https://www.data.gouv.fr/datasets/bd-alti-r-1",
            "https://www.data.gouv.fr/datasets/rge-alti-r",
            "https://cartes.gouv.fr/cgu",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://www.data.gouv.fr/datasets/bd-alti-r-1",
            "https://www.data.gouv.fr/datasets/rge-alti-r",
            "https://cartes.gouv.fr/cgu",
        ),
        coverage=(
            "BD ALTI and RGE ALTI cover metropolitan and overseas France except French "
            "Polynesia, New Caledonia and Wallis and Futuna. RGE ALTI holds nodata over "
            "the zones closed to aerial capture. The adapter takes a box in EPSG:2154."
        ),
        resolution=(
            "BD ALTI: regular grid, 25 m (75 m also published); the adapter assembles 25 m "
            "ASC archives. RGE ALTI: regular grid, 1 m or 5 m, fetched by extent from the "
            "WMS-Raster service."
        ),
        period=(
            "BD ALTI: records from 2011-01-01 to 2023-10-04. RGE ALTI: from 2009-01-01 to "
            "2024-11-26; its updates stopped in 2024, pending the LiDAR HD survey."
        ),
        update="BD ALTI: irregular, from RGE ALTI. RGE ALTI: irregular, stopped in 2024.",
        authentication=(
            "None sent by the adapter. The cartes.gouv.fr terms say some APIs may need an "
            "account, according to their documentation."
        ),
        limits=_GEOPF_RATE_LIMITS,
        cache=(
            CacheLayout(
                folder="data/dem/processed",
                pattern="dem_ign_geoplateforme_*.tif",
                format="GeoTIFF",
                note=(
                    "dem_ign_geoplateforme_bdalti_25m_<hash>.tif and "
                    "dem_ign_geoplateforme_rgealti_<resolution>_<hash>.tif. The BD ALTI "
                    "department archives stay in data/dem/raw_ign and data/dem/extracted_ign."
                ),
            ),
        ),
    ),
    SourceEntry(
        slug="bdtopo",
        publisher="IGN",
        licence=_etalab("Source: IGN, BD TOPO roads and railways"),
        basis=(
            "IGN, publishing on data.gouv.fr under its own organisation, gives BD TOPO "
            "the 'Licence Ouverte / Open Licence version 2.0'. The WFS capabilities point "
            "to the cartes.gouv.fr terms and state 'Fees: none'."
        ),
        hosts=("data.geopf.fr",),
        licence_pages=(
            "https://www.data.gouv.fr/datasets/bd-topo-r",
            "https://cartes.gouv.fr/cgu",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://www.data.gouv.fr/datasets/bd-topo-r",
            "https://cartes.gouv.fr/cgu",
        ),
        coverage=(
            "Metropolitan France and several overseas territories. The adapter reads the "
            "road and railway layers over a box in EPSG:2154."
        ),
        resolution="3D vector objects of metric precision.",
        period="Editions from 2008-03-18 to 2026-09-15; the code pins no edition.",
        update="Quarterly editions, with a weekly BDTOPO Express edition since May 2025.",
        authentication="None sent by the adapter.",
        limits=_GEOPF_RATE_LIMITS,
        cache=(
            CacheLayout(
                folder="data/crossings",
                pattern="crossings_bdtopo_*.gpkg",
                format="GeoPackage",
                note="crossings_bdtopo_<bbox hash>.gpkg. " + _WORKSPACE_NOTE,
            ),
        ),
    ),
    SourceEntry(
        slug="osm",
        publisher="OpenStreetMap contributors",
        licence=Licence(
            spdx="ODbL-1.0",
            url=_ODBL_URL,
            attribution="© OpenStreetMap contributors",
            share_alike=True,
            confidence="assumed",
        ),
        basis=(
            "openstreetmap.org/copyright states that the data is licensed under the Open "
            "Data Commons Open Database License (ODbL), and asks to credit OpenStreetMap "
            "and its contributors and to make clear the data is under the ODbL. Overpass "
            "serves that data."
        ),
        hosts=("overpass-api.de",),
        licence_pages=(_ODBL_URL,),
        licence_checked=LICENCES_CHECKED,
        facts_pages=("https://dev.overpass-api.de/overpass-doc/en/preface/commons.html",),
        coverage="The adapter asks Overpass for the waterways inside a box.",
        period="The current database: the query carries no date clause.",
        authentication="None.",
        limits=(
            "Public Overpass instance: about 10 000 requests and 1 GB of download per day "
            "per user, a default timeout of 180 s and 512 MiB of memory per query."
        ),
        cache=(
            CacheLayout(
                folder="data/hydrography",
                pattern="hydrography_osm_*.gpkg",
                format="GeoPackage",
                note="hydrography_osm_<bbox hash>.gpkg. " + _WORKSPACE_NOTE,
            ),
        ),
    ),
    SourceEntry(
        slug="bdtopage",
        publisher="Sandre / OFB",
        licence=_etalab("Source: Sandre (OFB, IGN), BD Topage"),
        basis=(
            "The Sandre atlas record of the 2026 BD Topage reaches (Tronçons "
            "hydrographiques - Métropole 2026) lists 'Licence Ouverte 2.0' and links the "
            "Etalab v2.0 text. The WFS capabilities add 'Fees: no conditions apply' and "
            "'accés libre ... pour tous les usages y compris commerciaux'."
        ),
        hosts=("services.sandre.eaufrance.fr",),
        licence_pages=(
            "https://www.sandre.eaufrance.fr/atlas/srv/api/records/14918811-c13c-481c-9dbe-2487b5436b24",
            "https://www.sandre.eaufrance.fr/atlas/srv/api/records/37c9509d-4ee4-4723-97ad-035a859215b3",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://www.sandre.eaufrance.fr/atlas/srv/api/records/14918811-c13c-481c-9dbe-2487b5436b24",
            "https://services.sandre.eaufrance.fr/geo/sandre?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities",
        ),
        coverage=(
            "Metropolitan France (layer sa:TronconHydrographique_FXX_Topage2026); an "
            "overseas layer is refused by the adapter."
        ),
        resolution="Vector reaches, for scales from 1:5 000 to 1:50 000, to 1 m.",
        period="The 2026 vintage; a new vintage changes the layer name.",
        update="Annual.",
        authentication="None: free access.",
        limits=(
            "No limit stated. The adapter pages by COUNT and follows the announced total "
            "because the server returns short pages."
        ),
        cache=(
            CacheLayout(
                folder="data/hydrography",
                pattern="hydrography_bdtopage_*.gpkg",
                format="GeoPackage",
                note=(
                    "hydrography_bdtopage_<bbox hash>.gpkg is the full answer, in EPSG:2154. "
                    "hydrography_bdtopage_permanent_<bbox hash>.gpkg holds only its "
                    "permanent reaches and is not registered in the index. " + _WORKSPACE_NOTE
                ),
            ),
        ),
    ),
    SourceEntry(
        slug="roe",
        publisher="Sandre / OFB",
        licence=_etalab("Source: Sandre (OFB), ROE obstacles to flow"),
        basis=(
            "The Sandre atlas record 'Obstacles à l'écoulement - Métropole' lists "
            "'Licence Ouverte Etalab' as its use limitation and 'Pas de restriction "
            "d'accès public'. The WFS capabilities state 'Fees: no conditions apply'."
        ),
        hosts=("services.sandre.eaufrance.fr",),
        licence_pages=(
            "https://www.sandre.eaufrance.fr/atlas/srv/api/records/070df464-73d3-4c00-be2f-93f2a97ef8f5",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://www.sandre.eaufrance.fr/atlas/srv/api/records/070df464-73d3-4c00-be2f-93f2a97ef8f5",
            "https://services.sandre.eaufrance.fr/geo/obs?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities",
        ),
        coverage="Metropolitan France (layer sa:ObstEcoul_FXX), one point per obstacle.",
        resolution="Points, equivalent scale 1:50 000.",
        period="The record gives no temporal extent; it was revised on 2026-10-08 at the check.",
        update="Weekly.",
        authentication="None: free access.",
        cache=(
            CacheLayout(
                folder="data/crossings",
                pattern="crossings_roe_*.gpkg",
                format="GeoPackage",
                note="crossings_roe_<bbox hash>.gpkg. " + _WORKSPACE_NOTE,
            ),
        ),
    ),
    SourceEntry(
        slug="euhydro",
        publisher="Copernicus Land Monitoring Service (EEA)",
        licence=Licence(
            spdx=COPERNICUS_LICENCE_ID,
            url=_COPERNICUS_URL,
            attribution="Source: Copernicus Land Monitoring Service, EU-Hydro, European Environment Agency",
            confidence="assumed",
        ),
        basis=(
            "The EEA catalogue record that links the MapServer the adapter reads says: "
            "'Free, full and open access to the products and services of the Copernicus "
            "Land Monitoring Service is made on the conditions that' the source is "
            "attributed, any modification is stated, and no EU endorsement is suggested "
            "(Delegated Regulation (EU) No 1159/2013, limitation on public access "
            "'noLimitations'). That is not an SPDX licence, so the id is a LicenseRef."
        ),
        hosts=("image.discomap.eea.europa.eu",),
        licence_pages=(
            "https://sdi.eea.europa.eu/catalogue/srv/api/records/801dc3ca-339d-4e27-9a18-08b6934efe34",
            "https://sdi.eea.europa.eu/catalogue/copernicus/api/records/393359a7-7ebd-4a52-80ac-1a18d5f3db9c",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://sdi.eea.europa.eu/catalogue/copernicus/api/records/393359a7-7ebd-4a52-80ac-1a18d5f3db9c",
            "https://image.discomap.eea.europa.eu/arcgis/rest/services/EUHydro/EUHydro_RiverNetworkDatabase/MapServer?f=pjson",
        ),
        coverage=(
            "The EEA39 countries (service description), from 27.4 to 71.4 degrees N and "
            "-31.6 to 44.8 degrees E, plus French overseas departments."
        ),
        resolution=(
            "Photo-interpreted river network by Strahler order, equivalent scale 1:50 000, "
            "minimum mapping unit 1 ha (EEA record of the 2006-2012 database, v1.3)."
        ),
        period="Reference period 2006-01-01 to 2012-12-31.",
        update="The EEA record of the 2006-2012 database (v1.3) gives its maintenance as continual.",
        authentication="None.",
        limits="At most 1000 records per request (service setting); the adapter pages.",
        cache=(
            CacheLayout(
                folder="data/hydrography",
                pattern="hydrography_euhydro_*.gpkg",
                format="GeoPackage",
                note="hydrography_euhydro_<bbox hash>.gpkg. " + _WORKSPACE_NOTE,
            ),
        ),
    ),
    SourceEntry(
        slug="hubeau",
        publisher="Hub'Eau (OFB / BRGM)",
        licence=_etalab(
            "Source: Hub'Eau, with the author of each dataset as named on its API page"
        ),
        basis=(
            "The Hub'Eau terms of use state: 'La réutilisation des Jeux de données est "
            "régie par la licence ouverte Etalab' and ask the user to cite the author of "
            "the datasets. They call the APIs 'libres d'accès et d'utilisation'."
        ),
        hosts=("hubeau.eaufrance.fr",),
        licence_pages=("https://hubeau.eaufrance.fr/page/conditions-generales",),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://hubeau.eaufrance.fr/page/api-hydrometrie",
            "https://hubeau.eaufrance.fr/page/api-piezometrie",
            "https://hubeau.eaufrance.fr/page/api-ecoulement",
            "https://hubeau.eaufrance.fr/page/api-qualite-cours-deau",
            "https://hubeau.eaufrance.fr/page/api-qualite-nappes",
        ),
        coverage=(
            "Hydrometry: the French network of about 5000 stations (PHyC). Groundwater "
            "levels (ADES) and groundwater quality: all of France. River quality "
            "(Naiades): all of France including overseas departments. Stream flow state "
            "(ONDE): metropolitan France with Corsica, over 3200 stations."
        ),
        resolution=(
            "Station time series. Hydrometry: observations every 5 to 60 minutes, with "
            "daily and monthly elaborated values. Stream flow state: visual observations "
            "in the summer period. The adapters read stations, not grids."
        ),
        period=(
            "Hydrometry: real-time observations keep one month of history, elaborated "
            "daily and monthly discharge cover the whole history, since 1900 for some "
            "stations. Stream flow state: more than 10 years. Groundwater quality: over "
            "100 million analyses at the start of 2021. The other APIs state no start date."
        ),
        update=(
            "Hydrometry: every 5 minutes for real-time values, daily for elaborated ones. "
            "Groundwater levels: daily. Groundwater and river quality: synchronised with "
            "their source databases."
        ),
        authentication="None: the terms ask for no registration and the adapters send no key.",
        limits=(
            "No limit stated on the terms page, which asks users to minimise resource "
            "use by filtering and compressing."
        ),
        cache=(
            CacheLayout(
                folder="data/hydrometry",
                pattern="hydrometry_hubeau_*.csv",
                format="CSV",
                note=(
                    "hydrometry_hubeau_<station>_<start>_<end>_<frequency>.csv, one per "
                    "station; hydrometry_hubeau_LOC.csv lists the station locations. "
                    + _WORKSPACE_NOTE
                ),
            ),
            CacheLayout(
                folder="data/piezometry",
                pattern="piezometry_hubeau_*.csv",
                format="CSV",
                note="Same naming as hydrometry, with the prefix piezometry.",
            ),
            CacheLayout(
                folder="data/intermittency",
                pattern="intermittency_hubeau_*.csv",
                format="CSV",
                note="Same naming as hydrometry, with the prefix intermittency.",
            ),
            CacheLayout(
                folder="data/water_quality",
                pattern="waterquality_hubeau_*.csv",
                format="CSV",
                note="Same naming as hydrometry, with the prefix waterquality (no underscore).",
            ),
        ),
    ),
    SourceEntry(
        slug="sim2",
        publisher="Meteo-France, served by GeoSAS",
        licence=_etalab("Source : Météo France"),
        basis=(
            "The GeoSAS service, which the adapter reads, links the Etalab open licence "
            "in its own collection description and its catalogue record states 'Usage "
            "libre sous réserve des mentions obligatoires ... Source : Météo France'. "
            "data.gouv.fr lists the same SIM quotidienne dataset, published by "
            "Meteo-France, under the 'Licence Ouverte / Open Licence version 2.0'."
        ),
        hosts=("api.geosas.fr",),
        licence_pages=(
            "https://geosas.fr/geonetwork/apps/api/records/4ee133fa-d4cb-44d8-b708-46946573ba5f",
            "https://api.geosas.fr/edr/collections/safran-isba?f=json",
            "https://www.data.gouv.fr/datasets/donnees-changement-climatique-sim-quotidienne",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://api.geosas.fr/edr/collections/safran-isba?f=json",
            "https://geosas.fr/geonetwork/apps/api/records/4ee133fa-d4cb-44d8-b708-46946573ba5f",
            "https://www.data.gouv.fr/datasets/donnees-changement-climatique-sim-quotidienne",
        ),
        coverage=(
            "Metropolitan France, on the SAFRAN grid. The service CRS is IGNF:LAMBE "
            "(Lambert II extended); the adapter asks for EPSG:2154."
        ),
        resolution="Daily values on a regular 8 km grid (0.072 degrees).",
        period="From 1958-08-01. The service reported an end of 2026-09-17 on 2026-10-09.",
        update=(
            "data.gouv.fr: twice a month for the last four years and daily over a rolling 60 days."
        ),
        authentication="None: the adapter sends no key and the service metadata asks for none.",
        limits="No limit stated in the service metadata.",
        cache=(
            CacheLayout(
                folder="data/<variable>",
                pattern="*_sim2_*.nc",
                format="NetCDF",
                note=(
                    "<record>_sim2_<bbox hash>_<start>_<end>.nc, with the dates as "
                    "YYYYMMDD, in the folder of each of the nine variables SIM2 backs "
                    "(etp, humidity, precipitation, radiation, recharge, runoff, "
                    "soil_moisture, temperature, wind). A variable with components "
                    "writes one file per component, such as precipitation_liquid. "
                    + _WORKSPACE_NOTE
                ),
            ),
        ),
    ),
    SourceEntry(
        slug="shom",
        publisher="SHOM",
        licence=_etalab("Source: Shom, REFMAR sea level observations"),
        basis=(
            "Shom publishes the two REFMAR datasets (the RONIM tide gauges and the "
            "partner tide gauges) on data.gouv.fr under the 'Licence Ouverte / Open "
            "Licence version 2.0'; the service lists gauges of exactly these two networks. "
            "The data.shom.fr support page calls the access to the observations free."
        ),
        hosts=("services.data.shom.fr",),
        licence_pages=(
            "https://www.data.gouv.fr/datasets/reseaux-de-reference-des-observations-maregraphiques-refmar-maregraphes-ronim",
            "https://www.data.gouv.fr/datasets/reseaux-de-reference-des-observations-maregraphiques-refmar-maregraphes-partenaires",
        ),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://services.data.shom.fr/support/en/services/refmar",
            "https://services.data.shom.fr/maregraphie/service/tidegauges",
        ),
        coverage=(
            "The tide gauges of the REFMAR network on the French coasts: 176 gauges "
            "listed by the service on 2026-10-09, 51 of the RONIM network, 124 of REFMAR "
            "partners and one without a network."
        ),
        resolution="Hourly validated sea level, which the adapter asks for with a 60 minute interval.",
        authentication="None: the adapter sends no key.",
        limits="Download by stream is limited to 31 days per request; the adapter chunks by 31 days.",
        cache=(
            CacheLayout(
                folder="data/oceanic",
                pattern="sealevel_shom_*.csv",
                format="CSV",
                note="sealevel_shom_<gauge id>_<start>_<end>_H.csv, one per gauge and period.",
            ),
        ),
    ),
    SourceEntry(
        slug="explore2",
        publisher="Meteo-France, distributed via DRIAS (Explore2-Climat)",
        licence=_etalab("Source: DRIAS, Explore2-Climat"),
        basis=(
            "The DRIAS terms of use state: 'Les données mises à disposition sur les "
            "portails DRIAS-climat et DRIAS-Eau sont couvertes par la licence Etalab', "
            "and link the Etalab v2.0 text. Météo-France publishes and hosts the portal. "
            "The user supplies the file; a licence written in its sidecar overrides this one."
        ),
        licence_pages=("https://www.drias-climat.fr/accompagnement/conditions",),
        licence_checked=LICENCES_CHECKED,
        facts_pages=(
            "https://www.drias-climat.fr/accompagnement/sections/354",
            "https://www.drias-climat.fr/accompagnement/legalnotices",
        ),
        coverage="Metropolitan France.",
        resolution=(
            "Daily values (the reader sets the frequency to D) on an 8 km grid in "
            "EPSG:27572, bias-corrected on the SAFRAN analysis with the ADAMONT and "
            "CDF-t methods. The reader resamples to a regular 8 km grid in the model CRS."
        ),
        period="1976 to 2100 (historical simulations and projections).",
        authentication=(
            "None by HydroModPy: it reads a local file and contacts no host. The DRIAS "
            "portal shows a login form; whether the download needs an account was not "
            "established."
        ),
        cache=(
            CacheLayout(
                folder="data/<variable>",
                pattern="*_explore2_*.nc",
                format="NetCDF",
                note=(
                    "<variable>_explore2_<bbox hash>_<start>_<end>.nc in the folders "
                    "precipitation and etp. The source file stays where the user keeps it. "
                    + _WORKSPACE_NOTE
                ),
            ),
        ),
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
        if entry.slug in table:
            raise ValueError(f"source slug {entry.slug!r} is declared twice")
        table[entry.slug] = entry
    return MappingProxyType(table)


SOURCES: Mapping[str, SourceEntry] = _index(_ENTRIES)
"""Every known slug, mapped to its entry."""


def source_entry(slug: str | None) -> SourceEntry | None:
    """Return the entry of *slug*, or ``None`` when it is not known here."""
    if not slug:
        return None
    return SOURCES.get(str(slug).strip())


def sources_by_publisher() -> Mapping[str, tuple[SourceEntry, ...]]:
    """Group the entries by publisher, for a page that answers "who feeds what".

    A source without a publisher (a user file, a generated value) is left out.
    """
    groups: dict[str, list[SourceEntry]] = {}
    for entry in SOURCES.values():
        if entry.publisher:
            groups.setdefault(entry.publisher, []).append(entry)
    return MappingProxyType({name: tuple(items) for name, items in sorted(groups.items())})


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
    "CACHE_INDEX",
    "COPERNICUS_LICENCE_ID",
    "LICENCES_CHECKED",
    "SIDECAR_SUFFIX",
    "SOURCES",
    "CacheLayout",
    "SourceEntry",
    "derived_licence",
    "input_licence",
    "is_determined",
    "licence_for_source",
    "licence_from_sidecar",
    "sidecar_path",
    "source_entry",
    "sources_by_publisher",
]
