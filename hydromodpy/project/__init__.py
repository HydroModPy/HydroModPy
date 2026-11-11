"""The top of the package tree: the public verbs, a project, and how its runs are launched.

:mod:`.api` holds the fifteen verbs that ``hydromodpy`` and ``hmp`` expose.
:mod:`.facade` holds :class:`~hydromodpy.project.facade.Project`,
:mod:`.runner` the runner behind ``simulate`` and ``calibrate``, and
:mod:`.accessors` the read-only accessors of a project and its catalog. This
module imports nothing, so ``import hydromodpy.project.environment`` loads that
module alone. The page of the package in the developer docs is the map of the package.
"""
