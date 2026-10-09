# Data sources

Every data section of the file, and the sources its `source` key accepts, with who publishes
each one and under which licence. Read from the configuration models and from the source registry of the code
(`hydromodpy.schema.sources`), which carries one entry per source. A field added to an
entry shows up here on its own.

A source marked "licence not determined" has no licence recorded in the code. The reason sits in
the details of the source, and a run that reads it does not claim a licence for its outputs.

How to declare the data of a project is a guide: {doc}`../guides/get-the-data`. The format a
`custom` file must have is in {doc}`../guides/use-your-own-files`. A new provider is added by
registering a source: {doc}`../contribute/architecture/how-to/add-a-data-source`.

::::{tab-set}

:::{tab-item} By section
```{hmp-data-sources}
```
:::

:::{tab-item} By provider
```{hmp-data-sources}
:view: provider
```
:::

::::
