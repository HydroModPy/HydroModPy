# -*- coding: utf-8 -*-
"""
Created on Mon May 24 17:03:47 2021

@author: dreuzy
"""
import matplotlib.pyplot as plt
import matplotlib        as mpl
import os
from pylab import *


def figure_init(xlab=None,ylab=None,figname=None):
    """ defines figure style to be applied to all callign figures"""
    plt.figure()#(figsize=(4,4))
    plt.xlabel(xlab,fontsize=16,fontweight='bold')
    plt.ylabel(ylab,fontsize=14,fontweight='bold')
    plt.xticks(fontsize=14)
    plt.yticks(fontsize=14)
    plt.grid(True)
    plt.title(figname,fontsize=22,fontweight='bold')
    
    ax = gca()
    # ax.axhline(linewidth=4, color="k") 
    # ax.axvline(linewidth=4, color="k")   
            
    # fontsize = 14
    # ax.xaxis.set_tick_params(width=3)
    # ax.yaxis.set_tick_params(width=3)
    # for tick in ax.xaxis.get_major_ticks():
    #     tick.label1.set_fontsize(fontsize)
    #     # tick.label1.set_fontweight('bold')
    # for tick in ax.yaxis.get_major_ticks():
    #     tick.label1.set_fontsize(fontsize)
    #     # tick.label1.set_fontweight('bold')
    
def figure_close(filename=None):
    """ defines figure style to be applied to all callign figures"""
    if filename != None : 
        plt.savefig(filename,dpi=300)
        plt.close()

def cmap_white_jet():
    """ Colormap jet with lowest values white instead of blue"""
    k=4
    # set upper part: 4 * 256/4 entries
    upper = mpl.cm.jet(np.arange(256))
    # set lower part: 1 * 256/4 entries
    # - initialize all entries to 1 to make sure that the alpha channel (4th column) is 1
    lower = np.ones((int(256/k),4))
    # - modify the first three columns (RGB):
    #   range linearly between white (1,1,1) and the first color of the upper colormap
    for i in range(3):
        lower[:,i] = np.linspace(1, upper[0,i], lower.shape[0])
    # combine parts of colormap
    cmap = np.vstack(( lower, upper ))
    # convert to matplotlib colormap
    cmap = mpl.colors.ListedColormap(cmap, name='myColorMap', N=cmap.shape[0])
    return cmap

def hist_scatter(histo=False,histox=None,histoy=None,histolegend="",scatter=False,scatterx=None,scattery=None,scatterlegend="",refx=None,refy=None,reflegend="",namex=None,namey=None,namefig=None,directory=None,file=None):
    """ Histogram and scatter plot """
    # Initialization of figure
    figure_init(xlab=namex,ylab=namey,figname=namefig)
    minix=math.inf
    maxix=-math.inf
    miniy=math.inf
    maxiy=-math.inf
    # Histogram
    if histo == True : 
        plt.hist2d(histox,histoy,bins=50,cmap=cmap_white_jet(),label=histolegend)
        plt.colorbar()
        minix=min(minix,min(histox))
        maxix=max(maxix,max(histox))
        miniy=min(miniy,min(histoy))
        maxiy=max(maxiy,max(histoy))
    # Scatter
    if scatter == True :           
        plt.scatter(scatterx,scattery,marker='+',c='r',s=40,label=scatterlegend)
        minix=min(minix,min(scatterx))
        maxix=max(maxix,max(scatterx))
        miniy=min(miniy,min(scattery))
        maxiy=max(maxiy,max(scattery))
    # Reference
    if refx != None : 
        plt.scatter(refx,refy,marker='o',c='r',s=150,label=reflegend)
        minix=min(minix,refx)
        maxix=max(maxix,refx)
        miniy=min(miniy,refy)
        maxiy=max(maxiy,refy)
    # Figure limits
    if minix != maxix: 
        plt.xlim(minix,maxix)
    if miniy != maxiy: 
        plt.ylim(miniy,maxiy)
    # Figure Management
    plt.legend()
    plt.show()
    if directory != None : 
        figure_close(filename=os.path.join(directory,file))

