# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import numpy as np
import whitebox
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False

logger = get_logger(__name__)

#%% CLASS

@dataclass
class _ParticleSettings:
    """Container for particle-tracking parameters."""

    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            'zone_partic': 'domain',
            'track_dir': 'forward',
            'bore_depth': None,
            'cell_div': 1,
            'zloc_div': False,
            'sel_random': None,
            'sel_slice': None,
        }
    )

    def set_parameters(self, parameters: Mapping[str, Any] | None = None, **kwargs) -> None:
        if parameters is not None:
            self.parameters.update(dict(parameters))
        if kwargs:
            self.parameters.update(kwargs)

class Transport:
    """
    Class with some update functions for transport (concentration) model parameters.
    """
    
    def __init__(self):
        logger.info('Initializing transport module for concentration parameters')
        self.particle = _ParticleSettings()

    def update_particle_parameters(
        self,
        zone_partic: str = 'domain',
        track_dir: str = 'forward',
        bore_depth: list | None = None,
        cell_div: int = 1,
        zloc_div: bool = False,
        sel_random: int | None = None,
        sel_slice: int | None = None,
    ):
        """Update particle-tracking parameters stored in ``transport.particle.parameters``."""
        self.particle.set_parameters(
            zone_partic=zone_partic,
            track_dir=track_dir,
            bore_depth=bore_depth,
            cell_div=cell_div,
            zloc_div=zloc_div,
            sel_random=sel_random,
            sel_slice=sel_slice,
        )
        
    #%% UPDATE
    
    def update_mt3dms_parameters(self,
                                 spc_name: str='NO3',
                                 sconc_init: float=0,
                                 sconc_input = 0,
                                 disp_long: float=0,
                                 disp_transh: float=0,
                                 disp_transv: float=0,
                                 diffu_coeff: float=0,
                                 react_order: int=None, # for MT3DM: 0, 1, 100
                                 rate_decay: float=0,
                                 plot_conc: bool=True,
                                 verbose: bool=True
                                 ):
        """
        Update the model name of the simulation.

        Parameters
        ----------
        model_name : str
            Name of simulation.
        """
        
        self.spc_name = spc_name
        self.sconc_init = sconc_init
        self.sconc_input = sconc_input
        self.disp_long = disp_long
        self.disp_transh = disp_transh
        self.disp_transv = disp_transv
        self.diffu_coeff = diffu_coeff
        self.react_order = react_order
        self.rate_decay = rate_decay
        self.plot_conc = plot_conc
        self.verbose = verbose
        
#%% NOTES
        
