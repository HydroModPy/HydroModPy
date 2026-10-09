# Write a theory page

A theory page gives the equations of one model, in the order the code applies
them, with their assumptions and their limits. It is the one part of the site
written by hand, so the build checks what it can: every TOML path it cites,
every field it lists, and the tests that cover the code it describes.

## What goes on a theory page

A page exists for what HydroModPy computes or decides: a rule it applies when it
builds the model, a conversion from TOML to solver input, a method it implements
itself, a refusal, a result of its own tests. Theory that a maintained source
already documents, such as the MODFLOW equations and packages or textbook
hydrogeology, gets at most three sentences: what the solver does, the citation
or link, then what HydroModPy writes, sets or refuses. No derivation, no
equation and no figure for it, unless other pages build on that equation.

A page has no how-to. What a user must know to set something up goes in the
description of the field, which the generated reference shows, or in a tested
example. The theory page links the reference page of the section. A page does
not copy generated content either: defaults and ranges come from `hmp-params`
and the parameter reference, and validation numbers come from
{doc}`../theory/validation`.

## The parts of a page, in this order

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} What it answers
One question, in one or two sentences, then the notation: each symbol with its
unit and the TOML field that sets it, through the `{toml}` role. A symbol that
no field sets is a state variable, and the page says so. The table is not typed:
list the symbols in `docs/source/theory/symbols.yaml` with the page name, and
show them with the `hmp-notation` directive. A symbol has one meaning on the
whole site: the build stops on a symbol that carries two, unless the registry
declares the pair and the two meanings never meet on one page.
`tests/unit/docs/test_notation_registry.py` checks this.
:::

:::{grid-item-card} Equations, in code order
The equations are written in the order the code applies them, with the file
and the function that holds them. A page states nothing the code does not do.
:::

:::{grid-item-card} Assumptions and limits
Assumptions are what the equations take for granted. Limits are what the code
refuses or does not represent. Both are lists, one line each. When both are
three bullets or fewer, they are merged under Limits.
:::

:::{grid-item-card} Generated boxes
`hmp-params` lists the fields of the equations with their type, default, unit
and range. `hmp-tested-by` lists the tests that import the modules of the
page. Neither is typed by hand, so neither goes out of date.
:::
::::

## Citing a source

Cite with `{cite:p}` or `{cite:t}` (`:cite:p:` in reStructuredText), with a key
of `docs/source/theory/references.bib`. To add a reference, append a BibTeX entry
to that file. The {doc}`../theory/bibliography` lists the entries that a page
cites.

## What the build checks

- A `{toml}` path that no field has fails the build, with the page and
  the line.
- A field in `hmp-params` that does not exist fails the build.
- A module in `hmp-tested-by` that no test imports: the box says so in red,
  so an untested model shows on its own page.

## Example

{doc}`../theory/soil-reservoir` is written this way. Its last two boxes,
"Parameters of this page" and "Checked by", are generated.
