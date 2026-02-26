from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np
 
class RMSE(ObjectiveFunction):
    """
    Root Mean Square Error (RMSE) objective function for hydrological model calibration.
    """

    def __init__(self, weight: float = 1.0):
        """Initialize RMSE with a weight parameter."""
        super().__init__(weight=weight)

    def evaluate(self, observed, simulated) -> float:
        """
        Calculate the Root Mean Square Error (RMSE) between observed and simulated values.
        
        Args:
            observed: Array of observed values
            simulated: Array of simulated values
        
        Returns:
            float: RMSE value
        """
        observed, simulated = self.check_series_consistency(observed, simulated)
        rmse = np.sqrt(np.mean((observed - simulated) ** 2))

        return rmse

    def normalize(self, observed, simulated) -> float:
        """
        Normalize RMSE to [0, 1] range using inverse transformation.
        
        RMSE ranges from 0 (optimal) to ∞ (worst).
        Uses formula: performance = 1 / (1 + RMSE)
        - RMSE = 0 → performance = 1 (optimal)
        - RMSE → ∞ → performance → 0 (worst)
        """
        rmse_value = self.evaluate(observed, simulated)
        # Transform error metric to performance metric
        return 1.0 / (1.0 + rmse_value)