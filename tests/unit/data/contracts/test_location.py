"""Station location: x, y in the CRS of the file, and free metadata that must write to JSON."""

import json

import numpy as np

from hydromodpy.data.contracts.location import StationLocation


def test_to_dict():
    loc = StationLocation(id="A", x=1.0, y=2.0, crs="EPSG:2154", metadata={"name": "Test"})

    d = loc.to_dict()

    assert d["id"] == "A"
    assert d["name"] == "Test"


def test_numpy_metadata_writes_to_json():
    metadata = {"influence": np.int64(1), "active": np.bool_(True), "altitude": np.float64(1.5)}

    loc = StationLocation(id="A", x=1.0, y=2.0, crs="EPSG:2154", metadata=metadata)

    assert json.loads(json.dumps(loc.to_dict()))["influence"] == 1
    assert type(loc.metadata["influence"]) is int
    assert type(loc.metadata["active"]) is bool
