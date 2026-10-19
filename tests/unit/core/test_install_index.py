"""``INSTALL.toml`` is one format for an example, a published run and an exported project.

Each file is named by its destination, its size and its sha256, the keys of
``[[example.file]]``; a file of a package also says its variable, provider,
request, licence, sidecar digest and data cache row. Each station row is a
``[[station]]`` like ``[[example.station]]``, each site a row of the site
catalog. The document carries its schema, and a reader refuses another one.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.payload import (
    INSTALL_FILENAME,
    INSTALL_SCHEMA,
    InstallIndex,
    PayloadFile,
    PayloadStation,
    read_index,
    stored_name,
    write_index,
)
from hydromodpy.core.site import SiteRow

STATION_FILE = PayloadFile(
    dest="data/hydrometry/hydrometry_hubeau_J0014010_20000101_20021231_D.csv",
    size=1234,
    sha256="a" * 64,
    variable="hydrometry",
    provider="hubeau",
    license="etalab-2.0",
    sidecar_sha256="b" * 64,
    request={"station": "J0014010", "period": ["2000-01-01T00:00:00", None]},
    cache={
        "variable": "hydrometry",
        "source": "hubeau",
        "station_id": "J0014010",
        "bbox": [389285.9, 6816518.7, 389285.9, 6816518.7],
        "fetch_metadata": {"asked_window": ["2000-01-01T00:00:00", "2002-12-31T00:00:00"]},
    },
)


def _index() -> InstallIndex:
    return InstallIndex(
        files=(
            STATION_FILE,
            PayloadFile(dest="step1_minimal.toml", size=10, sha256="c" * 64, root="project"),
        ),
        stations=(
            PayloadStation(
                dest="data/hydrometry/hydrometry_hubeau_LOC.csv",
                row=(("id", "J0014010"), ("x", "389285.9"), ("y", "6816518.7")),
            ),
        ),
        sites=(SiteRow(site="nancon", gauge="J0014010", x_outlet=389285.9, y_outlet=6816518.7),),
    )


def test_the_index_reads_back_what_it_wrote(tmp_path) -> None:
    written = _index()

    path = write_index(tmp_path, written)
    read = read_index(tmp_path)

    assert path.name == INSTALL_FILENAME
    assert read.files == written.files
    assert read.files[0].request == {"station": "J0014010", "period": ["2000-01-01T00:00:00", ""]}
    assert read.files[0].cache == STATION_FILE.cache
    assert read.stations == written.stations
    assert read.sites == written.sites
    assert read.file_at("step1_minimal.toml", root="project") is not None


def test_a_file_carries_the_keys_of_an_example_file(tmp_path) -> None:
    write_index(tmp_path, _index())
    text = (tmp_path / INSTALL_FILENAME).read_text(encoding="utf-8")

    assert f'schema = "{INSTALL_SCHEMA}"' in text
    assert "[[file]]" in text and "[[station]]" in text and "[[site]]" in text
    assert 'dest = "data/hydrometry/hydrometry_hubeau_J0014010_20000101_20021231_D.csv"' in text
    assert "repo_path" not in text
    assert stored_name("a" * 64, STATION_FILE.dest) == "a" * 64 + ".csv"


def test_an_unknown_key_of_a_file_is_refused_by_name(tmp_path) -> None:
    write_index(tmp_path, _index())
    path = tmp_path / INSTALL_FILENAME
    path.write_text(
        path.read_text(encoding="utf-8").replace("size = 1234", "size = 1234\nowner = 'me'", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown key"):
        read_index(tmp_path)


def test_an_index_of_another_schema_is_refused_by_name(tmp_path) -> None:
    write_index(tmp_path, _index())
    path = tmp_path / INSTALL_FILENAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(INSTALL_SCHEMA, "hydromodpy.install.v2"),
        encoding="utf-8",
    )

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.install.v2"):
        read_index(tmp_path)
