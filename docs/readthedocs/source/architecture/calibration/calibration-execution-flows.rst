Calibration Execution Flows
===========================

Scope
-----

These diagrams document the runtime behavior of calibration workflows rather
than their static class structure.

Open this page when you want:

- the high-level activity of one calibration session,
- the main sequence between launcher, runtime preparation, and engine,
- one concrete case-level runtime example,
- the devkit flow used to scaffold and validate new cases.

Calibration Activity
--------------------

This activity view is the best entry point for the launcher-managed control
flow of one calibration session.

.. uml:: diagrams/calibration_activity.wsd

.. literalinclude:: diagrams/calibration_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - calibration activity

Calibration Sequence
--------------------

This sequence view focuses on the handoff between launcher logic and the
generic calibration engine.

.. uml:: diagrams/calibration_sequence.wsd

.. literalinclude:: diagrams/calibration_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - calibration sequence

Reservoir Sequence
------------------

This sequence is a case-level example showing how one runnable calibration case
plugs into the shared core.

.. uml:: diagrams/reservoir_sequence.wsd

.. literalinclude:: diagrams/reservoir_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - reservoir sequence

Devkit Sequence
---------------

This sequence documents the developer tooling used to scaffold and validate new
calibration cases.

.. uml:: diagrams/devkit_sequence.wsd

.. literalinclude:: diagrams/devkit_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - devkit sequence
