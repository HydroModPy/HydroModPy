# Project

How the project is checked, tested and released, and where it is going.

- {doc}`ci-workflows`: what each check of GitHub Actions means and how to read
  a failing one. The table of workflows is generated:
  {doc}`../architecture/generated/ci`.
- {doc}`tests`: the test families and what to run when. The inventory of the
  suite, with the counts, is generated: {doc}`../architecture/generated/tests`.
- {doc}`/about/versions`: what each kind of version may change, and
  {doc}`../architecture/contracts`: which names that covers. The `HMP_*`
  environment variables are generated:
  {doc}`../architecture/generated/environment`, and the optional extras:
  {doc}`../architecture/generated/extras`.
- {doc}`../roadmap`: what is in flight, in a few lines.

To cut a release, follow {doc}`../architecture/how-to/cut-a-release`.

```{toctree}
:maxdepth: 1
:hidden:

ci-workflows
tests
../architecture/generated/ci
../architecture/generated/tests
../architecture/generated/environment
../architecture/generated/extras
../roadmap
```
