#!/usr/bin/env python3

import numpy as np
import xsimlab as xs

from fastscape.models import basic_model
from fastscape.processes import (LinearDiffusion, StreamPowerChannel, SurfaceToErode, UniformRectilinearGrid2D, MultipleFlowRouter, BlockUplift, BorderBoundary, SurfaceTopography)
from stability import stabilize_slope

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

@xs.process
class CorrectiveUplift:
    target = xs.variable(
        dims=(),
        description='mean elevation target'
    )

    shape = xs.foreign(UniformRectilinearGrid2D, 'shape')
    status = xs.foreign(BorderBoundary, 'border_status')
    #fs_context = xs.foreign(FastscapelibContext, 'context')
    elevation = xs.foreign(SurfaceTopography, 'elevation')

    uplift = xs.variable(
        dims=[(), ('y', 'x')],
        intent='out',
        groups=['bedrock_forcing_upward', 'surface_forcing_upward'],
        description='imposed vertical uplift'
    )

    def initialize(self):
        # build uplift rate binary mask according to border status
        self._mask = np.ones(self.shape)

        _all = slice(None)
        slices = [(_all, 0), (_all, -1), (0, _all), (-1, _all)]

        for status, border in zip(self.status, slices):
            if status == 'fixed_value':
                self._mask[border] = 0.
        self._count = self._mask.sum()

    def run_step(self):
        hdiff = self.target - (self.elevation*self._mask).sum()/self._count
        self.uplift = self._mask * hdiff

model = basic_model
model = model.drop_processes('diffusion')
model = model.update_processes({
    'slope': HillslopeLimit,
    'flow': MultipleFlowRouter,
#    'uplift': CorrectiveUplift,
})

class Topo:
    def __init__(self, **kwargs):
        self.parameters = kwargs
        self.setup(**kwargs)
        self.generate()

    def setup(self, uplift_rate=1e-3, uplift_target=500., k_coef=2e-6, area_exp=0.6, slope_exp=1.5, slope_limit=0.5, size=2.5e4, resolution=200, max_time=2e7, steps=500, out_steps=1): # Disabled: diffusivity=1e-1
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
                #'flow__slope': 'out',
            }
        )

        print(self.in_ds)

    def generate(self):
        with xs.monitoring.ProgressBar():
            self.out_ds = self.in_ds.xsimlab.run(model=model)

    def get_topo(self, step=-1):
        return np.array(self.out_ds.topography__elevation[step])

    def show(self, step=-1, extent=None, **kwargs):
        import matplotlib.pyplot as plt
        if extent is None:
            extent = (0, self.in_ds.grid__length[1], 0, self.in_ds.grid__length[0])
        print(float(self.out_ds.topography__elevation[step].mean()))
        return plt.imshow(self.out_ds.topography__elevation[step], extent=extent, **kwargs)

    def _make_raster(self, filename, data):
        from osgeo import gdal
        drv = gdal.GetDriverByName('GTiff')
        raster = drv.Create(filename, int(self.in_ds.grid__shape[1]), int(self.in_ds.grid__shape[0]), 1, gdal.GDT_Float32)
        raster.SetGeoTransform((0., self.in_ds.grid__length[1]/(self.in_ds.grid__shape[1]-1), 0., 0., 0., -self.in_ds.grid__length[0]/(self.in_ds.grid__shape[0]-1)))
        band = raster.GetRasterBand(1)
        #print(np.array(data))
        band.WriteArray(np.array(data))
        band.ComputeStatistics(True)
        band.FlushCache()

    def export(self, dem=None, drainage_area=None, slope=None, step=-1):
        if dem is not None:
            self._make_raster(dem, self.out_ds.topography__elevation[step])
        if drainage_area is not None:
            self._make_raster(drainage_area, self.out_ds.drainage__area[step])
        if slope is not None:
            self._make_raster(slope, self.out_ds.terrain__slope[step])

    def plot_slope(self, step=-1):
        from slope import slope_down_d8
        import matplotlib.pyplot as plt
        t = self.get_topo(step=step)
        s = slope_down_d8(t)
        d = np.array(self.out_ds.drainage__area[step])
        smin = s[s > 0].min()
        smax = s.max()
        dmin = d.min()
        dmax = d.max()

        U = in_ds.uplift__rate
        K = in_ds.spl__k_coef
        m = in_ds.spl__area_exp
        n = in_ds.spl__slope_exp
        l = in_ds.slope__limit
        critical_d = (U/K)**(1/m) * l**(-n/m)
        cst = (U/K)**(1/n)
        if dmin < critical_d and dmax > critical_d:
            X = [dmin, critical_d, dmax]
            Y = [l, l, cst * A**(-m/n)]
            # TODO finish that
