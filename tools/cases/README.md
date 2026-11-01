# Demos run by hand

These scripts build one part of a model from a TOML file and draw it for a visual check. They
live outside the `hydromodpy` package: no code of the library imports them, the wheel does not
ship them, and they write their figures in an `outputs/` folder next to them, which git
ignores. Each one runs from the repository root with `python -m`.

| folder | what it shows | launcher |
|---|---|---|
| `domain/` | a Domain built from a project TOML: top, substratum, thickness, zones | `python -m tools.cases.domain.review_cases` |
| `field/` | a field parameter on the unit square, on regular and triangle meshes | `python -m tools.cases.field.review_cases` |
| `geographic/` | catchments from an outlet or a polygon, and an extracted river network | `python -m tools.cases.geographic.review_cases` |
| `geographic/synthetic/` | a synthetic DEM, its 3D view and a profile | `python -m tools.cases.geographic.synthetic.run_geographic_synthetic_case` |
| `geology/` | a conductivity mapped from the Brittany geology onto a mesh | `python -m tools.cases.geology.run_geology_property_case` |
| `intermittency/` | the ONDE observations of three stations, as a JSON summary | `python -m tools.cases.intermittency.run_intermittency_case` |
| `oceanic/` | a local sea level series, as a JSON summary | `python -m tools.cases.oceanic.run_oceanic_case` |

`plotting_utils.py` holds the window helpers that the domain, field and geographic demos share.
The TOML paths are relative to the folder of the TOML. They point into `examples/data/`, except
the intermittency and oceanic ones, which read the small files of their golden tests in
`tests/unit/data_managers/`.
`tests/contract/test_case_review_contract.py` checks the three review launchers and that every
path of these TOML files exists. The other tests of the demos are in `tests/unit/tools/cases/`.
