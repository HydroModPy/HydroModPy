# coding:utf-8

import numpy as np
import xsimlab as xs

from fastscape.models import basic_model
from fastscape.processes import (StreamPowerChannel, SurfaceToErode, UniformRectilinearGrid2D, MultipleFlowRouter)

from osgeo import gdal

import os

# Generates synthetic topographies using Fastscape library

# Typical usage:

#    # Import
#    from topogen import Topo

#    # Create the Topo object with the parameters you want (see below)
#    topo = Topo(slope_exp=1.3, steps=100)

#    # Export output
#    topo.export('dem.tif') # Will also export drainage as 'dem_drn.tif' and flow directions pointers as 'dem_ptr.tif'


# Parameters:
# Stream power-law equation: [fluvial erosion] = k_coef * [drainage area] ^ area_exp * [slope] ^ slope_exp

#    uplift_rate  float
#    k_coef       float  scaling coefficient for erosive intensity
#    area_exp     float  exponent defining how erosion increases with river drainage area
#    slope_exp    float  exponent defining how erosion increases with slope
#    slope_limit  float  greatest possible stable slope. Hillslopes are cut if they exceed this slope.

#    size:        float  length of the simulated area (side of the square)
#    resolution   int    grid length in pixel intervals
#    max_time     float  simulation time
#    steps        int    number of time steps
#    out_steps    int    number of time steps that are kept in memory. Last step is always kept if out_steps > 0
#    verbose      bool   whether to flood the terminal with a pretty progressbar and other superfluous stuff.

class Topo:
    def __init__(self, verbose=True, **kwargs):
        #self.parameters = kwargs
        self.setup(verbose=verbose, **kwargs)
        self.generate(verbose=verbose)

    def setup(self, uplift_rate=1e-3, k_coef=2e-6, area_exp=0.6, slope_exp=1.5, slope_limit=0.5, size=2.5e4, resolution=200, max_time=2e7, steps=500, out_steps=1, verbose=True): # Disabled: diffusivity=1e-1, uplift_target=500.
        
        if verbose:
            char_length = ((uplift_rate/k_coef)**(1/area_exp) * slope_limit**(-slope_exp/area_exp))**0.5
            print('Characteristic length expected: {:6.2f} ({:6.4f} pixels)'.format(char_length, char_length/125))

        self.timesteps = np.linspace(0, max_time, steps+1)
        outsteps_exact = np.linspace(0, max_time, out_steps+1)[1:] # Drop first element
        outsteps_diff = np.abs(self.timesteps[np.newaxis,:] - outsteps_exact[:,np.newaxis])
        self.outsteps = self.timesteps[outsteps_diff.argmin(axis=1)]
        del outsteps_exact, outsteps_diff

        self.in_ds = xs.create_setup(
            model=model,
            clocks={
                'time': self.timesteps, #2e7
                'out': self.outsteps,
            },
            master_clock='time',
            input_vars={
                'grid__shape': [resolution+1, resolution+1],
                'grid__length': [size, size],
                'boundary__status': 'fixed_value',
                'uplift__rate': uplift_rate,
                #'uplift__target': uplift_target,
                'spl': {
                    'k_coef': k_coef,
                    'area_exp': area_exp,
                    'slope_exp': slope_exp,
                },
                #'diffusion__diffusivity': diffusivity,
                'slope__limit': slope_limit,
                'flow__slope_exp': 1.,
            },
            output_vars={
                'topography__elevation': 'out',
                'terrain__slope': 'out',
                'drainage__area': 'out',
                'flow__donors': 'out',
                'flow__receivers': 'out',
                'flow__weights': 'out',
                #'flow__slope': 'out',
            }
        )

        if verbose:
            print(self.in_ds)

    def generate(self, verbose=True):
        if verbose:
            with xs.monitoring.ProgressBar():
                self.out_ds = self.in_ds.xsimlab.run(model=model)
        else:
            self.out_ds = self.in_ds.xsimlab.run(model=model)

    def make_receiver_array(self, **kwargs):
        receivers = np.array(self.out_ds.flow__receivers[0])
        weights = np.array(self.out_ds.flow__weights[0])
        topo = np.array(self.out_ds.topography__elevation[-1])
        return make_pointer_array(receivers, weights, topo.shape, **kwargs)

    def make_donor_array(self, **kwargs):
        donors = np.array(self.out_ds.flow__donors[0])
        weights = np.array(self.out_ds.flow__receivers[0])
        topo = np.array(self.out_ds.topography__elevation[-1])
        return make_pointer_array(donors, weights, topo.shape, **kwargs)

    def get_topo(self, step=-1):
        return np.array(self.out_ds.topography__elevation[step])

    def _make_raster(self, filename, data, dtype=gdal.GDT_Float32, **kwargs):
        drv = gdal.GetDriverByName('GTiff')
        raster = drv.Create(filename, int(self.in_ds.grid__shape[1]), int(self.in_ds.grid__shape[0]), 1, dtype)
        raster.SetGeoTransform((0., self.in_ds.grid__length[1]/(self.in_ds.grid__shape[1]-1), 0., 0., 0., -self.in_ds.grid__length[0]/(self.in_ds.grid__shape[0]-1)))
        band = raster.GetRasterBand(1)
        #print(np.array(data))
        band.WriteArray(np.array(data))
        metadata = {
            'uplift_rate': float(self.in_ds.uplift__rate),
            'k_coef': float(self.in_ds.spl__k_coef),
            'area_exp': float(self.in_ds.spl__area_exp),
            'slope_exp': float(self.in_ds.spl__slope_exp),
            'slope_limit': float(self.in_ds.slope__limit),
        }
        metadata.update(kwargs)
        for k, v in metadata.items():
            metadata[k] = str(v)
        raster.SetMetadata(metadata)
        band.ComputeStatistics(True)
        band.FlushCache()

    def export(self, dem='dem.tif', drainage_area=None, pointers=None, step=-1):
        time = self.outsteps[step]
        if len(self.timesteps) == 1:
            dt = time
        else:
            i = max(np.searchsorted(self.timesteps, time), 1)
            dt = self.timesteps[i] - self.timesteps[i-1]
        dem = os.path.expanduser(dem)
        if drainage_area is None:
            drainage_area = '{}_drn{}'.format(*os.path.splitext(dem))
        if pointers is None:
            pointers = '{}_ptr{}'.format(*os.path.splitext(dem))

        self._make_raster(dem, self.out_ds.topography__elevation[step], type='dem', time=time, dt=dt)
        self._make_raster(drainage_area, self.out_ds.drainage__area[step], type='drainage', time=time, dt=dt)
        self._make_raster(pointers, self.make_receiver_array(), type='receivers', time=time, dt=dt, dtype=gdal.GDT_Byte)

