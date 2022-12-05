import numpy as np

def fixlayers(top, bots, min_overlap=1.0):
    for bot in bots:
        max_bot = top.copy()
        max_bot[:-1,:] = np.minimum(max_bot[:-1,:], top[1:,:])
        max_bot[1:,:] = np.minimum(max_bot[1:,:], top[:-1,:])
        max_bot[:,:-1] = np.minimum(max_bot[:,:-1], top[:,1:])
        max_bot[:,1:] = np.minimum(max_bot[:,1:], top[:,:-1])
        max_bot -= min_overlap
        too_high = bot > max_bot
        if np.any(too_high):
            bot[too_high] = max_bot[too_high]

        top = bot
