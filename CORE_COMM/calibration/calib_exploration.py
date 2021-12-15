# -*- coding: utf-8 -*-
"""
Created on Wed Mar 24 20:35:54 2021

@author: dreuzy
"""

from math import ceil
                                     
from calibration import global_parameters as gp
                     # LPM choice


def systematic_sampling(pmin,pmax,nmodels):
    """ Systematic sampling in the range of pmin-pmax
            Cartesian Product
        Parameters
        ----------
        pmin: array of floats
            vector of min for each of the dimensions to investigate 
        pmax: array of floats
            vector of max for each of the dimensions to investigate
        nmodels: int
            total number of models to investigate
    """
    # Number of parameters to vary for the cartesian product
    np = len(pmin)
    # Resolution in each of the dimentions (parameters) to investigate
    n=ceil(nmodels**(1/np))
    # Cartesian Product for the different dimension cases 
    if np == 1:
        p1 = gp.arange_n(pmin[0],pmax[0],n) 
        return [[i] for i in p1]
    elif np == 2:
        p1 = gp.arange_n(pmin[0],pmax[0],n)
        p2 = gp.arange_n(pmin[1],pmax[1],n)
        return [[i,j] for i in p1 for j in p2]
    elif np == 3:
        p1 = gp.arange_n(pmin[0],pmax[0],n)
        p2 = gp.arange_n(pmin[1],pmax[1],n)
        p3 = gp.arange_n(pmin[2],pmax[2],n)
        return [[i,j,k] for i in p1 for j in p2 for k in p3]
    elif np == 4:
        p1 = gp.arange_n(pmin[0],pmax[0],n)
        p2 = gp.arange_n(pmin[1],pmax[1],n)
        p3 = gp.arange_n(pmin[2],pmax[2],n)
        p4 = gp.arange_n(pmin[3],pmax[3],n)
        return [[i,j,k,l] for i in p1 for j in p2 for k in p3 for l in p4]


