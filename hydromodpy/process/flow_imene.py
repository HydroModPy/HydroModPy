# -*- coding: utf-8 -*-
"""
Custom Flow class for Imene's example
Encapsulates additional hydraulic parameters not in base Flow class
"""

from hydromodpy.process.flow import Flow


class FlowImene(Flow):
    """
    Custom Flow class that manages additional hydraulic parameters beyond base Flow.
    """

    def __init__(self,
                 hk_decay=0,       # HK decay with depth
                 sy_decay=0,       # Sy decay with depth
                 ss_decay=0,       # Ss decay with depth
                 hk_vertical=None, # Vertical HK distribution
                 cond_drain=None   # Drain conductance
                 ):
        """
        Initialize FlowImene with additional hydraulic parameters.

        Parameters
        ----------
        hk_decay : float, optional
            HK exponential decay with depth (default: 0)
        sy_decay : float, optional
            Sy exponential decay with depth (default: 0)
        ss_decay : float, optional
            Ss exponential decay with depth (default: 0)
        hk_vertical : list or None, optional
            Vertical HK distribution (e.g., [ [1e-5, [0, 20]], [1e-6, [20,80]] ])
        cond_drain : float or None, optional
            Drain conductance
        """
        super().__init__()

        # Store additional parameters
        self.hk_decay = hk_decay
        self.sy_decay = sy_decay
        self.ss_decay = ss_decay
        self.hk_vertical = hk_vertical
        self.cond_drain = cond_drain

    def apply_to_watershed(self, BV):
        """
        Apply additional hydraulic parameters to a Watershed object.

        Parameters
        ----------
        BV : Watershed
            Watershed object to update
        """
        # Apply decay parameters
        BV.hydraulic.update_hk_decay(self.hk_decay, min_value=None, log_transf=False)
        BV.hydraulic.update_sy_decay(self.sy_decay, min_value=None, log_transf=False)
        BV.hydraulic.update_ss_decay(self.ss_decay, min_value=None, log_transf=False)

        # Apply vertical distribution and drain conductance
        BV.hydraulic.update_hk_vertical(self.hk_vertical)
        BV.hydraulic.update_cond_drain(self.cond_drain)

    def update_hk_decay(self, hk_decay):
        """Update HK decay"""
        self.hk_decay = hk_decay

    def update_sy_decay(self, sy_decay):
        """Update Sy decay"""
        self.sy_decay = sy_decay

    def update_ss_decay(self, ss_decay):
        """Update Ss decay"""
        self.ss_decay = ss_decay

    def update_hk_vertical(self, hk_vertical):
        """Update vertical HK distribution"""
        self.hk_vertical = hk_vertical

    def update_cond_drain(self, cond_drain):
        """Update drain conductance"""
        self.cond_drain = cond_drain

