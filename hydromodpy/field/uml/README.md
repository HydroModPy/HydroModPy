# Field UML

PlantUML diagrams for the `hydromodpy.field` module.

## Files

- `field_classes.wsd`: class diagram (core abstractions + square case classes).
- `field_spatial_cases_classes.wsd`: focused class diagram for
  `Field` (parent), `FieldSquare`, and `GeologyField`.
- `field_activity.wsd`: activity diagram of the demo workflow.
- `field_sequence.wsd`: sequence diagram of runtime interactions.

## Render

From repository root:

```bash
plantuml hydromodpy/field/uml/field_classes.wsd
plantuml hydromodpy/field/uml/field_spatial_cases_classes.wsd
plantuml hydromodpy/field/uml/field_activity.wsd
plantuml hydromodpy/field/uml/field_sequence.wsd
```
