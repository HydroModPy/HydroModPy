from hydromodpy.calibration import objective_function as obj_f
import numpy as np

def Q_brutsaert(rech, K, Sy=0.05):
    """
    Calculate Brutsaert flow based on time, hydraulic conductivity, and specific yield.
    Temporary function to be replaced by Hydromodpy Solver interactions.
    
    Parameters:
    rech (Pandas Series): Time and recharge values
    K (float): Hydraulic conductivity
    Sy (float): Specific yield
    
    Returns:
    float: Q_brutsaert value
    """
    t = rech.index.values # Assuming rech is a Pandas Series with time as index
    Q_brutsaert = (np.log10(K) * Sy) #/ t
    return Q_brutsaert

class Calibration:
    """
    Class to compute objective function values across a range of K and Sy parameters for a given recharge time series.
    """
    
    def __init__(self, params_dict, max_sim_nb, rech, obj_func, calib_method, solver='Modflow'):
        """
        Initialize with parameter ranges, calibration options and recharge values.
        
        Parameters:
        params_dict (dict): Dictionary with parameter names as keys and lists of parameter bounds to explore as values
        max_sim_nb (int): Maximum number of simulations to run within calibration process
        rech (Pandas Series): Time and recharge values
        obj_func (str): Objective function to use for evaluating the performance of each parameter combination
        calib_method (str): Calibration method to use
        """
        from math import ceil
        self.params_dict = params_dict
        self.list_params = list(self.params_dict.keys())
        self.nb_params = len(self.list_params)
        self.param_resolution = ceil(max_sim_nb**(1/self.nb_params))
        self.log_spaced_params = ['K'] # List of parameters to be explored using log scale
        self.nb_sim = self.param_resolution ** self.nb_params
        self.rech = rech
        self.t = rech.index.values # Extract time values from the rech Series
        self.Q_obs = Q_brutsaert(rech, 1E-3, 0.05) # To be replaced by reference observable
        print(self.Q_obs)
        self.obj_func = obj_func
        self.calib_method = calib_method
        self.solver = solver

        # Dictionnary allowing to check parameters vs solver consistency
        # to be switched to a parameter file
        solver_params_dict = {
            'Modflow': ['K', 'Sy', 'Ss', 'Cd'],
            'GR4J': ['X1', 'X2', 'X3', 'X4']}
        
        for param in self.list_params:
            if param not in solver_params_dict[self.solver] and param != 'thick':
                raise ValueError(f"Parameter {param} is not compatible with the chosen solver.")



    
    def explore(self):
        """
        Calculate objective function for all combinations of explored parameters.
        
        Returns:
        dict: Dictionary with parameter combinations and associated objective function values
        """
        import pandas as pd
        import numpy as np

        # Initialisation of results storage and check consistency of parameters to calibrate
        results_dict = {}
        results_df_cols = self.list_params + ['Objective_Function']
        results_df = pd.DataFrame(columns=results_df_cols)
        if len(self.list_params) == 0:
            raise ValueError("Set at least 1 parameter to calibrate")
                
        # Create a dictionnary of parameter ranges
        param_ranges = {}
        for param in self.list_params:
            p_start, p_stop = self.params_dict[param]
            if param in self.log_spaced_params:
                param_ranges[param] = np.logspace(np.log10(p_start), np.log10(p_stop), self.param_resolution)
            else:
                param_ranges[param] = np.linspace(p_start, p_stop, self.param_resolution)

        # Generate nested loops dynamically
        def generate_combinations(params_list, ranges_dict, index=0, current_combo=None):
            if current_combo is None:
                current_combo = {}
            
            if index == len(params_list):
                yield current_combo.copy()
                return
            
            param = params_list[index]
            for value in ranges_dict[param]:
                current_combo[param] = value
                yield from generate_combinations(params_list, ranges_dict, index + 1, current_combo)

        for param_combo in generate_combinations(self.list_params, param_ranges):
            print(param_combo)
            if self.nb_params == 1:
                Q_sim = Q_brutsaert(self.rech, param_combo[self.list_params[0]]) # to replace by several hydromodpy interactions
            else:
                Q_sim = Q_brutsaert(self.rech, param_combo['K'], param_combo['Sy']) # to replace by several hydromodpy interactions
            key = ", ".join([f"{p}={param_combo[p]:.6f}" for p in self.list_params])
            results_dict[key] = obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric='RMSE')
            row = {p: param_combo[p] for p in self.list_params}
            row['Objective_Function'] = results_dict[key]
            results_df = pd.concat([results_df, pd.DataFrame([row])], ignore_index=True)

        # old code for 2 parameters:
        # for K in range(self.params_dict)
        #     for Sy in self.Sy_range:
        #         key = f"K={K}, Sy={Sy}"
        #         Q_sim = Q_brutsaert(K, Sy, self.rech) # To be replaced by simulated values from Solver.
        #         results_dict[key] = obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric='RMSE')
        #         results_df = pd.concat([results_df, pd.DataFrame({'K': [K], 'Sy': [Sy], 'Objective_Function': [results_dict[key]]})], ignore_index=True)
       
        return (results_dict, results_df)
    
    def print_results(self, results_df):
        """"
        Print visualizable results of obective function for 1, 2 or 3 parameter calibration.
        
        Parameters:
        results_df (DataFrame): DataFrame containing parameter combinations and associated objective function values
        """

        import matplotlib.pyplot as plt
        # 1 parameter calibration result visualization
        if len(self.list_params) == 1:
            param_col = self.list_params[0]
            obj_col = 'Objective_Function'
            plt.figure(figsize=(10, 6))
            plt.plot(results_df[param_col], results_df[obj_col], marker='o')
            plt.xlabel(param_col)
            plt.ylabel(obj_col)
            plt.title(f'{obj_col} vs {param_col}')
            plt.xscale('log' if param_col in self.log_spaced_params else 'linear')
            plt.grid()
            plt.show()

        # 2 parameters 2D visualization
        param_cols = self.list_params
        obj_col = 'Objective_Function'

        if len(param_cols) == 2: # Create pivot table if 2 parameters are calibrated
            pivot_data = results_df.pivot_table(
                index=param_cols[0],
                columns=param_cols[1],
                values=obj_col
            )
            
            plt.figure(figsize=(10, 6))
            plt.imshow(pivot_data.values, aspect='auto', cmap='viridis', origin='lower')
            plt.colorbar(label=self.obj_func)
            plt.xlabel(param_cols[1])
            plt.ylabel(param_cols[0])
            plt.title(f'{obj_col} vs {param_cols[0]} and {param_cols[1]}')
            plt.xticks(range(len(pivot_data.columns)), [f'{x:.4f}' for x in pivot_data.columns], rotation=45)
            plt.yticks(range(len(pivot_data.index)), [f'{x:.4f}' for x in pivot_data.index])
            # plt.tight_layout()
            plt.show()
        else:
            print(f"2D visualization requires exactly 2 parameters, found {len(param_cols)}")
        

