# Write a theory page

A theory page gives the equations of one model, in the order the code applies
them, with their assumptions and their limits. It is the one part of the site
written by hand, so the build checks what it can: every TOML path it cites,
every field it lists, and the tests that cover the code it describes.

## The parts of a page, in this order

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} What it answers
One question, in one or two sentences, then the notation: each symbol with its
unit and the TOML field that sets it, through the `{toml}` role. A symbol that
no field sets is a state variable, and the page says so.
:::

:::{grid-item-card} Equations, in code order
The equations are written in the order the code applies them, with the file
and the function that holds them. A page states nothing the code does not do.
:::

:::{grid-item-card} Assumptions and limits
Assumptions are what the equations take for granted. Limits are what the code
refuses or does not represent. Both are lists, one line each.
:::

:::{grid-item-card} Generated boxes
`hmp-params` lists the fields of the equations with their type, default, unit
and range. `hmp-tested-by` lists the tests that import the modules of the
page. Neither is typed by hand, so neither goes out of date.
:::
::::

## What the build checks

- A `{toml}` path that no field has fails the build, with the page and
  the line.
- A field in `hmp-params` that does not exist fails the build.
- A module in `hmp-tested-by` that no test imports: the box says so in red,
  so an untested model shows on its own page.

## Example

{doc}`../theory/soil-reservoir` is written this way. Its last two boxes,
"Parameters of this page" and "Checked by", are generated.
