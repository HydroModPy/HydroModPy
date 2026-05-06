"""Guard against opaque payloads in the root configuration schema."""

from hydromodpy.config import HydroModPyConfig
from tools.doc_config.coverage import INTENTIONALLY_OPAQUE_PATHS, _walk_opaque_fields


def test_no_opaque_dicts_in_root_schema() -> None:
    opaque_fields = [
        (path, annotation)
        for path, annotation in _walk_opaque_fields(HydroModPyConfig, section_path="")
        if path not in INTENTIONALLY_OPAQUE_PATHS
    ]

    assert opaque_fields == []
