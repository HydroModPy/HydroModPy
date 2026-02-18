from IObjectiveFunction import IObjectiveFunction

import numpy as np 

class MAE(IObjectiveFunction):
    """
    Mean Absolute Error (MAE) objective function for hydrological model calibration.
    """

    def evaluate(obs, sim):
        """
        Calculate the Mean Absolute Error (MAE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: MAE value
        """
        obs, sim = check_series_consistency(obs, sim)
        mae = np.mean(np.abs(obs - sim))
        
        return mae

    def getweights(self) -> list[float]:
        """MAE does not use weights, so this method returns an empty list."""
        return []
        

    def set_weights(self, weights: list[float]) -> None:
        """MAE does not use weights, so this method does nothing."""
        pass