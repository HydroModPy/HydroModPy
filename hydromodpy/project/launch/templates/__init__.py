"""Shell templates of the SLURM array job written by ``hmp campaign array``.

``prepare.sh`` and ``array.sh`` are the two job scripts; ``worker.sh`` is the
block both of them run for one case: resolve the case of the task, run the
worker as a child, forward SIGTERM to it, and write ``failed`` in the run
directory when the worker left ``running`` behind. Placeholders are
``{{NAME}}`` tokens, filled by :mod:`hydromodpy.project.launch.slurm`.
"""
