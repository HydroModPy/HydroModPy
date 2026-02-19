"""Objective functions and utilities for hydrological model calibration."""

from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction
from hydromodpy.calibration.objective_functions.nse import NSE
from hydromodpy.calibration.objective_functions.kge import KGE
from hydromodpy.calibration.objective_functions.mae import MAE
from hydromodpy.calibration.objective_functions.rmse import RMSE
from hydromodpy.calibration.objective_functions.weighted import WeightedObjectiveFunction
from hydromodpy.calibration.objective_functions.transformations import TransformationStrategy
from hydromodpy.calibration.objective_functions.transformed import TransformedObjectiveFunction

__all__ = [
    'ObjectiveFunction',
    'NSE',
    'KGE',
    'MAE',
    'RMSE',
    'WeightedObjectiveFunction',
    'TransformationStrategy',
    'TransformedObjectiveFunction',
]
