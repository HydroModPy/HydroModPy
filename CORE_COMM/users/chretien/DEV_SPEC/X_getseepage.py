#!/usr/bin/env python3

import numpy as np
import matplotlib.pyplot as plt
import util
import sys

desc = {
    'watershed': sys.argv[1],
    'model_name': sys.argv[2],
}

data = util.load_data(**desc)
#meta = util.load_meta(**desc)
#plt.imshow(data['outflow'][0])
plt.subplot(1,2,1)
plt.imshow(data['ztop'])
plt.colorbar(orientation='horizontal')
plt.subplot(1,2,2)
plt.imshow(np.maximum(data['head'][0]-data['ztop'], 0))
plt.colorbar(orientation='horizontal')
plt.show()
