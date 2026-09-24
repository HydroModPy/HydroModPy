"""A data source states a licence only when its basis is written down.

The registry replaced a ``CC-BY-4.0`` literal nobody chose. Each claim it
makes is a legal statement about somebody else's data, so the set of claims is
pinned here: adding one is a deliberate change of this test, reviewed with
its basis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.data.provenance.sidecars import SIDECAR_SUFFIX as DATA_SIDECAR_SUFFIX
from hydromodpy.schema.job.inputset import UNDETERMINED, Licence
from hydromodpy.schema.sources import (
    SIDECAR_SUFFIX,
    SOURCES,
    derived_licence,
    input_licence,
    licence_for_source,
    licence_from_sidecar,
)

ETALAB = Licence(spdx="etalab-2.0", confidence="assumed")
ODBL = Licence(spdx="ODbL-1.0", share_alike=True, confidence="assumed")


def _sidecar(path: Path, **payload: object) -> None:
    path.with_name(path.name + SIDECAR_SUFFIX).write_text(json.dumps(payload), encoding="utf-8")


def test_the_claims_are_the_reviewed_ones() -> None:
    claims = {
        slug: entry.licence.spdx
        for slug, entry in SOURCES.items()
        if entry.licence.spdx != UNDETERMINED_LICENSE
    }
    assert claims == {
        "brgm_1m": "etalab-2.0",
        "brgm_50k": "etalab-2.0",
        "ign_geoplateforme_dem": "etalab-2.0",
        "ign-bdalti": "etalab-2.0",
        "osm": "ODbL-1.0",
    }


@pytest.mark.parametrize("slug", sorted(SOURCES))
def test_every_entry_says_why(slug: str) -> None:
    entry = SOURCES[slug]
    assert entry.basis.strip()
    if entry.licence.spdx == UNDETERMINED_LICENSE:
        assert entry.licence.confidence == "undetermined"
    else:
        assert entry.licence.confidence == "assumed"
        assert entry.licence.url


def test_the_code_slugs_are_all_known() -> None:
    written_by_the_code = {
        "bdtopage",
        "brgm_1m",
        "brgm_50k",
        "constant",
        "custom",
        "euhydro",
        "hubeau",
        "ign_geoplateforme_dem",
        "osm",
        "shom",
        "sim2",
        "synthetic",
    }
    port_ids = {"ign-bdalti", "hubeau-piezometry", "sim2-precipitation"}
    assert written_by_the_code | port_ids <= set(SOURCES)


def test_an_unknown_source_is_undetermined() -> None:
    assert licence_for_source("somebody_elses_api") == UNDETERMINED
    assert licence_for_source(None) == UNDETERMINED


def test_osm_is_share_alike() -> None:
    assert licence_for_source("osm").share_alike is True


def test_the_sidecar_suffix_is_the_data_one() -> None:
    assert SIDECAR_SUFFIX == DATA_SIDECAR_SUFFIX


def test_a_declared_sidecar_licence_wins_over_the_registry() -> None:
    licence = licence_from_sidecar({"source": "custom", "license": "CC0-1.0"})
    assert licence.spdx == "CC0-1.0"
    assert licence.confidence == "declared"


def test_a_sidecar_written_before_the_registry_uses_its_source() -> None:
    assert licence_from_sidecar({"source": "brgm_1m", "license": None}).spdx == "etalab-2.0"
    assert licence_from_sidecar({"source": "custom", "license": UNDETERMINED_LICENSE}) == (
        UNDETERMINED
    )


def test_a_file_without_sidecar_is_undetermined(tmp_path: Path) -> None:
    data = tmp_path / "dem.tif"
    data.write_bytes(b"x")
    assert input_licence(data) == UNDETERMINED


def test_a_directory_needs_a_sidecar_on_every_file(tmp_path: Path) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("1")
    second.write_text("2")
    _sidecar(first, source="brgm_1m", license="etalab-2.0")
    assert input_licence(tmp_path) == UNDETERMINED
    _sidecar(second, source="custom", license="etalab-2.0")
    assert input_licence(tmp_path).spdx == "etalab-2.0"


def test_a_run_is_never_more_open_than_its_least_known_input() -> None:
    assert derived_licence([]) == UNDETERMINED_LICENSE
    assert derived_licence([ETALAB, UNDETERMINED]) == UNDETERMINED_LICENSE
    assert derived_licence([ETALAB, ETALAB]) == "etalab-2.0"
    assert derived_licence([ETALAB, ODBL]) == "ODbL-1.0 AND etalab-2.0"
