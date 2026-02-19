from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np 
 
class MAE(ObjectiveFunction):
    """
    Mean Absolute Error (MAE) objective function for hydrological model calibration.
    """

    def __init__(self, weight: float = 1.0):
        """Initialize MAE with a weight parameter."""
        super().__init__(weight=weight)

    def evaluate(self, obs, sim):
        """
        Calculate the Mean Absolute Error (MAE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: MAE value
        """
        obs, sim = self.check_series_consistency(obs, sim)
        mae = np.mean(np.abs(obs - sim))
        
        return mae

    def normalize(self, obs, sim) -> float:
        """
        Normalize MAE to [0, 1] range using inverse transformation.
        
        MAE ranges from 0 (optimal) to ∞ (worst).
        Uses formula: performance = 1 / (1 + MAE)
        - MAE = 0 → performance = 1 (optimal)
        - MAE → ∞ → performance → 0 (worst)
        """
        mae_value = self.evaluate(obs, sim)
        # Transform error metric to performance metric
        return 1.0 / (1.0 + mae_value)