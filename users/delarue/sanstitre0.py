# -*- coding: utf-8 -*-
"""
Created on Mon Mar 24 14:35:57 2025

@author: delarueo
"""

    # ---- Grid and Input
    def load_input_grid(self, path_to_grid: str):
        """
        Load input grid data.
    
        Parameters
        ----------
        path_to_grid : str
            The path to the csv file that contains the geomatic data, surface
            conditions, and soil and design data for each cell of the grid
            dividing the study area.
        """
        self.grid_filename = osp.abspath(path_to_grid)
        print(f'Reading grid data from {path_to_grid}...')
        if not osp.exists(path_to_grid):
            self.grid = None
            print("Grid input csv file does not exist.")
        else:
            self.grid = load_grid_from_csv(path_to_grid)
            print('Grid data read successfully from input csv file.')
        


    def get_latlon_for_cellnames(self, cells):
        """
        Return a numpy array with latitudes and longitudes of the provided
        cells cid. Latitude and longitude for cids that are missing from
        the grid are set to nan.
        """
        lat = np.array(self.grid['lat_dd'].reindex(cells).tolist())
        lon = np.array(self.grid['lon_dd'].reindex(cells).tolist())
        return lat, lon





def load_grid_from_csv(path_togrid):
    """
    Load the csv that contains the infos required to evaluate regional
    groundwater recharge with HELP.
    """
    grid = pd.read_csv(path_togrid, dtype={'cid': 'str'})

    fname = osp.basename(path_togrid)
    req_keys = ['cid', 'lat_dd', 'lon_dd', 'run', 'context']
    for key in req_keys:
        if key not in grid.keys():
            raise KeyError("No attribute '{}' found in {}".format(key, fname))

    # Set 'cid' as the index of the dataframe.
    grid.set_index(['cid'], drop=False, inplace=True)

    return grid