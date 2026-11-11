"""How a run travels between workspaces: publish a copy, install it, replay it.

A copy is published with the files that the run read, installed elsewhere, and played
again from its own bytes. This folder needs to see both the run (``results``) and the data
of a workspace (``data``), and no lower layer sees both, so it sits in ``project``.
It never imports ``Project`` (``ImportedProject`` is a result record, not the facade), and
it imports neither ``launch/`` nor ``dispatch/``. The commands ``hmp publish``,
``hmp catalog import`` and ``hmp project import`` call into it, not the reverse. The format
of the install index itself is in ``hydromodpy.core.payload``.

A kind of file that a published run carries is added in ``share.py``. A check or a conflict
when installing is added in ``install.py`` and named before any write. A check on a copy
before it is replayed is added in ``replay.py``.
"""
