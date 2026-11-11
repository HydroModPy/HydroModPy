"""The launcher of a ``[sites]`` project: plan, prepare, launch, count, index.

- :mod:`.local`: :func:`plan_project` and :func:`run_plan`, the local launcher.
- :mod:`.prepare`: the prepare phase, the one writer of the shared data cache.
- :mod:`.children`: the case processes and what they leave behind.
- :mod:`.lease`: ``.hmp/launcher.lease``, one launcher per project.
- :mod:`.journal`: ``jobs/<stamp>-<scheduler>/``, its journal and its case list.
- :mod:`.env`: the environment of a launched case and its thread budget.
- :mod:`.status`: where each case of the current plan stands, from the disk.
"""
