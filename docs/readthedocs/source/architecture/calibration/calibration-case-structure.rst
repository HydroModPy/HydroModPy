Calibration Case Structure
==========================

Scope
-----

This page documents how runnable calibration cases are organized around the
shared calibration core.

It is useful when you want:

- the boundary between ``core/`` and ``cases/``,
- the expected structure of one new calibration case package,
- the split between reusable abstractions and case-specific workflows.

Case/Core Structure
-------------------

.. uml:: diagrams/case_core_structure.wsd

.. literalinclude:: diagrams/case_core_structure.wsd
   :language: text
   :caption: PlantUML (.wsd) source - case/core structure

Notes
-----

- Case packages under ``hydromodpy/calibration/cases`` are expected to
  stay thin adapters around the shared engine.
- CLI-specific concerns such as manifests, reruns, and report
  persistence are owned by ``hydromodpy/calibration/cli.py`` and the
  reporting helpers in ``hydromodpy/calibration/persistence.py`` and
  ``report.py``.
