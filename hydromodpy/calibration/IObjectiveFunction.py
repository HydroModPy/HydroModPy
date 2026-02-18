from abc import ABC, abstractmethod

import pandas as pd

class IObjectiveFunction(ABC):
    """
    Interface for objective functions used in calibration of hydrological models.
    """
    
    @abstractmethod
    def evaluate(self, simulated: pd.Series, observed: pd.Series) -> float:
        """Calculate the objective function value based on simulated and observed data."""
        pass

    @abstractmethod
    def getweights(self) -> float:
        """Return the weight for different metrics."""
        pass

    @abstractmethod
    def set_weights(self, weights: float) -> None:
        """Set the weight for different metrics."""
        pass

    # Ajout d'une méthode ou paramètre dans les classes filles pour transformations (log, sqrt, etc.)