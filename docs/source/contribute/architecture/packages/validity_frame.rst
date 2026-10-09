Package: validity_frame
=======================

``validity_frame`` is a small standalone distribution at ``validity_frame/``, next to
``hydromodpy/`` and never inside it. It has its own ``pyproject.toml``, version and tests.
The package code is in ``validity_frame/src/validity_frame/``. ``hydromodpy/`` does not
import it, and CI installs it (``pip install -e validity_frame``) for the tests that use it.

Status
------

It is outside the stable V1 public API and has no compatibility guarantee. It depends on no
other framework and expects compatible objects through duck-typing. It must stay isolated from
the modeling layers, and it is not a layer of ``layer_matrix.yaml``.

Parts
-----

Paths are relative to ``validity_frame/src/validity_frame/``.

- ``validity.py``: ``ValidityFrame``, with ``verify(state, steps)``, which checks a few generic
  invariants of a pipeline state. With ``tolerant=True`` it returns instead of raising.
- ``loader.py``: ``create_validity_frame(name)``, which loads a frame from the
  ``validity_frame.frames`` entry-point group. The package registers ``default``, and an
  external project can register its own.
- ``auto_capture/``: ``AutoCaptureCollector`` and ``AutoCaptureSnapshot``, which take a
  snapshot of the execution before a run (``capture_start``) and after it
  (``capture_end``, or ``capture_exception`` for a run that raised), and ``ExecutionContext``.
- ``probes/``: the system, hardware, runtime and solver probes the collector calls.
- ``semantic_model/``: the knowledge model of a run: ``ContextModel``, ``ValidityDomain``,
  ``ExpertAnnotation``, ``ExecutionKnowledgeRecord``, ``ValidationStore`` and the loader
  ``load_semantic_model``.

Capture sequence
----------------

The envelope around a run: a snapshot before, the run, then a snapshot of the end state or
of the exception.

.. uml:: ../process/diagrams/validity_frame_runtime_sequence.puml

See also
--------

- :doc:`../layered-architecture` for the matrix contract.
- :ref:`artifact-policy` for the storage formats the project treats as canonical.
