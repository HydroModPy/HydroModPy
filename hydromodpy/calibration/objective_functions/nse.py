from IObjectiveFunction import IObjectiveFunction

import numpy as np

class NSE(IObjectiveFunction):
    """
    Nash-Sutcliffe Efficiency (NSE) objective function for hydrological model calibration.
    """
    
    def evaluate(obs, sim):
        """
        Calculate the Nash-Sutcliffe Efficiency (NSE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: NSE value
        """
        obs, sim = check_series_consistency(obs, sim)
        err_var_sum = np.sum((obs - sim) ** 2)
        obs_var_sum = np.sum((obs - np.mean(obs)) ** 2)
        nse = 1 - (err_var_sum / obs_var_sum)

        return nse

    def getweights(self) -> list[float]:
        """NSE does not use weights, so this method returns an empty list."""
        return []
        

    def set_weights(self, weights: list[float]) -> None:
        """NSE does not use weights, so this method does nothing."""
        pass