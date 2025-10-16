# -*- coding: utf-8 -*-
"""
Created on Mon Feb 24 15:57:13 2025

@author: mathi
"""

import pandas as pd
from abc import ABC, abstractmethod

class PyhelpCsvManager(ABC):
    """Abstract base class for managing operations on PyHelp CSV input files."""
    
    def _save_csv(self, data: pd.DataFrame, output_path: str) -> None:
        """Save the DataFrame to a CSV file."""
        try:
            data.to_csv(output_path, index=False)
        except Exception as e:
            print(f"Error saving CSV file: {e}")
    
    @abstractmethod
    def display_data(self) -> None:
        """Display data"""
        pass

    @abstractmethod
    def list_parameters(self) -> None:
        """List parameters in the dataset"""
        pass
