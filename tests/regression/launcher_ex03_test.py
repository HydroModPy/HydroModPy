# -*- coding: utf-8 -*-
"""
Test wrapper for launcher.py - Example 03 mode
Runs launcher.py with example="ex03" and stops after preprocessing_modflow
"""

import sys
import os
from pathlib import Path

# Add root to path
root_dir = str(Path(__file__).parent.parent.parent)
sys.path.append(root_dir)

# Import launcher module
import launcher

# Configure for Example 03 - SHORT version, end-to-end with MODFLOW
launcher.CONFIG = {
    "example": "ex03",
    "sections": {
        "watershed": True,
        "data": True,
        "recharge": True,
        "parametrization": True,
        "modeling": True,        # MODFLOW
        "matching_streams": False,
        "modpath": False,
        "mt3dms": False,
        "plot": True  ,
        "plot_streamflow": False,
        "plot_piezometry": False,
        "plot_pathlines": False,
        "plot_concentration": False,
        "plot_animation_interactive": False
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
