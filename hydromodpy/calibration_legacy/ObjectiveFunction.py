from abc import ABC, abstractmethod

import numpy as np

class ObjectiveFunction(ABC):
    """
    Interface for objective functions used in calibration of hydrological models.
    """
    
    def __init__(self, weight: float = 1.0):
        """
        Initialize the objective function.
        
        Parameters
        ----------
        weight : float, optional
            Weight for this objective function, by default 1.0
        """
        self._weight = weight
    
    @property
    def weight(self) -> float:
        """Get the weight of this objective function."""
        return self._weight
    
    @weight.setter
    def weight(self, value: float) -> None:
        """Set the weight of this objective function."""
        self._weight = value
    
    @abstractmethod
    def evaluate(self, observed, simulated) -> float:
        """Calculate the objective function value based on simulated and observed data."""
        pass

    @abstractmethod
    def normalize(self, observed, simulated) -> float:
        """
        Return normalized performance value between 0 and 1.
        
        1 = optimal performance, 0 = worst acceptable performance.
        This allows combining different objective functions with incompatible scales.
        """
        pass

    @staticmethod
    def check_series_consistency(observed, simulated):
        """
        Prepare observed/simulated arrays with common finite-value masking.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            (obs, sim) masked to finite pairs.

        Notes
        -----
        - Keeps only paired finite values to avoid NaN/Inf propagation.
        - Preserves 1-to-1 comparison after masking.
        """
        obs = np.asarray(observed, dtype=float)
        sim = np.asarray(simulated, dtype=float)

        if obs.shape != sim.shape:
            raise ValueError("Observed and simulated data must have the same shape")

        # Keep only entries where both observed and simulated are finite.
        mask = np.isfinite(obs) & np.isfinite(sim)
        obs = obs[mask]
        sim = sim[mask]

        if obs.size == 0:
            raise ValueError("No common valid finite values in observed and simulated data")

        return obs, sim

    # Ajout d'une méthode ou paramètre dans les classes filles pour transformations (log, inv, sqrt, etc.)