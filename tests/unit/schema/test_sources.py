"""Registry of data sources: licence claims, where each source caches files, how it is reached.

A licence claim is a legal statement about somebody else's data, so the set of
claims is pinned here and each carries its basis. The cache layout of a source is
held against real file names built by the data package, which ``schema`` may not
import.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.data.families.stations import _VAR_FILE_PREFIX
from hydromodpy.data.provenance.sidecars import SIDECAR_SUFFIX as DATA_SIDECAR_SUFFIX
from hydromodpy.data.variables.oceanic.apis.shom import _cache_file as shom_name
from hydromodpy.schema.job.inputset import UNDETERMINED, Licence
from hydromodpy.schema.sources import (
    COPERNICUS_LICENCE_ID,
    LICENCES_CHECKED,
    SIDECAR_SUFFIX,
    SOURCES,
    derived_licence,
    input_licence,
    licence_for_source,
    licence_from_sidecar,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ETALAB = Licence(spdx="etalab-2.0", confidence="assumed")
ODBL = Licence(spdx="ODbL-1.0", share_alike=True, confidence="assumed")
CLAIMED = sorted(
    slug for slug, entry in SOURCES.items() if entry.licence.spdx != UNDETERMINED_LICENSE
)


def cache_layouts(slug: str) -> dict:
    return {layout.folder: layout for layout in SOURCES[slug].cache}


def test_reviewed_claims() -> None:
    claims = {slug: SOURCES[slug].licence.spdx for slug in CLAIMED}

    assert claims == {
        "bdtopage": "etalab-2.0",
        "bdtopo": "etalab-2.0",
        "brgm_1m": "etalab-2.0",
        "brgm_50k": "etalab-2.0",
        "euhydro": COPERNICUS_LICENCE_ID,
        "explore2": "etalab-2.0",
        "hubeau": "etalab-2.0",
        "ign_geoplateforme_dem": "etalab-2.0",
        "osm": "ODbL-1.0",
        "roe": "etalab-2.0",
        "shom": "etalab-2.0",
        "sim2": "etalab-2.0",
    }


def test_undetermined_sources() -> None:
    undetermined = {slug for slug in SOURCES if slug not in CLAIMED}
    assert undetermined == {"file", "url", "constant", "synthetic"}


def test_licence_ref_only_without_spdx_id() -> None:
    refs = {
        slug: SOURCES[slug].licence.spdx
        for slug in CLAIMED
        if SOURCES[slug].licence.spdx.startswith("LicenseRef-")
    }
    assert refs == {"euhydro": COPERNICUS_LICENCE_ID}


@pytest.mark.parametrize("slug", sorted(SOURCES))
def test_entry_has_a_basis(slug: str) -> None:
    entry = SOURCES[slug]
    assert entry.basis.strip()
    if entry.licence.spdx == UNDETERMINED_LICENSE:
        assert entry.licence.confidence == "undetermined"
        assert not entry.licence_pages
    else:
        assert entry.licence.confidence == "assumed"
        assert entry.licence.url


@pytest.mark.parametrize("slug", CLAIMED)
def test_claim_has_page_and_date(slug: str) -> None:
    entry = SOURCES[slug]
    assert entry.licence_pages
    assert all(page.startswith("https://") for page in entry.licence_pages)
    assert entry.licence_checked == LICENCES_CHECKED
    assert date.fromisoformat(entry.licence_checked)
    assert entry.licence.attribution


def test_downloads_state_authentication() -> None:
    for slug, entry in SOURCES.items():
        if entry.hosts:
            assert entry.authentication, slug


def test_entry_document() -> None:
    document = SOURCES["sim2"].to_document()

    json.dumps(document)
    assert document["licence"]["spdx"] == "etalab-2.0"
    assert document["cache"][0]["folder"] == "data/<variable>"


def test_code_slugs_are_known() -> None:
    written_by_the_code = {
        "bdtopage",
        "bdtopo",
        "brgm_1m",
        "brgm_50k",
        "constant",
        "euhydro",
        "file",
        "hubeau",
        "ign_geoplateforme_dem",
        "osm",
        "roe",
        "shom",
        "sim2",
        "synthetic",
    }
    assert written_by_the_code <= set(SOURCES)


def test_unknown_source() -> None:
    assert licence_for_source("somebody_elses_api") == UNDETERMINED
    assert licence_for_source(None) == UNDETERMINED


def test_sidecar_suffix() -> None:
    assert SIDECAR_SUFFIX == DATA_SIDECAR_SUFFIX


def test_old_sidecar_uses_source() -> None:
    assert licence_from_sidecar({"source": "brgm_1m", "license": None}).spdx == "etalab-2.0"
    assert licence_from_sidecar({"source": "file", "license": UNDETERMINED_LICENSE}) == UNDETERMINED


def test_directory_sidecars(tmp_path: Path) -> None:
    def write_sidecar(path: Path, **payload: object) -> None:
        path.with_name(path.name + SIDECAR_SUFFIX).write_text(json.dumps(payload), encoding="utf-8")

    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("1")
    second.write_text("2")
    write_sidecar(first, source="brgm_1m", license="etalab-2.0")
    assert input_licence(tmp_path) == UNDETERMINED
    write_sidecar(second, source="file", license="etalab-2.0")
    assert input_licence(tmp_path).spdx == "etalab-2.0"


def test_derived_licence() -> None:
    assert derived_licence([]) == UNDETERMINED_LICENSE
    assert derived_licence([ETALAB, UNDETERMINED]) == UNDETERMINED_LICENSE
    assert derived_licence([ETALAB, ETALAB]) == "etalab-2.0"
    assert derived_licence([ETALAB, ODBL]) == "ODbL-1.0 AND etalab-2.0"


def test_shom_gauge_file_name() -> None:
    gauge_file = shom_name(Path("cache"), "300", datetime(2020, 1, 1), datetime(2020, 12, 31))
    assert fnmatch(gauge_file.name, cache_layouts("shom")["data/oceanic"].pattern)


def test_station_file_name() -> None:
    layouts = cache_layouts("hubeau")
    variables = ("hydrometry", "piezometry", "intermittency", "water_quality")

    assert set(layouts) == {f"data/{variable}" for variable in variables}
    for variable in variables:
        prefix = _VAR_FILE_PREFIX.get(variable, variable)
        name = f"{prefix}_hubeau_ABC_20200101_20201231_D.csv"
        assert fnmatch(name, layouts[f"data/{variable}"].pattern)


# Names built inline in a module that no function exposes, so the literal is searched in its text.
INLINE_NAMES = [
    pytest.param(
        "hydromodpy/data/variables/geology/apis/brgm_1m.py",
        "brgm_1m",
        "data/geology",
        "geology_brgm_1m_",
        id="brgm 1m",
    ),
    pytest.param(
        "hydromodpy/data/variables/geology/apis/brgm_50k.py",
        "brgm_50k",
        "data/geology",
        "geology_brgm_50k_",
        id="brgm 50k",
    ),
    pytest.param(
        "hydromodpy/data/variables/dem/apis/ign_dem_fr.py",
        "ign_geoplateforme_dem",
        "data/dem/processed",
        "dem_ign_geoplateforme_",
        id="ign dem",
    ),
]


@pytest.mark.parametrize(("module", "slug", "folder", "literal"), INLINE_NAMES)
def test_inline_cache_names(module: str, slug: str, folder: str, literal: str) -> None:
    assert literal in (REPO_ROOT / module).read_text(encoding="utf-8")
    assert cache_layouts(slug)[folder].pattern.startswith(literal)


def test_layouts_under_data() -> None:
    for entry in SOURCES.values():
        for layout in entry.cache:
            assert layout.folder.startswith("data/")


def test_no_layout_without_files() -> None:
    for slug in ("file", "url", "constant", "synthetic"):
        assert SOURCES[slug].cache == ()
