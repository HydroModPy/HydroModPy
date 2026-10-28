"""``[geographic.synthetic]``: the grid of the analytical support and its topography laws."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.synthetic import (
    RadialIslandTopography,
    SyntheticGeographicConfig,
    SyntheticGridConfig,
)


def test_grid_lengths_accept_unit_strings_and_derive_cell_size() -> None:
    grid = SyntheticGridConfig(length_x="0.1 km", length_y="2 m", nx=100, ny=2)

    assert (grid.ncol, grid.nrow, grid.dx, grid.dy) == (100, 2, 1.0, 1.0)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (
            lambda: SyntheticGeographicConfig.model_validate(
                {
                    "topography": {
                        "kind": "flat",
                        "base_elevation": 20.0,
                        "right_to_left_amplitude": 0.0,
                    }
                }
            ),
            "right_to_left_amplitude",
        ),
        (lambda: SyntheticGridConfig(length_x="10 m", length_y="10 m", nx=2, ny=5), "square cells"),
        (lambda: RadialIslandTopography(island_radius="0 m"), "island_radius must be > 0"),
        (lambda: RadialIslandTopography(crest_elevation=0.0), "crest_elevation must be > 0"),
        (lambda: RadialIslandTopography(base_elevation=1.0), "base_elevation must be < 0"),
    ],
    ids=["cross-variant-field", "rectangular-cells", "radius", "crest", "base-above-the-sea"],
)
def test_a_synthetic_support_that_cannot_be_built_is_refused(build, match) -> None:
    with pytest.raises(ValidationError, match=match):
        build()


def test_a_synthetic_section_reads_from_its_toml_table(tmp_path) -> None:
    path = tmp_path / "synthetic.toml"
    path.write_text(
        '[synthetic_geographic]\ncase_id = "island"\n'
        '[synthetic_geographic.grid]\nlength_x = "40 m"\nlength_y = "20 m"\nnx = 4\nny = 2\n',
        encoding="utf-8",
    )

    config = SyntheticGeographicConfig.from_toml(path)

    assert config.case_id == "island"
    assert (config.grid.ncol, config.grid.dx) == (4, 10.0)
