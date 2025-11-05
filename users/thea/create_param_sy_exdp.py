#%%
import numpy as np
import pandas as pd
import os
from typing import Dict, List, Tuple, Optional
from itertools import product


class ParameterGenerator:
    """
    A flexible parameter generator that creates parameter combinations for any number of variables.
    
    Supports both linear and logarithmic scales, automatic scale detection, and CSV export.
    """
    
    def __init__(self):
        """Initialize the parameter generator."""
        self.parameters = {} # les paramètres seront stockés ici
        self.total_combinations = 0 # nombre total de combinaisons générées
        self.generation_info = {} # informations sur la génération des paramètres exemple (resolution, total_combinations, parameters)
    
    def add_parameter(self, name: str, min_val: float, max_val: float, 
                     resolution: int, scale: str = 'auto') -> None:
        """
        Add a parameter to the generation set.
        
        Parameters
        ----------
        name : str
            Name of the parameter
        min_val : float
            Minimum value for the parameter
        max_val : float
            Maximum value for the parameter
        resolution : int
            Number of points to generate for this parameter
        scale : str, optional
            Scale type: 'linear', 'log', or 'auto' (default: 'auto')
            Auto detection uses logarithmic scale if max_val/min_val > 100
        """
        # Auto-detect scale if requested
        if scale == 'auto':
            ratio = max_val / min_val if min_val > 0 else 1
            scale = 'log' if ratio > 100 else 'linear'
        
        # Generate parameter values
        if scale == 'log':
            if min_val <= 0:
                raise ValueError(f"Logarithmic scale requires positive values. Got min_val={min_val}")
            values = np.logspace(np.log10(min_val), np.log10(max_val), resolution)
        else:  # linear
            values = np.linspace(min_val, max_val, resolution)
        
        self.parameters[name] = {
            'values': values,
            'min': min_val,
            'max': max_val,
            'resolution': resolution,
            'scale': scale
        }
    
    def generate_combinations(self) -> Tuple[pd.DataFrame, Dict]:
        """
        Generate all parameter combinations.
        
        Returns
        -------
        df : pd.DataFrame
            DataFrame containing all parameter combinations
        info : Dict
            Generation information including total combinations, parameters info, etc.
        """
        if not self.parameters:
            raise ValueError("No parameters defined. Use add_parameter() first.")
        
        # Get parameter names and values
        param_names = list(self.parameters.keys())
        param_values = [self.parameters[name]['values'] for name in param_names]
        
        # Generate all combinations using itertools.product
        combinations = []
        for combo in product(*param_values):
            param_dict = dict(zip(param_names, combo))
            param_dict['index'] = len(combinations)
            combinations.append(param_dict)
        
        self.total_combinations = len(combinations)
        
        # Create DataFrame
        df = pd.DataFrame(combinations)
        
        # Generate info dictionary
        self.generation_info = {
            'total_combinations': self.total_combinations,
            'num_parameters': len(self.parameters),
            'parameter_info': {
                name: {
                    'resolution': info['resolution'],
                    'scale': info['scale'],
                    'range': f"[{info['min']:.2e}, {info['max']:.2e}]"
                }
                for name, info in self.parameters.items()
            }
        }
        
        return df, self.generation_info
    
    def export_to_csv(self, df: pd.DataFrame, num_files: int = 1, 
                     output_dir: str = 'parameters', 
                     file_prefix: str = 'parameters') -> Dict:
        """
        Export parameter combinations to CSV files.
        
        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing parameter combinations = parameters
        num_files : int, optional
            Number of CSV files to split the combinations into (default: 1)
        output_dir : str, optional
            Output directory (default: 'parameters')
        file_prefix : str, optional
            Prefix for output files (default: 'parameters')
        
        Returns
        -------
        export_info : Dict
            Information about the export process
        """
        # Create output directory
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        total_rows = len(df)
        
        if num_files == 1:
            # Single file export
            filename = f"{file_prefix}.csv"
            filepath = os.path.join(output_dir, filename)
            df.to_csv(filepath, index=False)
            
            export_info = {
                'total_combinations': total_rows,
                'num_files': 1,
                'combinations_per_file': [total_rows],
                'output_directory': output_dir,
                'files_created': [filepath]
            }
        else:
            # Multiple files export
            rows_per_file = total_rows // num_files #divise et garde l'entier de la division du nombre de row // num_files
            remainder = total_rows % num_files # gère le rest de la division et ajouter les lignes de plus si le reste est supérieur à 0
            
            export_info = {
                'total_combinations': total_rows,
                'num_files': num_files,
                'combinations_per_file': [],
                'output_directory': output_dir,
                'files_created': []
            }
            
            start_index = 0
            for i in range(num_files):
                end_index = start_index + rows_per_file
                if i < remainder:
                    end_index += 1
                
                df_chunk = df.iloc[start_index:end_index].copy()
                filename = f"{file_prefix}_{i+1}.csv"
                filepath = os.path.join(output_dir, filename)
                df_chunk.to_csv(filepath, index=False)
                
                export_info['combinations_per_file'].append(len(df_chunk))
                export_info['files_created'].append(filepath)
                start_index = end_index
        
        return export_info
    
    def print_info(self, generation_info: Dict, export_info: Optional[Dict] = None) -> None:
        """
        Print detailed information about the parameter generation and export.
        
        Parameters
        ----------
        generation_info : Dict
            Generation information from generate_combinations()
        export_info : Dict, optional
            Export information from export_to_csv()
        """
        print("=" * 60)
        print("PARAMETER GENERATION SUMMARY")
        print("=" * 60)
        
        print(f"Total combinations: {generation_info['total_combinations']:,}")
        print(f"Number of parameters: {generation_info['num_parameters']}")
        print()
        
        print("Parameter Details:")
        print("-" * 40)
        for name, info in generation_info['parameter_info'].items():
            print(f"  {name}:")
            print(f"    Resolution: {info['resolution']}")
            print(f"    Scale: {info['scale']}")
            print(f"    Range: {info['range']}")
        print()
        
        if export_info:
            print("CSV Export Summary:")
            print("-" * 40)
            print(f"Output directory: {export_info['output_directory']}")
            print(f"Number of CSV files: {export_info['num_files']}")
            print(f"Combinations per file: {export_info['combinations_per_file']}")
            print(f"Files created: {len(export_info['files_created'])}")


