---
description: Every bug fix that moves a number, every default that moves with an edition, every rule and every key that moves or leaves, read from the register of changes.
---

# Register of changes

The register is the file `hydromodpy/schema/changes.toml`. One row says one change that a reader of
an older run or an older file has to know about. The code reads the same rows that this page lists.
The label of a run reads the bugs. The loader and `hmp doctor --fix-config` read the key moves of
the configuration. The `Numbers` section of the changelog is generated from the bugs, the defaults
and the recipes that change a number. Nobody writes this page: a row added to the register shows up
here at the next build.

A key that only a pre-release of 2.0 wrote has no row. It is refused since 2.1.0 with a message
that names every such key of the file, as {doc}`/about/versions` says.

## Bugs

A fix that changes the numbers of a run. A run of one of the listed versions is labelled
`exploratory` when it exposes one of the listed quantities.

```{hmp-changes-register} bug
```

## Defaults

A default that moves with an edition. A file that writes an older edition, or none, keeps the old
value. The key `edition` of a file is `"2.0"` when it is not written.

```{hmp-changes-register} default
```

## Recipes

A computation or a rule that changes without a bug. The effect says what it touches: the numbers,
a refusal, the label of a run, the identity of a run or the layout of its folder.

```{hmp-changes-register} recipe
```

## Key moves

One key or one value that moves, in the configuration or in a stored document. A live
configuration loads a move with a warning until the version in the column Refused from, and
is refused with the new name after it. A sealed run reads the row in silence for the whole major
line. A key that left is refused at once, with what to write instead.

```{hmp-changes-register} migration
```
