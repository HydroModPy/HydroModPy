import numpy as np

def slope_twoside(a, spacing=1.0):
    grad_y, grad_x = np.gradient(a, spacing, spacing)
    return (grad_x**2 + grad_y**2)**0.5

def slope_down_inter(a, spacing=1.0):
    neigh_NS = a.copy()
    neigh_EW = a.copy()
    neigh_NS[1:,:] = np.minimum(neigh_NS[1:,:], a[:-1,:]) # Elevation at North
    neigh_EW[:,:-1] = np.minimum(neigh_EW[:,:-1], a[:,1:]) # Elevation at East
    neigh_NS[:-1,:] = np.minimum(neigh_NS[:-1,:], a[1:,:]) # Elevation at South, if lower than North
    neigh_EW[:,1:] = np.minimum(neigh_EW[:,1:], a[:,:-1]) # Elevation at West, if lower than East

    return ((a-neigh_NS)**2 + (a-neigh_EW)**2)**0.5 / spacing

def slope_down_d8(a, spacing=1.0, nodata=-99999., minimum=-100.):
    isvalid = (a != nodata) & (a >= minimum)
    sqr_half = 0.5**0.5
    steepest = np.zeros(a.shape)

    hdiff = (a[:-1,:]-a[1:,:]) * (isvalid[:-1,:] & isvalid[1:,:]) # Positive = slope towards South
    steepest[:-1,:] = np.maximum(steepest[:-1,:], hdiff) # to South
    steepest[1:,:] = np.maximum(steepest[1:,:], -hdiff) # to North
    hdiff = (a[:,:-1]-a[:,1:]) * (isvalid[:,:-1] & isvalid[:,1:]) # Positive = slope towards East
    steepest[:,:-1] = np.maximum(steepest[:,:-1], hdiff) # to East
    steepest[:,1:] = np.maximum(steepest[:,1:], -hdiff) # to West

    hdiff = (a[:-1,:-1]-a[1:,1:])*sqr_half * (isvalid[:-1,:-1] & isvalid[1:,1:]) # Positive = slope towards SE
    steepest[:-1,:-1] = np.maximum(steepest[:-1,:-1], hdiff) # to SE
    steepest[1:,1:] = np.maximum(steepest[1:,1:], -hdiff) # to NW
    hdiff = (a[1:,:-1]-a[:-1,1:])*sqr_half * (isvalid[1:,:-1] & isvalid[:-1,1:]) # Positive = slope towards NE
    steepest[1:,:-1] = np.maximum(steepest[1:,:-1], hdiff) # to NE
    steepest[:-1,1:] = np.maximum(steepest[:-1,1:], -hdiff) # to SW

    return steepest / spacing
