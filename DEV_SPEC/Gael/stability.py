import numpy as np

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
