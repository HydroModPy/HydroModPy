from IObjectiveFunction import IObjectiveFunction

import numpy as np

class KGE(IObjectiveFunction):
    """
    Kling-Gupta Efficiency (KGE) objective function for hydrological model calibration.
    """
    
    def evaluate(obs, sim):
        """
        Calculate the Kling-Gupta Efficiency (KGE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: KGE value
        """
        obs, sim = check_series_consistency(obs, sim)
        correlation = np.corrcoef(obs, sim)[0, 1]
        bias = np.mean(sim) / np.mean(obs)
        variability = (np.std(sim) / np.std(obs))
        kge = 1 - np.sqrt((correlation - 1) ** 2 + (bias - 1) ** 2 + (variability - 1) ** 2)
        
        return kge

    def getweights(self) -> list[float]:
        """KGE does not use weights, so this method returns an empty list."""
        return []
        

    def set_weights(self, weights: list[float]) -> None:
        """KGE does not use weights, so this method does nothing."""
        pass