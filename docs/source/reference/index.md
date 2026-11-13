# Reference

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} TOML parameters
:link: parameters/index
:link-type: doc

Every section of the configuration file, grouped by what it describes.
:::

:::{grid-item-card} What changed in the TOML
:link: changes
:link-type: doc

Added, removed and changed fields between two versions, computed from the models.
:::

:::{grid-item-card} Register of changes
:link: changes-register
:link-type: doc

Every fix that moves a number, every default that moves with an edition, and every key that moves or leaves, read from the register.
:::

:::{grid-item-card} Python API
:link: python/index
:link-type: doc

The functions of `import hydromodpy as hmp`, the objects they return, the exceptions and their codes.
:::

:::{grid-item-card} Command line
:link: cli/index
:link-type: doc

Every `hmp` command and subcommand, with its arguments, examples and exit codes, read from the parser.
:::

:::{grid-item-card} Outputs of a run
:link: outputs
:link-type: doc

Every field array and every time series a run stores, with its path, unit and dimensions, read from the registry of the code.
:::

:::{grid-item-card} Data sources
:link: data-sources
:link-type: doc

Every data section and the sources it accepts, by section or by provider, with publisher and licence.
:::

:::{grid-item-card} Figure requests
:link: figure-requests
:link-type: doc

The fields of a figure and of a panel, the frames, quantities, variables, presets and overlays a request names.
:::

:::{grid-item-card} Solvers
:link: solvers
:link-type: doc

Every process and solver pair, the TOML lines that select it, its executable and what it needs before it.
:::

:::{grid-item-card} Calibration methods
:link: calibration-methods
:link-type: doc

Every search method with its options and defaults, and every metric with its formula, read from the registries of the code.
:::

:::{grid-item-card} Glossary
:link: glossary
:link-type: doc

The terms used on this site, with a short definition, and the setting in the configuration file when there is one.
:::

::::

```{toctree}
:hidden:
:caption: Configuration

parameters/index
changes
changes-register
```

```{toctree}
:hidden:
:caption: Python and command line

python/index
cli/index
```

```{toctree}
:hidden:
:caption: Catalogs

outputs
data-sources
figure-requests
solvers
calibration-methods
glossary
```
