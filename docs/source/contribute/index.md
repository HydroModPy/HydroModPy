# Contribute

This part is for people who change HydroModPy itself: add a field, a solver, a
data source, a figure. If you write TOML files, the {doc}`Guides <../guides/index>`
and the {doc}`Reference <../reference/index>` are for you.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Contributor handbook
:link: handbook
:link-type: doc

Open an issue, set up a development environment, the coding style, the tests.
:::

:::{grid-item-card} Architecture
:link: architecture/index
:link-type: doc

The layers and their allowed imports, the storage layout, the packages, and the
recipes to add a field, a solver, a data source or a figure.
:::

:::{grid-item-card} Document a configuration field
:link: document-a-field
:link-type: doc

What the generated reference reads from a `Field`, and how to write it.
:::

:::{grid-item-card} Write a theory page
:link: write-a-theory-page
:link-type: doc

The parts of a page, the boxes the build generates, and what it checks.
:::

::::

## Three rules for the documentation

1. **The code is the only source of a parameter.** Name, type, default, unit,
   range and conditions are read from the Pydantic models. No page types them.
2. **A reference page is generated.** If a card is wrong, fix the model or its
   metadata, never the page. The generated pages are not committed.
3. **A guide embeds keys, it does not copy them.** It writes
   {toml}`flow.param.K.field.value` in prose and lists rows with `hmp-params`.
   A key that does not exist stops the build.

```{toctree}
:maxdepth: 1
:hidden:

handbook
architecture/index
document-a-field
write-a-theory-page
docstring-policy
roadmap
```
