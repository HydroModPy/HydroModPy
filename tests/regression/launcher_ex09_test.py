# -*- coding: utf-8 -*-
"""
Test wrapper for launcher.py - Example 09 mode
Runs launcher.py with example="ex09" and stops after preprocessing_modflow
"""

import sys
import os
from pathlib import Path

# Add root to path
root_dir = str(Path(__file__).parent.parent.parent)
sys.path.append(root_dir)

# Import launcher module
import launcher

# Configure for Example 09 - SHORT version, end-to-end with MODFLOW
launcher.CONFIG = {
    "example": "ex09",
    "sections": {
        "watershed": True,
        "data": True,
        "recharge": True,
        "parametrization": True,
        "modeling": True,
        "matching_streams": True,
        "modpath": True,
        "mt3dms": True,
        "plot_streamflow": True,
        "plot_piezometry": True,
        "plot_pathlines": True,
        "plot_concentration": True,
        "plot_animation_interactive": True
    }
}

if __name__ == "__main__":
    try:
        launcher.main()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
