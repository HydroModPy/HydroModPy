# Field UML

This folder remains the module-local UML entry point for `hydromodpy.field`.
The canonical `.wsd` files are now stored in the documentation tree.

## Source Of Truth

- `docs/readthedocs/source/architecture/field/diagrams/field_classes.wsd`
- `docs/readthedocs/source/architecture/field/diagrams/field_spatial_cases_classes.wsd`
- `docs/readthedocs/source/architecture/field/diagrams/field_activity.wsd`
- `docs/readthedocs/source/architecture/field/diagrams/field_sequence.wsd`

## Related Documentation

- `docs/readthedocs/source/architecture/field/index.rst`
- `docs/readthedocs/source/architecture/field/field-uml-diagrams.rst`

## Render

From repository root:

```bash
plantuml docs/readthedocs/source/architecture/field/diagrams/field_classes.wsd
plantuml docs/readthedocs/source/architecture/field/diagrams/field_spatial_cases_classes.wsd
plantuml docs/readthedocs/source/architecture/field/diagrams/field_activity.wsd
plantuml docs/readthedocs/source/architecture/field/diagrams/field_sequence.wsd
```
