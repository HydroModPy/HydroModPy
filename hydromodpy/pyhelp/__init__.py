# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright © PyHelp Project Contributors
# https://github.com/cgq-qgc/pyhelp
#
# This file is part of PyHELP.
# Licensed under the terms of the MIT License.
# -----------------------------------------------------------------------------

import os

version_info = (0, 4, 1, 'dev0')
__version__ = '.'.join(map(str, version_info))
__appname__ = 'PyHELP'
__namever__ = __appname__ + " " + __version__
__date__ = '20/06/2022'
__project_url__ = "https://github.com/cgq-qgc/pyhelp"
__releases_url__ = __project_url__ + "/releases"
__releases_api__ = "https://api.github.com/repos/cgq-qgc/pyhelp/releases"

__rootdir__ = os.path.dirname(os.path.realpath(__file__))

# Try to import the HELP3O Fortran extension
try:
    from . import HELP3O
    _HELP3O_AVAILABLE = True
except ImportError as e:
    _HELP3O_AVAILABLE = False
    HELP3O = None
    import warnings
    warnings.warn(
        f"HELP3O Fortran extension not available: {e}\n"
        "PyHELP functionality will be limited. To compile the extension, run:\n"
        "  python build_extensions.py\n"
        "from the project root directory.",
        ImportWarning
    )

try:
    from hydromodpy.pyhelp.managers import HelpManager
except ImportError as e:
    # We need to do this to avoid an error when building the
    # help extension with setup.py
    print('ImportError:', e)