def stabilize_slope(elev, slope_max):
    old_err = np.seterr(invalid='ignore') # Disable error for invalid square root

    slope_max2 = 2*slope_max**2
    neigh_NS = np.full(elev.shape, np.inf)
    neigh_EW = np.full(elev.shape, np.inf)
    while True:
        neigh_NS[:,:] = np.inf
        neigh_EW[:,:] = np.inf
        neigh_NS[1:,:] = elev[:-1,:] # Elevation at North
        neigh_EW[:,:-1] = elev[:,1:] # Elevation at East
        neigh_NS[:-1,:] = np.minimum(neigh_NS[:-1,:], elev[1:,:]) # Elevation at South, if lower than North
        neigh_EW[:,1:] = np.minimum(neigh_EW[:,1:], elev[:,:-1]) # Elevation at West, if lower than East

        neigh_diff = np.abs(neigh_EW - neigh_NS)
        elev_max = np.where(neigh_diff < slope_max,
                (neigh_EW+neigh_NS+np.sqrt(slope_max2-neigh_diff**2)) / 2,
                np.minimum(neigh_NS, neigh_EW) + slope_max
        )

        if np.all(elev <= elev_max):
            np.seterr(**old_err) # Push old error settings back
            return elev
        elev = np.minimum(elev, elev_max)

@xs.process
class HillslopeLimit:
    limit = xs.variable(description='maximal stable slope')

    elevation = xs.foreign(SurfaceToErode, 'elevation')
    dx = xs.foreign(UniformRectilinearGrid2D, 'dx')
    #diff_erosion = xs.foreign(LinearDiffusion, 'erosion')
    stream_erosion = xs.foreign(StreamPowerChannel, 'erosion')
    erosion = xs.variable(
        dims = ('y', 'x'),
        intent='out',
        groups='erosion',
    )

    def run_step(self):
        elev = self.elevation - self.stream_erosion
        hdiff_max = self.limit*self.dx
        self.erosion = elev - stabilize_slope(elev, hdiff_max)

model = basic_model
model = model.drop_processes('diffusion')
model = model.update_processes({
    'slope': HillslopeLimit,
    'flow': MultipleFlowRouter,
})

def make_pointer_array(pointers, weights, shape, multiple=True):
    X = shape[1]
    pointer_match = { # 8 directions
        -X+1:  1,
           1:  2,
         X+1:  4,
         X  :  8,
         X-1: 16,
          -1: 32,
        -X-1: 64,
        -X  :128,
    }
    pointer_bytes = np.zeros(pointers.shape[0], dtype='u1')
    links = {}
    if multiple:
        for i in range(pointers.shape[0]):
            byte = 0
            for j in range(8):
                d = pointers[i,j]
                if np.isnan(d) or d < 0:
                    break

                d = int(d) - i
                if weights[i,j] > 0. and d in pointer_match:
                    byte |= pointer_match[d]

            pointer_bytes[i] = byte
    else:
        for i in range(pointers.shape[0]):
            n = weights[i].argmax()
            d = pointers[i,n]
            if np.isnan(d) or d < 0:
                continue

            d = int(d) - i
            if weights[i,n] > 0. and d in pointer_match:
                pointer_bytes[i] = pointer_match[d]

    return pointer_bytes.reshape(shape)
