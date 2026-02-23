from hydromodpy.calibration import objective_function as obj_f
import numpy as np
import pandas as pd


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

def generate_combinations(params_list, ranges_dict, index=0, current_combo=None):
    """
    Generate nested loops dynamically. Used for n-dimension exploration methods

    Args:
        params_list (_type_): _description_
        ranges_dict (_type_): _description_
    """
    if current_combo is None:
        current_combo = {}
    
    if index == len(params_list):
        yield current_combo.copy()
        return
    
    param = params_list[index]
    for value in ranges_dict[param]:
        current_combo[param] = value
        yield from generate_combinations(params_list, ranges_dict, index + 1, current_combo)



class Calibration_method:
    """
    Class to compute objective function values across a range of K and Sy parameters for a given recharge time series.
    """
    
    def __init__(self, params_dict, max_sim_nb, rech, Q_obs, obj_func, calib_method, solver='Modflow'):
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
        self.max_sim_nb = max_sim_nb
        self.param_resolution = ceil(max_sim_nb**(1/self.nb_params)) # Number of samples in each dimension
        self.nb_sim = self.param_resolution ** self.nb_params
        self.rech = rech
        self.t = rech.index.values # Extract time values from the rech Series
        self.Q_obs = Q_obs
        print(self.Q_obs)
        self.obj_func = obj_func
        self.solver = solver

        self.log_spaced_params = ['K'] # List of parameters to be explored using log scale

        # Dictionnary allowing to check parameters vs solver consistency
        # to be switched to a parameter file
        solver_params_dict = {
            'Modflow': ['K', 'Sy', 'Ss', 'Cd'],
            'GR4J': ['X1', 'X2', 'X3', 'X4']}
        
        for param in self.list_params:
            if param not in solver_params_dict[self.solver] and param != 'thick':
                raise ValueError(f"Parameter {param} is not compatible with the chosen solver.")
        
        if calib_method == 'regular_exploration':
            self.results_df = self.regular_exploration()
        elif calib_method == 'Sobol_exploration':
            self.results_df = self.Sobol_exploration()


    # # Get the objective function result /!\ To be replaced by several hydromodpy interactions (Solver) /!\
    # # implement this function into all calibration methods.
    # def get_obj_func_result(self, params):
    #     param_combo = dict(zip(self.list_params, params))
    #     if self.nb_params == 1:
    #         Q_sim = Q_brutsaert(self.rech, param_combo[self.list_params[0]])
    #     else:
    #         Q_sim = Q_brutsaert(self.rech, param_combo['K'], param_combo['Sy'])
    #     return obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric='RMSE')


    def regular_exploration(self):
        """
        Calculate objective function for all combinations of explored parameters.
        
        Returns:
        dict: Dictionary with parameter combinations and associated objective function values
        """

        # Initialisation of results storage and check consistency of parameters to calibrate
        results_dict = {}
        results_df_cols = self.list_params + ['Objective_Function']
        results_df = pd.DataFrame(columns=results_df_cols)
        if len(self.list_params) == 0:
            raise ValueError("Set at least 1 parameter to calibrate")
                
        # Create a dictionnary of parameter sets to explore
        param_ranges = {}
        for param in self.list_params:
            p_start, p_stop = self.params_dict[param]
            if param in self.log_spaced_params:
                param_ranges[param] = np.logspace(np.log10(p_start), np.log10(p_stop), self.param_resolution)
            else:
                param_ranges[param] = np.linspace(p_start, p_stop, self.param_resolution)

        # Parameter exploration through dynamically generated nested loops
        for param_combo in generate_combinations(self.list_params, param_ranges):
            # print(param_combo)
            if self.nb_params == 1:
                Q_sim = Q_brutsaert(self.rech, param_combo[self.list_params[0]]) # to replace by several hydromodpy interactions
            else:
                Q_sim = Q_brutsaert(self.rech, param_combo['K'], param_combo['Sy']) # to replace by several hydromodpy interactions
            key = ", ".join([f"{p}={param_combo[p]:.6f}" for p in self.list_params])
            results_dict[key] = obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric=self.obj_func)
            row = {p: param_combo[p] for p in self.list_params}
            row['Objective_Function'] = results_dict[key]
            results_df = pd.concat([results_df, pd.DataFrame([row])], ignore_index=True)
       
        return results_df
    

    def Sobol_exploration(self):
        """
        Calculate objective function for Sobol sensitivity analysis.
        
        Returns:
        dict: Dictionary with parameter combinations and associated objective function values
        """
        from scipy.stats.qmc import Sobol
        from scipy.stats.qmc import scale

        def closest_sobol_n(max_nb_sim, d):
            """
            Retourne le plus grand n <= max_nb_sim tel que n^(1/d) est une puissance de 2.
            """
            import math
            # La racine d-ième de n doit être une puissance de 2 : n^(1/d) = 2^k donc n = 2^(k*d)
            # On cherche le plus grand k tel que 2^(k*d) <= max_nb_sim
            k = int(math.log2(max_nb_sim) / d)  # floor implicite via int()
            n = 2**(k * d)
            return round(n**(1/d))


        # Initialisation of results storage and check consistency of parameters to calibrate
        results_dict = {}
        results_df_cols = self.list_params + ['Objective_Function']
        results_df = pd.DataFrame(columns=results_df_cols)
        if len(self.list_params) == 0:
            raise ValueError("Set at least 1 parameter to calibrate")

        # Create a dictionnary of parameter sets to explore
        param_ranges = {}
        sampler = Sobol(d=self.nb_params, scramble=True, seed=42)
        n_samples = closest_sobol_n(self.max_sim_nb, self.nb_params)
        samples = sampler.random(n=n_samples)
        lower_bounds = [bounds[0] for bounds in self.params_dict.values()]
        upper_bounds = [bounds[1] for bounds in self.params_dict.values()]
        samples_scaled = scale(samples, lower_bounds, upper_bounds) # Array
        print(samples_scaled[0])
        param_ranges = dict(zip(self.list_params, samples_scaled.T)) # Array to dict (+transpose)
        print(param_ranges)

        # Parameter exploration through dynamically generated nested loops
        for param_combo in generate_combinations(self.list_params, param_ranges):
            # print(param_combo)
            if self.nb_params == 1:
                Q_sim = Q_brutsaert(self.rech, param_combo[self.list_params[0]]) # to replace by several hydromodpy interactions
            else:
                Q_sim = Q_brutsaert(self.rech, param_combo['K'], param_combo['Sy']) # to replace by several hydromodpy interactions
            key = ", ".join([f"{p}={param_combo[p]:.6f}" for p in self.list_params])
            results_dict[key] = obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric=self.obj_func)
            row = {p: param_combo[p] for p in self.list_params}
            row['Objective_Function'] = results_dict[key]
            results_df = pd.concat([results_df, pd.DataFrame([row])], ignore_index=True)
       
        return results_df
    

    def simplex_calibration(self):
        """
        Calculate objective function for Nelder-Mead simplex optimization method.
        
        Returns:
        dict: Dictionary with parameter combinations and associated objective function values
        """
        from scipy.optimize import minimize

        # Initialisation of results storage and check consistency of parameters to calibrate
        results_dict = {}
        results_df_cols = self.list_params + ['Objective_Function']
        results_df = pd.DataFrame(columns=results_df_cols)
        if len(self.list_params) == 0:
            raise ValueError("Set at least 1 parameter to calibrate")

        # Initial guess for optimization (midpoint of parameter ranges)
        initial_guess = [(bounds[0] + bounds[1]) / 2 for bounds in self.params_dict.values()]

        # Get the objective function result /!\ To be replaced by several hydromodpy interactions (Solver) /!\
        # implement this function into all calibration methods.
        def get_obj_func_result(params):
            param_combo = dict(zip(self.list_params, params))
            if self.nb_params == 1:
                Q_sim = Q_brutsaert(self.rech, param_combo[self.list_params[0]])
            else:
                Q_sim = Q_brutsaert(self.rech, param_combo['K'], param_combo['Sy'])
            return obj_f.objective_function(obs=self.Q_obs, sim=Q_sim, metric=self.obj_func)

        # Define callback function that will be called after each iteration of the optimization to store results
        def callback(xk):
            param_combo = dict(zip(self.list_params, xk))
            obj_value = get_obj_func_result(xk)
            key = ", ".join([f"{p}={param_combo[p]:.6f}" for p in self.list_params])
            results_dict[key] = obj_value
            # row = {p: param_combo[p] for p in self.list_params}
            # row['Objective_Function'] = obj_value
            # results_df = pd.concat([results_df, pd.DataFrame([row])], ignore_index=True)

        # Perform optimization using Nelder-Mead simplex method
        result = minimize(get_obj_func_result,
                          initial_guess,
                          method='Nelder-Mead',
                          callback=callback,
                          options={'xatol': 1e-4, # tolérance sur les paramètres
                                    'fatol': 1e-4,  # tolérance sur f
                                    'maxiter': self.max_sim_nb,
                                    'disp': True,
                                    'adaptive': True})  # adapte coefficients α, γ, ρ, σ en fonction de n (formules de Gao & Han, 2012), améliore la convergence en dimension > 2

        return results_df

  
    def print_results(self):
        """"
        Print visualizable results of obective function for 1, 2 or 3 parameter calibration.
        
        Parameters:
        results_df (DataFrame): DataFrame containing parameter combinations and associated objective function values
        """
        import matplotlib.pyplot as plt

        param_cols = self.list_params
        obj_col = 'Objective_Function'
        
        # 1 parameter calibration result visualization
        if len(self.list_params) == 1:
            plt.figure(figsize=(10, 6))
            plt.plot(self.results_df[param_cols], self.results_df[obj_col], marker='o')
            plt.xlabel(param_cols)
            plt.ylabel(obj_col)
            plt.title(f'{obj_col} vs {param_cols}')
            plt.xscale('log' if param_cols[0] in self.log_spaced_params else 'linear')
            plt.grid()
            plt.show()

        # 2 parameters 2D visualization
        elif len(param_cols) == 2: # Create pivot table if 2 parameters are calibrated
            print(self.results_df)
            print(param_cols[0], param_cols[1], obj_col)
            pivot_data = self.results_df.pivot(
                index=param_cols[0],
                columns=param_cols[1],
                values=obj_col)
            
            plt.figure(figsize=(10, 6))
            plt.imshow(pivot_data.values, aspect='auto', cmap='viridis', origin='lower')
            plt.colorbar(label=self.obj_func)
            plt.xlabel(param_cols[1])
            plt.ylabel(param_cols[0])
            plt.title(f'{obj_col} vs {param_cols[0]} and {param_cols[1]}')
            plt.xticks(range(len(pivot_data.columns)), [f'{x:.4f}' for x in pivot_data.columns], rotation=45)
            xtick_indices = np.linspace(0, len(pivot_data.columns) - 1, 5, dtype=int)
            plt.xticks(xtick_indices, [f'{pivot_data.columns[i]:.4f}' for i in xtick_indices])
            ytick_indices = np.linspace(0, len(pivot_data.index) - 1, 5, dtype=int)
            plt.yticks(ytick_indices, [f'{pivot_data.index[i]:.4f}' for i in ytick_indices])
            plt.tight_layout()
            plt.show()

        # 3 parameters 3D visualization
        elif len(param_cols) == 3:
            fig = plt.figure(figsize=(10, 8))
            ax = fig.add_subplot(111, projection='3d')
            x = self.results_df[param_cols[0]]
            y = self.results_df[param_cols[1]]
            z = self.results_df[param_cols[2]]
            scatter = ax.scatter(x, y, z, c=self.results_df[obj_col], cmap='viridis')
            ax.set_xlabel(param_cols[0])
            ax.set_ylabel(param_cols[1])
            ax.set_zlabel(param_cols[2])
            plt.colorbar(scatter)
            plt.title(f'{obj_col} vs {param_cols[0]}, {param_cols[1]}, and {param_cols[2]}')
            plt.show()

        else:
            print(f"graphical visualization requires 3 or less parameters, found {len(param_cols)}")
        
    def get_result(self):
        """
        Get the results of the calibration process.
        
        Returns:
        DataFrame: DataFrame containing parameter combinations and associated objective function values
        """
        return self.results_df