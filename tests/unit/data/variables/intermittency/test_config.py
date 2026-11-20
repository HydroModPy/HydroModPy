"""Source settings of the intermittency variable (ONDE flow states)."""

import pytest

from hydromodpy.data.variables.intermittency.config import IntermittencySourceConfig

pytestmark = pytest.mark.fast


def test_a_file_source_requires_a_path():
    with pytest.raises(ValueError, match="path"):
        IntermittencySourceConfig(source="file")
