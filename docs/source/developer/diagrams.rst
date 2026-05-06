Diagram Strategy
================

HydroModPy documentation uses two diagram engines side by side. Each one fits
a specific need.

When To Use Mermaid
-------------------

Use Mermaid for lightweight, source-friendly diagrams that fit inline in an
RST page:

- simple flowcharts (boxes plus arrows),
- decision trees with a few branches,
- short sequence sketches between two or three actors,
- conceptual maps where rich UML stereotypes are not needed.

Mermaid blocks render client-side via ``sphinxcontrib.mermaid``. They are
plain text inside the RST, so they review well in Git and require no Java
binary.

Inline form, preferred for short diagrams::

   .. mermaid::

      flowchart LR
        A --> B
        B --> C

External file form, for longer diagrams shared across pages::

   .. mermaid:: diagrams/my_diagram.mmd

When To Use PlantUML
--------------------

Keep PlantUML for detailed UML where its native vocabulary pays off:

- class diagrams with attributes, methods, stereotypes, and visibility,
- component diagrams with packages, ports, and interfaces,
- sequence diagrams with activations, deactivations, alt/loop/par fragments,
- state diagrams with composite or hierarchical states,
- activity diagrams with partitions, swimlanes, or detached notes.

PlantUML files live next to the page that uses them, in a sibling
``diagrams/`` folder, with a ``.wsd`` extension. They are rendered server-side
by ``sphinxcontrib-plantuml`` against the bundled ``tools/vendor/plantuml/``
binary.

File Conventions
----------------

- ``diagrams/<name>.wsd`` next to the consuming RST page for PlantUML.
- ``.. mermaid::`` inline for short Mermaid blocks; ``.mmd`` external file
  in ``diagrams/`` only when the same Mermaid diagram is reused elsewhere.
- One diagram per file. Do not bundle several PlantUML scenes in one ``.wsd``.
- The basename should describe the content, not the rendering engine
  (``mesh_support_strategy_map``, not ``mesh_support_strategy_uml``).

Migration Policy
----------------

Existing PlantUML diagrams that are essentially "boxes plus arrows plus
labels" are migrated to Mermaid on a best-effort basis. UML-rich diagrams
(class, partitioned activity, composite state, sequence with activations)
stay in PlantUML. Do not duplicate the same scene in both engines.
