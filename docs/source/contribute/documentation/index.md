# Documentation

This site is built from the code as much as the code allows. A parameter, a
command, a solver, a figure and a test list are written by the build from the
repository. What you write by hand are Get started, Understand, the theory
pages and the contributor pages.

## Three rules

1. **The code is the only source of a parameter.** Name, type, default, unit,
   range and conditions are read from the Pydantic models. No page types them.
2. **A reference page is generated.** If a card is wrong, fix the model or its
   metadata, never the page. The generated pages are not committed.
3. **A page embeds keys, it does not copy them.** It writes
   {toml}`flow.param.K.field.value` in prose and lists rows with `hmp-params`.
   A key that does not exist stops the build.

## Pages

- {doc}`how-the-docs-are-built`: the generators, the extensions, the checks and
  the commands to build and check a page.
- {doc}`../write-a-theory-page`: equations in the order the code applies them.
- {doc}`../docstring-policy`: what the Python API reference reads from a
  docstring.
- {doc}`coverage`: what the models leave undocumented, computed at each build.
- To document a TOML key, write its `Field` description. The recipe is the section
  "Describe the field" of {doc}`../architecture/how-to/add-a-config-field`.

```{toctree}
:maxdepth: 1
:hidden:

how-the-docs-are-built
../write-a-theory-page
../docstring-policy
coverage
```
