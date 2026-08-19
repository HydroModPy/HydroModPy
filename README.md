![logo](https://github.com/HydroModPy/HydroModPy/blob/61d654ca738c488480fd22aa01c2b1002984eac9/docs/readthedocs/source/images/logoHydroModPy_long.png)

**HydroModPy** is a Python toolbox for deploying catchment-scale shallow
groundwater models. One TOML config drives MODFLOW 6, MODFLOW-NWT, Boussinesq
and GR4J on the same hydrology, with reproducible inputs and ML-friendly
outputs.

[![PyPI](https://img.shields.io/pypi/v/hydromodpy.svg)](https://pypi.org/project/hydromodpy/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: EPL-2.0](https://img.shields.io/badge/license-EPL--2.0-green.svg)](https://opensource.org/licenses/EPL-2.0)
[![CI](https://github.com/HydroModPy/HydroModPy/actions/workflows/main-ci.yml/badge.svg?branch=main)](https://github.com/HydroModPy/HydroModPy/actions/workflows/main-ci.yml?query=branch%3Amain)
[![Documentation](https://readthedocs.org/projects/hydromodpy-docs/badge/?version=main)](https://hydromodpy-docs.readthedocs.io/en/main/)
[![Codecov](https://codecov.io/gh/HydroModPy/HydroModPy/branch/main/graph/badge.svg)](https://codecov.io/gh/HydroModPy/HydroModPy/tree/main)

## What you get

- **One config, four solvers.** A single `HydroModPyConfig` (Pydantic v2)
  drives MODFLOW 6, MODFLOW-NWT, Boussinesq and GR4J on the same catchment.
- **Disk is the truth.** Every run is one plain directory under `runs/`,
  named after the run. The DuckDB file in `.hmp/` is only an index over
  those directories: delete it and `hmp catalog reindex` rebuilds it.
- **Standard formats, no container.** Field arrays in Zarr, tables in
  Parquet, the frozen config in TOML, the seal and the provenance in JSON.
  `pandas`, `xarray` and `zarr` read a run without HydroModPy installed.
- **Reproducibility.** A frozen `hydromodpy.lock` pins the input data, and
  each run stores its own `provenance.json`: Python version, package
  versions, git commit, host, solver binary and its SHA-256.

## Install

```bash
pip install --pre hydromodpy
```

The current `main` documentation targets the v2 alpha line. Use
`pip install hydromodpy` only when you want the latest stable release.

Optional extras: `[ide]`, `[test]`, `[viewer3d]`, `[docs]`. Solver binaries
(MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS) are downloaded on demand into
`~/.cache/hydromodpy/bin/` on first solver run, or eagerly with
`hmp install-binaries`.

For developer install, conda recipes, Windows + WSL setup and the PETSc
backend, see the [installation guide](https://hydromodpy-docs.readthedocs.io/en/main/install.html).

## Quickstart

Scaffold a workspace, create a project, run it. `hmp project new` writes
both a `project.toml` with the shared settings and a ready-to-run
`run_demo.toml` on a small synthetic catchment.

```bash
hmp workspace init .
hmp project new getting_started --workspace .
hmp run projects/getting_started/run_demo.toml
```

The run lands in its own directory inside the project:

```text
projects/getting_started/
├── project.toml                  shared settings, and the marker of the project root
├── run_demo.toml                 the run you launched
├── hydromodpy.lock               frozen input data
├── runs/
│   └── demo/                     one directory per run, named after the run
│       ├── config.toml           frozen resolved configuration
│       ├── fields.zarr/          field arrays (head, mesh, forcings, ...)
│       ├── tables.parquet/       metrics, parameters, budgets, timeseries
│       ├── figures/              figures rendered for this run
│       ├── manifest.json         seal, written last
│       └── provenance.json       versions, git commit, solver binary
└── .hmp/                         internals: index.duckdb, logs, checkpoints
```

`figures/` appears once a figure is rendered, and a tagged run also carries
an `annotations.json`. On-demand exports and reports go to `share/`,
calibration sessions to `sessions/`.

Browse it from the command line:

```bash
hmp catalog ls                    # every run of the project
hmp catalog show demo --detail    # metadata, metrics, parameters, store layout
hmp viz show demo piezometric_map # render one figure into runs/demo/figures/
```

Or read it from Python:

```python
import hydromodpy as hmp

catalog = hmp.open("projects/getting_started")
run = catalog.latest()

head = hmp.read(run, "head")  # lazy xarray.DataArray
water_table = hmp.read(run, "watertable_elevation", time=-1)  # numpy array
```

The tables are plain Parquet, so `pandas.read_parquet` on
`runs/demo/tables.parquet/metrics.parquet` works too. See the
[results guide](https://hydromodpy-docs.readthedocs.io/en/main/user_guide/results-and-exports.html)
for the full reading and export path.

## Documentation

Full documentation lives at
**[hydromodpy-docs.readthedocs.io](https://hydromodpy-docs.readthedocs.io/en/main/)**.

| Section | What it covers |
|---------|----------------|
| [Get started](https://hydromodpy-docs.readthedocs.io/en/main/getting_started/index.html) | Install, scaffold, first run end to end. |
| [User Guide](https://hydromodpy-docs.readthedocs.io/en/main/user_guide/index.html) | Workflows, configuration, theory, cookbook. |
| [Configuration](https://hydromodpy-docs.readthedocs.io/en/main/user_guide/config_reference/index.html) | Every TOML section validated by `HydroModPyConfig`. |
| [CLI](https://hydromodpy-docs.readthedocs.io/en/main/cli/index.html) | Every `hmp` verb, its sub-actions, and the typed exit codes. |
| [Gallery](https://hydromodpy-docs.readthedocs.io/en/main/capability_gallery/index.html) | Validation figures, mesh illustrations, watershed diagnostics. |
| [API Reference](https://hydromodpy-docs.readthedocs.io/en/main/api/index.html) | Auto-generated reference for every public class and module. |
| [Architecture](https://hydromodpy-docs.readthedocs.io/en/main/architecture/index.html) | Layer matrix, module diagrams, contributor maps. |

## Contributing

Bug reports, feature requests and pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the short version and the
[contributor guide](https://hydromodpy-docs.readthedocs.io/en/main/contribute.html)
for the full reference. Released versions are listed in
[CHANGELOG.md](CHANGELOG.md).

Security issues: please follow [SECURITY.md](SECURITY.md) and use a private
advisory rather than a public issue.

## How to cite

If HydroModPy supports your work, please cite the software and the companion
paper. Full BibTeX, RIS and plain-text entries are on the
[citation page](https://hydromodpy-docs.readthedocs.io/en/main/how_to_cite.html);
GitHub renders the "Cite this repository" button from
[`CITATION.cff`](CITATION.cff).

> Gauvain, A., Abhervé, R., Boivin, B., Roques, C., Le Mesnil, M., Coche, A.,
> Babey, T., Marçais, J., Bouchez, C., Leray, S., Marti, E., Bresciani, E.,
> Figueroa, R., Pélissier, M., Guillaumot, L., Touzeau, T., Issolah, I.,
> Maugan, E., Bagagnan, R. S., Vautier, C., Sallou, J., Bourcier, J.,
> Combemale, B., Brunner, P., Longuevergne, L., Aquilina, L., & de Dreuzy, J.-R.
> (2026). Technical note: HydroModPy – a Python toolbox for deploying
> catchment-scale shallow groundwater models. *EGUsphere* [preprint], 1–31.
> <https://doi.org/10.5194/egusphere-2026-868>

## Authors and contact

HydroModPy is developed by Geosciences Rennes (Université de Rennes, CNRS)
together with collaborators at CHYN Neuchâtel, INRAE, Pontificia Universidad
Católica de Chile, Universidad de O'Higgins, WUR, Inria/IRISA and CNRS-LMD.
The complete author list with affiliations is maintained in
[`CITATION.cff`](CITATION.cff).

For questions or collaboration: <alexandre.gauvain.ag@gmail.com> or
<ronan.abherve@gmail.com>.

## License

HydroModPy is released under the [Eclipse Public License 2.0](https://opensource.org/licenses/EPL-2.0).
See [LICENSE](LICENSE).
