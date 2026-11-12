"""``INSTALL.toml`` is one format for an example, a published run and an exported project.

Each file is named by its destination, its size and its sha256, the keys of
``[[example.file]]``; a file of a package also says its variable, provider,
request, licence, sidecar digest and data cache row. Each station row is a
``[[station]]`` like ``[[example.station]]``, each site a row of the site
catalog. The document carries its schema, and a reader refuses another one.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.payload.index import (
    InstallIndex,
    PayloadFile,
    PayloadStation,
    read_index,
    write_index,
)
from hydromodpy.core.site.row import SiteRow

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


def test_unknown_root_is_refused(tmp_path) -> None:
    written = write_index(tmp_path, _index())
    written.write_text(
        written.read_text(encoding="utf-8").replace("size = 1234", "size = 1234\nroot = 'moon'", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="root is 'moon'"):
        read_index(tmp_path)
