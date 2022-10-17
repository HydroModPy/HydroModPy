#!/usr/bin/env python3

import topogen
import matplotlib.pyplot as plt
import numpy as np
import sys

if len(sys.argv) >= 2:
    n = int(sys.argv[1])
else:
    n = 1

for i in range(n):
    print(i+1)
    topo = topogen.Topo(max_time=4e6, steps=500, out_steps=500)

    hmean = np.mean(topo.out_ds.topography__elevation, axis=(1,2))
    hmax = np.max(topo.out_ds.topography__elevation, axis=(1,2))
    t = topo.in_ds.out

    (p,) = plt.plot(t, hmean)
    plt.plot(t, hmax, c=p.get_c(), linestyle='--')
plt.xlabel('Time')
plt.ylabel('Elevation')
plt.show()
