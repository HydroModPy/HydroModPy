![logo](https://github.com/HydroModPy/HydroModPy/blob/61d654ca738c488480fd22aa01c2b1002984eac9/docs/readthedocs/source/images/logoHydroModPy_long.png)

**HydroModPy** is a Python toolbox for deploying catchment-scale shallow
groundwater models. One TOML config drives MODFLOW 6, MODFLOW-NWT, Boussinesq
and GR4J on the same hydrology, with reproducible inputs and ML-friendly
outputs.

[![PyPI](https://img.shields.io/pypi/v/hydromodpy.svg)](https://pypi.org/project/hydromodpy/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: EPL-2.0](https://img.shields.io/badge/license-EPL--2.0-green.svg)](https://opensource.org/licenses/EPL-2.0)
[![CI](https://github.com/HydroModPy/HydroModPy/actions/workflows/main-ci.yml/badge.svg?branch=main)](https://github.com/HydroModPy/HydroModPy/actions/workflows/main-ci.yml?query=branch%3Amain)
[![Documentation](https://github.com/HydroModPy/HydroModPy/actions/workflows/docs-deploy-pages.yml/badge.svg?branch=main)](https://docs.hydromodpy.fr/main/)
[![Codecov](https://codecov.io/gh/HydroModPy/HydroModPy/branch/main/graph/badge.svg)](https://codecov.io/gh/HydroModPy/HydroModPy/tree/main)
[![Paper](https://img.shields.io/badge/HESS-10.5194%2Fhess--30--5571--2026-f59e0b.svg)](https://doi.org/10.5194/hess-30-5571-2026)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22141925.svg)](https://doi.org/10.5281/zenodo.22141925)

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

`2.0.0a1` misses `whitebox-workflows` in its dependencies, and
`build_geographic` fails without it. On that release, add it by hand:

```bash
pip install whitebox-workflows==1.3.5
```

Optional extras: `[ide]`, `[test]`, `[viewer3d]`, `[docs]`. Solver binaries
(MODFLOW 6, MODFLOW-NWT, MODPATH, MT3D-USGS) are downloaded on demand into
`~/.cache/hydromodpy/bin/` on first solver run, or eagerly with
`hmp install-binaries`.

For developer install, conda recipes, Windows + WSL setup and the PETSc
backend, see the [installation guide](https://docs.hydromodpy.fr/main/get-started/install.html).

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
`runs/demo/tables.parquet/metrics.parquet` works too. See
[Reading the results](https://docs.hydromodpy.fr/main/understand/reading-results.html)
and the [Python API](https://docs.hydromodpy.fr/main/reference/python/index.html)
for the full reading and export path.

## Documentation

Full documentation lives at
**[docs.hydromodpy.fr](https://docs.hydromodpy.fr/main/)**.

| Section | What it covers |
|---------|----------------|
| [Understand](https://docs.hydromodpy.fr/main/understand/index.html) | What the model computes and how to read its maps, in plain words. |
| [Get started](https://docs.hydromodpy.fr/main/get-started/index.html) | Install, then example 04 file by file. |
| [Reference](https://docs.hydromodpy.fr/main/reference/index.html) | Every TOML parameter, every `hmp` command and the Python API, generated from the code. |
| [Theory](https://docs.hydromodpy.fr/main/theory/index.html) | The equations, their assumptions and limits, and the validation against references. |
| [Contribute](https://docs.hydromodpy.fr/main/contribute/index.html) | Contributor handbook, layer matrix, storage layout, package maps. |

## Contributing

Bug reports, feature requests and pull requests are welcome. See
[CONTRIBUTING.md](https://github.com/HydroModPy/HydroModPy/blob/main/CONTRIBUTING.md) for the short version and the
[contributor guide](https://docs.hydromodpy.fr/main/contribute/handbook.html)
for the full reference. Released versions are listed in
[CHANGELOG.md](https://github.com/HydroModPy/HydroModPy/blob/main/CHANGELOG.md).

Security issues: please follow [SECURITY.md](https://github.com/HydroModPy/HydroModPy/blob/main/SECURITY.md) and use a private
advisory rather than a public issue.

## How to cite

If HydroModPy supports your work, please cite the technical note below. If you
also cite the software, give the version you ran and its Zenodo DOI. The concept
DOI [10.5281/zenodo.22141925](https://doi.org/10.5281/zenodo.22141925) names
every version and resolves to the latest archive; each archived version has its
own DOI on that page. Full BibTeX, RIS and plain-text entries are on the
[citation page](https://docs.hydromodpy.fr/main/about/cite.html);
GitHub renders the "Cite this repository" button from
[`CITATION.cff`](https://github.com/HydroModPy/HydroModPy/blob/main/CITATION.cff).

<!-- The dash belongs to the published title. -->
<!-- vale off -->
> Gauvain, A., Abhervé, R., Boivin, B., Coche, A., Le Mesnil, M., Babey, T.,
> Maugan, E., Touzeau, T., Issolah, I., Roques, C., Bouchez, C., Marçais, J.,
> Leray, S., Marti, E., Bresciani, E., Figueroa, R., Pélissier, M., Carlier, S.,
> Guillaumot, L., Bagagnan, R. S., Vautier, C., Longuevergne, L., Sallou, J.,
> Bourcier, J., Combemale, B., Brunner, P., Aquilina, L., & de Dreuzy, J.-R.
> (2026). Technical note: HydroModPy (v1.0) – a Python toolbox for deploying
> catchment-scale shallow groundwater models. *Hydrology and Earth System
> Sciences*, 30(17), 5571–5592. <https://doi.org/10.5194/hess-30-5571-2026>
<!-- vale on -->

## Authors and contact

HydroModPy is developed by Geosciences Rennes (Université de Rennes, CNRS)
together with collaborators at CHYN Neuchâtel, INRAE, Pontificia Universidad
Católica de Chile, Universidad de O'Higgins, BRGM, WUR, Université de Pau et
des Pays de l'Adour, Inria/IRISA and CNRS-LMD. The complete author list is
maintained in
[`CITATION.cff`](https://github.com/HydroModPy/HydroModPy/blob/main/CITATION.cff);
the affiliations are on the
[citation page](https://docs.hydromodpy.fr/main/about/cite.html).

For questions or collaboration: <alexandre.gauvain.ag@gmail.com> or
<ronan.abherve@inrae.fr>.

## License

HydroModPy is released under the [Eclipse Public License 2.0](https://opensource.org/licenses/EPL-2.0).
See [LICENSE](https://github.com/HydroModPy/HydroModPy/blob/main/LICENSE).
