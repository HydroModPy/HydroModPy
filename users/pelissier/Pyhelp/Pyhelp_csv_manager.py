# -*- coding: utf-8 -*-
"""
Created on Sat Jan 11 17:16:42 2025

@author: mathi
"""

from abc import ABC, abstractmethod
import pandas as pd
import rasterio

class PyhelpCsvManager(ABC):
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self.load_csv()

    def load_csv(self):
        return pd.read_csv(self.file_path)

    def save(self, data, output_path):
        data.to_csv(output_path, index=False)

    @abstractmethod
    def display_data(self):
        pass

    @abstractmethod
    def list_parameters(self):
        pass

class PyhelpGrid(PyhelpCsvManager):
    def __init__(self, file_path, dem_file_path):
        super().__init__(file_path)
        self.dem_file_path = dem_file_path
    
    def display_data(self):
        print("Données du fichier CSV:")
        print(self.data)
               
    def list_parameters(self):
        print("Liste des paramètres:")
        for c in self.data.columns:
            print(f"- {c}")            

    def dem_coordinate(self):
        dem_dataset = rasterio.open(self.dem_file_path)
        
        transform = dem_dataset.transform
        width = dem_dataset.width
        height = dem_dataset.height
        
        coordinates = []
        for row in range(height):
            for col in range(width):
                x, y = transform * (col, row)
                coordinates.append((x, y))  
                
        print(dem_dataset.crs)

        return coordinates

    def update_csv(self):

        coordinates = self.dem_coordinate()

        rows = len(coordinates)
        first_values = self.data.iloc[0]
        new_data = pd.DataFrame([first_values[3:].values] * rows, columns=self.data.columns[3:])

        new_data['cid'] = range(int(first_values['cid']), int(first_values['cid']) + rows)

        new_data['lat_dd'] = [coord[1] for coord in coordinates]
        new_data['lon_dd'] = [coord[0] for coord in coordinates]

        new_data = new_data[['cid', 'lat_dd', 'lon_dd'] + [col for col in new_data.columns if col not in ['cid', 'lat_dd', 'lon_dd']]]

        self.data = new_data
        self.save(self.data, self.file_path)



if __name__ == "__main__":
    
    csv_file_path = "C:/Users/mathi/Dev/pyhelp-master/pyhelp-test/example/example/input_grid_base1.csv"
    dem_file_path = "C:/Users/mathi/Dev/pyhelp-master/pyhelp-test/example/example/watershed_box_buff_dem.tif"  
    
    pyhelp_grid = PyhelpGrid(csv_file_path, dem_file_path)
    pyhelp_grid.display_data()
    
    pyhelp_grid.update_csv()   
    pyhelp_grid.display_data()
    
    #pyhelp_grid.list_parameters()

