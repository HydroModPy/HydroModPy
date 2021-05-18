#!/usr/bin/env python3

import util
from osgeo import gdal
import os
import sys
import matplotlib.pyplot as plt
import numpy as np

watershed, model_name, drnfile = sys.argv[1:4]
desc = {
    'watershed': watershed,
    'model_name': model_name,
}
data = util.load_data(**desc)
meta = util.load_meta(**desc)

drnarea = gdal.Open(os.path.expanduser(drnfile)).ReadAsArray()
wateroffset = data['head'][0] - data['ztop']

out = False
if len(sys.argv) > 4:
    out = True
    outfile = sys.argv[4]

fig = plt.gcf()
fig.set_size_inches(12,8)
#fig.set_dpi(300)
plt.subplot(2,2,1)
plt.scatter(drnarea, wateroffset, s=2, alpha=1.0, edgecolors='none', rasterized=True)
plt.xscale('log')
#plt.yscale('log')
plt.xlabel('Drainage area')
plt.ylabel('Relative piezometric level')
plt.title('Piezometric levels')

is_seepage = wateroffset >= 0.0

plt.subplot(2,2,2)
nbins = 100
bins = np.geomspace(drnarea.min(), drnarea.max(), nbins+1)
plt.hist([drnarea[~is_seepage], drnarea[is_seepage]], bins=bins, stacked=True)
plt.legend(['No seepage', 'Seepage'])
plt.xscale('log')
plt.xlabel('Drainage area')
plt.ylabel('Number of points')
plt.title('Statistical repartition')

plt.subplot(2,2,3)
n_noseep, _ = np.histogram(drnarea[~is_seepage], bins=bins)
n_seep, _ = np.histogram(drnarea[is_seepage], bins=bins)
n_tot = n_noseep + n_seep
bin_center = np.sqrt(bins[:-1]*bins[1:])
plt.stackplot(bin_center, n_noseep/n_tot, n_seep/n_tot)
plt.legend(['No seepage', 'Seepage'])
plt.xscale('log')
plt.xlabel('Drainage area')
plt.ylabel('Probability')
plt.title('Statistical repartition — normed')

plt.subplot(2,2,4)
drnarea_flat = drnarea.flatten()
drnarea_order = np.argsort(drnarea_flat)
is_seepage_order = is_seepage.flatten()[drnarea_order]
varyline = np.cumsum(is_seepage_order*2-1)
plt.plot(drnarea_flat[drnarea_order], varyline)
plt.xscale('log')
plt.xlabel('Drainage area')
plt.ylabel('$n_{seepage}-n_{no\_seepage}$')
plt.title('Cumulative number of points')

min_order = varyline.argmin()
drnsplit = drnarea_flat[drnarea_order[min_order]]
print(min_order, drnsplit)
plt.scatter(drnsplit, varyline.min())

plt.suptitle('Relations between drainage and seepage for watershed {}, with $\\frac{{R}}{{K}}={:4.2e}$.'.format(watershed, meta['climatic'][0]/meta['hyd_cond']))
plt.tight_layout()
if out:
    plt.savefig(os.path.expanduser(outfile), dpi=300)
else:
    plt.show()
