"""The spatial part of the site selection, in one sub-package per phase.

The phases are ``candidates``, ``hydrology``, ``evidence``, ``evaluation``,
``decisions`` and ``outputs``, on the records of ``domain`` and the tables of
``config``. Import a name from its module. The run of a selection file lives in
``hydromodpy.workflow.site_selection``.
"""

from __future__ import annotations