def quick_generate(param_config: Dict, num_files: int = 1, 
                  output_dir: str = 'parameters', file_prefix: str = 'parameters') -> Tuple[pd.DataFrame, Dict]:
    """
    Quick function to generate parameters and export to CSV with minimal setup.
    
    Parameters
    ----------
    param_config : Dict
        Parameter configuration. Format:
        {
            'param_name': {'min': float, 'max': float, 'resolution': int, 'scale': str},
            ...
        }
    num_files : int, optional
        Number of CSV files to create (default: 1)
    output_dir : str, optional
        Output directory for CSV files (default: 'parameters')
    file_prefix : str, optional
        Prefix for output files (default: 'parameters')
    
    Returns
    -------
    df : pd.DataFrame
        DataFrame containing all parameter combinations
    export_info : Dict
        Export information including file paths and distribution
    
    Examples
    --------
    >>> config = {
    ...     'hk': {'min': 1e-8, 'max': 1e-2, 'resolution': 40, 'scale': 'log'},
    ...     'sy': {'min': 0.001, 'max': 0.03, 'resolution': 40, 'scale': 'linear'}
    ... }
    >>> df, info = quick_generate(config, num_files=6)
    """
    generator = ParameterGenerator()
    
    # Add parameters
    for name, config in param_config.items():
        generator.add_parameter(
            name=name,
            min_val=config['min'],
            max_val=config['max'],
            resolution=config['resolution'],
            scale=config.get('scale', 'auto')
        )
    
    # Generate combinations
    df, gen_info = generator.generate_combinations()
    
    # Export to CSV
    export_info = generator.export_to_csv(df, num_files, output_dir, file_prefix)
    
    # Print information
    generator.print_info(gen_info, export_info)
    
    return df, export_info

#%% Example usage
if __name__ == "__main__": # permet d'executer cette section de code uniquement dans le fichier principal create_param_hk_sy.py
    
    # Example 1: Recreate your original parameters (hk, sy)
    # print("\n" + "="*60)
    # print("EXAMPLE 1: 10x10 grid (exdp, sy)")
    # print("="*60)
    
    # original_config = {
    #     'hk': {'min': 1e-8, 'max': 1e-4, 'resolution': 10, 'scale': 'log'},
    #     'sy': {'min': 1e-1, 'max': 10, 'resolution': 10, 'scale': 'log'}
    # }
    # df1, info1 = quick_generate(
    #     original_config, 
    #     num_files=8, 
    #     output_dir=r"C:\Users\theat\Documents\Python\01_Git_Repository\01-HMPdev-sewage\users\thea\parameters",
    #     file_prefix="parameters_hk_sy"
    # )
    
    # Example 2: New parameters for EVT calibration (exdp, sy) with fixed hk
    print("\n" + "="*60)
    print("EXAMPLE 2: exdp x sy grid (for EVT calibration with fixed hk)")
    print("="*60)
    evt_config = {
        'exdp': {'min': 1, 'max': 30, 'resolution': 10, 'scale': 'linear'},
        'sy': {'min': 1, 'max': 30, 'resolution': 10, 'scale': 'linear'}
    }
    df2, info2 = quick_generate(
        evt_config, 
        num_files=8, 
        output_dir=r"C:\Users\theat\Documents\Python\01_Git_Repository\01-HMPdev-sewage\users\thea\parameters",
        file_prefix="parameters_exdp_sy"
    )
    
    # Example 3: Three parameters (hk, sy, exdp) - Full calibration
    # print("\n" + "="*60)
    # print("EXAMPLE 3: Full 3D grid (hk, sy, exdp)")
    # print("="*60)
    # full_config = {
    #     'hk': {'min': 1e-8, 'max': 1e-4, 'resolution': 5, 'scale': 'log'},
    #     'sy': {'min': 0.5, 'max': 5.0, 'resolution': 5, 'scale': 'linear'},
    #     'exdp': {'min': 0.5, 'max': 3.0, 'resolution': 5, 'scale': 'linear'}
    # }
    # df3, info3 = quick_generate(
    #     full_config, 
    #     num_files=8, 
    #     output_dir=r"C:\Users\theat\Documents\Python\01_Git_Repository\01-HMPdev-sewage\users\thea\parameters",
    #     file_prefix="parameters_hk_sy_exdp"
    # )
    
    print("\n" + "="*60)
    print("ALL PARAMETER FILES GENERATED SUCCESSFULLY!")
    print("="*60)
    print(f"\nTotal parameter files created in 'parameters' folder:")
    # print(f"  - Example 1 (hk, sy): {info1['num_files']} files with {info1['total_combinations']} combinations")
    print(f"  - Example 2 (exdp, sy): {info2['num_files']} files with {info2['total_combinations']} combinations")
    # print(f"  - Example 3 (hk, sy, exdp): {info3['num_files']} files with {info3['total_combinations']} combinations")
# %%
