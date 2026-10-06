# Document a configuration field

The parameter reference is generated from the Pydantic models of
`HydroModPyConfig`. Everything a reader sees about a key comes from its `Field`
declaration, so you document a key where you declare it. No page holds a copy:
change the field, and the next build shows the change everywhere the key
appears.

## What the reference reads

| The reader sees | It comes from |
|---|---|
| The path of the key and its place in the file | The model tree under `HydroModPyConfig` |
| The one-line summary | The first sentence of `description` |
| The text of the card | The whole `description` |
| The form of the value: number, text, list, table | The annotation |
| The unit | A quantity type (`Length`, `HydraulicConductivity`...), else `field_metadata(unit=...)`, else `Calibrable(units=...)` |
| The default, or *required* | `default`, `default_factory`, or no default |
| The range | `ge`, `gt`, `le`, `lt` |
| The allowed values | `Literal[...]` |
| What each value does | `field_metadata(value_docs={...})` |
| The value written on a required line | The first item of `Field(examples=[...])` |
| Shown by default, or behind the dev and expert button | `Profile.USER`, `Profile.DEV`, `Profile.EXPERT` in the annotation |
| When the key is read | `VisibleWhen("sibling", value)` in the annotation |
| The *calibrable* badge and its transform | `field_metadata(calibrable=Calibrable(...))` |
| The *experimental* and *deprecated* badges | `field_metadata(stability="experimental")`, `Field(deprecated=...)` |
| "Connections found in the code" | Other sections named in the same function or string of `hydromodpy/` |

`field_metadata` lives in `hydromodpy/core/config_kit/field_metadata.py`. It
refuses an unknown key when the module is imported, so a typo fails the tests
rather than the page.

## The description

The first sentence is the summary: it shows on the line of the key, in the
tree of the whole file and in the search. Make it say what the key sets, in
the words of the person who writes the file. Where the key applies, its
conditions and its exceptions come after.

```python
grid_dual: Annotated[Literal["voronoi", "triangle"], Profile.USER] = Field(
    default="voronoi",
    description=(
        "Cell shape of a runtime gmsh mesh: the Voronoi (PEBI) dual or the "
        "triangles themselves. Applies only to a MODFLOW 6 run on a runtime "
        "gmsh mesh; ignored for structured grids."
    ),
    json_schema_extra=field_metadata(
        value_docs={
            "voronoi": "Exact CVFD orthogonality, about half the cells. The default.",
            "triangle": "Keeps the triangulation cells, for simplex comparison runs.",
        }
    ),
)
```

## Values, units and conditions

- **A choice between values.** Use a `Literal` and explain every value in
  `value_docs`. The card lists the values with their explanation, and the
  search finds a key by the name of one of its values.
- **A number.** Give it a unit. A quantity type also lets the file write
  `"150 m"` or `"3 days"`; a bare number is then read in the canonical unit.
- **A key read only in some cases.** Say it with `VisibleWhen`, not only in the
  prose: the card then shows the condition on its own line.
- **An example value.** A required key with no default needs one, in
  `Field(examples=[...])`. It is the value the reference writes on the line
  of the key. Never take it from an example project.

## Check your change

Build the documentation and open the page of the section:

```bash
make -C docs html-strict
```

The build fails on a `{toml}` path that does not exist, on a key listed in
`hmp-params` that does not exist, and on any other warning. The tree of the
whole file, {doc}`../reference/parameters/explorer`, is the fastest way to see
the key in context.
