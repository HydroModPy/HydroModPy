from hydromodpy.calibration.ObjectiveFunction import ObjectiveFunction

import numpy as np
 
class KGE(ObjectiveFunction):
    """
    Kling-Gupta Efficiency (KGE) objective function for hydrological model calibration.
    """
    
    def __init__(self, weight: float = 1.0):
        """Initialize KGE with a weight parameter."""
        super().__init__(weight=weight)
    
    def evaluate(self, obs, sim):
        """
        Calculate the Kling-Gupta Efficiency (KGE) between observed and simulated values.
        
        Args:
            obs: Array of observed values
            sim: Array of simulated values
        
        Returns:
            float: KGE value
        """
        obs, sim = self.check_series_consistency(obs, sim)
        correlation = np.corrcoef(obs, sim)[0, 1]
        bias = np.mean(sim) / np.mean(obs)
        variability = (np.std(sim) / np.std(obs))
        kge = 1 - np.sqrt((correlation - 1) ** 2 + (bias - 1) ** 2 + (variability - 1) ** 2)
        
        return kge

    def normalize(self, obs, sim) -> float:
        """
        Normalize KGE to [0, 1] range.
        
        KGE ranges from -∞ to 1, where 1 is optimal.
        Values below 0 indicate poor performance.
        This method clamps KGE to [0, 1] for combining with other objectives.
        """
        kge_value = self.evaluate(obs, sim)
        # Clamp to [0, 1]: values < 0 become 0, values > 1 become 1
        return max(0.0, min(1.0, kge_value))