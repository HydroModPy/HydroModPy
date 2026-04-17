Calibration Core Classes
========================

Scope
-----

These diagrams document the reusable classes behind the calibration stack.

They are the right entry point when you want to understand:

- how calibration configuration is normalized before execution,
- which runtime objects stay generic across methods and cases,
- which structures belong to reusable calibration core code rather than to one
  specific scientific case.

Core Classes (Config)
---------------------

This diagram focuses on validated configuration and method-selection objects.

.. uml:: diagrams/core_classes_config.wsd

.. literalinclude:: diagrams/core_classes_config.wsd
   :language: text
   :caption: PlantUML (.wsd) source - core classes config

Core Classes (Main Runtime)
---------------------------

This diagram focuses on the reusable runtime objects exchanged during one
calibration session.

.. uml:: diagrams/core_classes_main.wsd

.. literalinclude:: diagrams/core_classes_main.wsd
   :language: text
   :caption: PlantUML (.wsd) source - core classes main runtime
