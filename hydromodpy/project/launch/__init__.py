"""The launcher of a ``[sites]`` project: plan, prepare, launch, count, index.

- :mod:`.local`: :func:`plan_project` and :func:`run_plan`, the local launcher.
- :mod:`.prepare`: the prepare phase, the one writer of the shared data cache.
- :mod:`.children`: the case processes and what they leave behind.
- :mod:`.lease`: ``.hmp/launcher.lease``, one launcher per project.
- :mod:`.journal`: ``jobs/<stamp>-<scheduler>/``, its journal and its case list.
- :mod:`.env`: the environment of a launched case and its thread budget.
- :mod:`.status`: where each case of the current plan stands, from the disk.

The launcher never opens a ``Project``. It starts ``hmp run plan/<hash>/<case>.toml
--frozen`` processes and reads what they leave on disk, on your machine (``local.py``)
or through SLURM array scripts (``slurm.py``). The two do not import each other, because
what they share lives in ``selection.py``. The module
``hydromodpy.project.launch.slurm`` keeps its name and path, because the frozen scripts
in ``templates/*.sh`` and the copies that users keep in ``jobs/`` call it with ``python
-m hydromodpy.project.launch.slurm``. A scheduler other than SLURM is a module next to
``slurm.py`` that shares the rules through ``selection.py`` and ``journal.py``. A
figure, a page or the RO-Crate of a collect is not here: ``display/cohort.py`` and
``results/export/campaign_summary.py`` hold them.
"""
