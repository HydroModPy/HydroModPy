"""The plan of a ``[sites]`` project: sites x recipes resolved into cases.

The section itself is :mod:`hydromodpy.config.sites`, which the root
configuration reads. This package turns it into cases: it reads the table,
binds its columns, resolves each case with its precedence, writes the plan
once under ``plan/<hash>/`` and says what the plan costs. Each name is
imported from its module.
"""
