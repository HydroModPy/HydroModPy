# Write a guide

A guide answers one task, such as "calibrate on the stream network" or "compare
two runs". It is for someone who writes TOML files and runs `hmp`. The other
doors of the site cover the rest: Get started teaches a first run, the Reference
lists keys and commands, and Theory gives the equations.

## One task, one page

Name the task in the title, in sentence case. If a page answers two tasks, split
it. If a section is a list of keys, it belongs in the Reference, and the guide
links to it.

## Start from a TOML file that runs

Write the guide from a file you have run, then copy the blocks into the page.
Each block is one of two kinds:

- a **section block**, which writes one or more tables of the file. `check_page`
  merges it onto the first step of example 04 and loads the result with the real
  loader, so a key that does not exist or a value out of range fails the check;
- a **fragment**, a block that shows a mistake on purpose or something the
  loader does not read. Its first line is `# not checked: <reason>`.

```toml
[flow.param.K.field]
kind = "homogeneous"
value = 1e-5
```

## Cite keys with the role, not by typing them

In prose, write {toml}`flow.param.K.field.value` with the `{toml}` role. The
build resolves it against the field registry and links it to its card, and a
key that does not exist stops the build. To list the keys of a section with
their type, default and unit, use the `hmp-params` directive: nothing is typed
twice.

## Rules of the site

- English only, short sentences, no em dash.
- A claim about the code is checked against the code before it is written.
- A guide may use the example projects. The TOML and Python references may not.
- Observed data, such as the BD Topage network or a calibration target, is
  never a model input in a guide: it is a criterion, a figure or a diagnostic.

## Check it

```bash
make -C docs html-strict
python -m tools.docs.check_page docs/source/guides/your-page.md
python -m tools.docs.check_site docs/build/html
```

Add the page to the `toctree` of `guides/index.md`. The commands are described
in {doc}`how-the-docs-are-built`.
