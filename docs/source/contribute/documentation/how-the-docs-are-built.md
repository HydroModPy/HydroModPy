# How the docs are built

The site is a Sphinx 9 project in `docs/source/`, with the PyData theme 0.23
and MyST 5.1. Pages come from three places: pages written by hand, data files
written by generators from the code, and pages the local extensions render from
those data files.

## What is written, what is generated

| Part of the site | Source of truth | Written by |
|---|---|---|
| Theory, Understand, Get started, About, Contribute | `docs/source/**/*.md` and `*.rst` | a person |
| Parameter reference (`reference/parameters/`) | the Pydantic models under `HydroModPyConfig` | `tools/docs/field_registry.py`, then `_ext/hmp_params.py` and `_ext/hmp_tview.py` |
| Python API and command line (`reference/python/`, `reference/cli/`) | `hydromodpy.__all__`, the signatures, the docstrings and the `argparse` parser | `tools/docs/api_registry.py`, then `_ext/hmp_api.py` |
| Catalogs of solvers, figures and data sources | the registries of the code | `tools/docs/catalogs.py`, then `_ext/hmp_catalogs.py` |
| Validation page and "Checked by" boxes | `tests/` and `validation_cases/` | `tools/docs/tests_index.py`, then `_ext/hmp_validation.py` |
| TOML changes since the last release | the field snapshot of the release under `tools/docs/snapshots/` and the current registry | `tools/docs/toml_changelog.py` |
| Layer matrix | `tests/unit/architecture/layer_matrix.yaml` | `tools/doc_contracts.py` |
| JSON Schema of the configuration | `HydroModPyConfig` | `tools/docs/schema_export.py` |

The data files go to `docs/source/_data/` at the `builder-inited` event of the
build. Git ignores them, and it ignores the generated pages under
`reference/parameters/`, `reference/python/` and `reference/cli/`.
`HMP_SKIP_DOC_DATA=1` reuses the data of the previous build when you only edit
written pages. The layer matrix fragment is committed: a build rewrites it, and
CI fails if the committed copy is stale
(`HMP_SKIP_CONTRACT_TABLES_GEN=1` skips that step).

## The local extensions

They live in `docs/source/_ext/` and are listed in `conf.py`.

| Extension | What it does |
|---|---|
| `hmp_params` | The field registry, the role that cites a TOML key, the `hmp-params` and `hmp-resolved` directives, the parameter cards and the explorer data. It registers the other generator-backed extensions. |
| `hmp_tview` | The annotated TOML view of each section. |
| `hmp_api` | The Python API and command-line pages, rendered with autodoc and napoleon. |
| `hmp_catalogs` | The solver, figure and data source catalogs. |
| `hmp_validation` | The validation page and the "Checked by" boxes. |
| `hmp_card` | The text rendering of one parameter card. |
| `hmp_directives` | The `image-comparison` slider, and optional page-view analytics. |
| `hmp_site` | The site chrome the theme does not give: scripts and styles loaded only on the pages that use them, and previous and next links that stay inside a door. Its stylesheet is `_static/css/hmp-site.css`. |

## Build and check

Build the site with the strict target, the one CI runs. A warning is an error.

```bash
make -C docs html-strict
```

Without `make`, the same build is:

```bash
python -m sphinx -j auto -W --keep-going -b html docs/source docs/build/html
```

Then run the two checkers CI runs after the build.

```bash
python -m tools.docs.check_page $(git ls-files 'docs/source/*.md')
python -m tools.docs.check_site docs/build/html
```

`check_page` reads a page without building the site, which makes it the fast
loop while you write. It needs `docs/source/_data/registry.json`, so build once
first. For each page, `.md` or `.rst`, it checks that:

- every key cited with the TOML role, every `hmp-params` line and every
  `hmp-resolved` key exists in the field registry;
- every document link, card link and relative link points to a page;
- every TOML block parses, and a block that writes a section of the file loads
  with the real loader once merged onto the first step of example 04;
- the page has no French and no em dash.

A TOML block that shows a mistake on purpose, or a file the loader does not
read, starts with `# not checked: <reason>` and is skipped.

`check_site` reads the built HTML. Sphinx does not see what the extensions
write as raw HTML, so it looks for a link inside a link, an internal link to a
missing page or anchor, and markup shown as text (double backticks, bold
markers, a role that was not resolved).

## Diagrams

The architecture pages draw their diagrams with PlantUML (`.. uml::`). The build
renders them only when it finds a PlantUML command: the `PLANTUML_COMMAND`
environment variable, the jar installed by `python tools/setup_plantuml.py`
(it needs Java), or a `plantuml` on the path. Without one, each diagram is a
banner that names the file, and the build still passes. The deploy workflow
installs the `plantuml` package. The pull-request build (`docs.yml`) does not, so
there the diagrams are banners.

## Preview

```bash
make -C docs livehtml
```

serves the site with `sphinx-autobuild` and reloads on save. The `lint` target
runs `sphinx-lint` and `doc8` on the sources.

## What CI does with it

`docs.yml` runs the strict build, `check_page`, `check_site`, and a last step
that fails when a tracked file under `docs/source` changed during the build.
`docs-deploy-pages.yml` builds one version and publishes it to its own folder
of `docs.hydromodpy.fr`; the other versions stay. See
{doc}`../project/ci-workflows`.
