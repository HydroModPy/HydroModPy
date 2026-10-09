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

:::{grid-item-card} Data sources
:link: data-sources
:link-type: doc

Every data section and the sources it accepts, by section or by provider, with publisher and licence.
:::

:::{grid-item-card} Figures
:link: figures
:link-type: doc

Every figure a run can draw, what it reads, when it can be drawn and the options it takes.
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

::::

```{toctree}
:hidden:
:caption: Configuration

parameters/index
changes
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

data-sources
figures
solvers
calibration-methods
```
