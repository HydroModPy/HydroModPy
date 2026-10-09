# Contribute

This part is for people who change HydroModPy itself. If you only write TOML
files, the {doc}`Guides <../guides/index>` and the
{doc}`Reference <../reference/index>` are for you.

## I want to

| Task | Start here |
|---|---|
| Set up an environment and run my first test | {doc}`quick-start` |
| Open an issue, branch, commit, open a pull request | {doc}`handbook` |
| Add a config field | {doc}`architecture/how-to/add-a-config-field` |
| Add a solver, a process or a data source | {doc}`architecture/how-to/add-a-solver`, {doc}`architecture/how-to/add-a-process`, {doc}`architecture/how-to/add-a-data-source` |
| Add a figure, an exporter or a `hmp` command | {doc}`architecture/how-to/add-a-figure`, {doc}`architecture/how-to/add-an-exporter`, {doc}`architecture/how-to/add-a-cli-command` |
| Add a test, or read a failing check | {doc}`architecture/how-to/add-a-test`, {doc}`project/ci-workflows` |
| Fix an import the architecture gate refuses | {doc}`architecture/how-to/fix-an-architecture-gate` |
| Cut a release | {doc}`architecture/how-to/cut-a-release` |
| Change this documentation | {doc}`documentation/index` |
| Understand how the code is organised | {doc}`architecture/mental-model` |

## The four blocks

- **Recipes** ({doc}`architecture/how-to/index`): one page per extension, with
  the files to touch, the contract to honour and the test to add.
- **Architecture** ({doc}`architecture/index`): the layers and their allowed
  imports, the packages, the storage layout and the subsystems.
- **Documentation** ({doc}`documentation/index`): how this site is built, and
  how to write a field, a guide or a theory page.
- **Project** ({doc}`project/index`): CI, tests, the V1 release contract, the
  environment variables and the roadmap.

```{toctree}
:maxdepth: 1
:hidden:

handbook
quick-start
architecture/how-to/index
architecture/index
documentation/index
project/index
```
