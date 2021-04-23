#!/usr/bin/env python3

import util
import numpy as np
import matplotlib.pyplot as plt

def plot_seepage_RK(*watersheds):
    for watershed in watersheds:
        X = []
        Y = []
        for model_name in util.loop_models(watershed, 'R{:d}'):
            desc = {
                'watershed': watershed,
                'model_name': model_name,
            }
            data = util.load_data(**desc)
            meta = util.load_meta(**desc)
            X.append(meta['climatic'][0] / meta['hyd_cond'])
            Y.append((data['outflow'][0] > 0).mean())
        
        plt.plot(X, Y, label=watershed)
    
    plt.xlabel('R/K')
    plt.xscale('log')
    plt.ylabel('Seepage area fraction')
    plt.yscale('log')
    plt.legend()

def inequality(a):
    aa = np.cumsum(np.sort(a, axis=None))
    return 1 - aa.sum() / aa[-1] / (aa.size+1) * 2

def plot_seepage_ineq_RK(*watersheds):
    for watershed in watersheds:
        X = []
        Y = []
        for model_name in util.loop_models(watershed, 'R{:d}'):
            #print(watershed, model_name)
            desc = {
                'watershed': watershed,
                'model_name': model_name,
            }
            data = util.load_data(**desc)
            meta = util.load_meta(**desc)
            X.append(meta['climatic'][0] / meta['hyd_cond'])
            ineq = inequality(data['outflow'][0])
            Y.append(ineq)
        
        plt.plot(X, Y, label=watershed)
    
    plt.xlabel('R/K')
    plt.xscale('log')
    plt.ylabel('Seepage area inequality')
    #plt.yscale('log')
    plt.legend()

functions = {
    'seep_RK': plot_seepage_RK,
    'seep_ineq_RK': plot_seepage_ineq_RK,
}

if __name__ == '__main__':
    import sys

    f = sys.argv[1]
    if f in functions:
        functions[f](*sys.argv[2:])
    plt.show()
