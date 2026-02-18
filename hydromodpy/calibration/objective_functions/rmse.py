from IObjectiveFunction import IObjectiveFunction

import numpy as np

class RMSE(IObjectiveFunction):
    """
    Root Mean Square Error (RMSE) objective function for hydrological model calibration.
    """

    def evaluate(obs, sim):
        """
        Calculate the Root Mean Square Error (RMSE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: RMSE value
        """
        obs, sim = check_series_consistency(obs, sim)
        rmse = np.sqrt(np.mean((obs - sim) ** 2))

        return rmse

    def getweights(self) -> list[float]:
        """RMSE does not use weights, so this method returns an empty list."""
        return []
        

    def set_weights(self, weights: list[float]) -> None:
        """RMSE does not use weights, so this method does nothing."""
        pass