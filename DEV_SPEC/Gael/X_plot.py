#!/usr/bin/env python3

import util
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcl
import os

# 'seep_rk w1 w2 w3 ...' : seepage area fraction in function of R/K
# 'seep_ineq_rk w1 w2 w3 ...' : plot seepage inequality (similar to Gini coefficient)'
# 'seep_pdf' : plot probability density function of seepage flux
# 'time_pdf' : plot probability density function of transit time

def iterate_models(*models):
    n = len(models) // 2
    for i in range(n):
        watershed, model_name = models[2*i:2*i+2]
        print('{} {}'.format(watershed, model_name))
        desc = {
            'watershed': watershed,
            'model_name': model_name,
        }
        yield desc

def variable_pdf(data, nbins=50, **kwargs):
    sdata = np.sort(data, axis=None)
    n = sdata.size - 1
    bins = np.linspace(0, n, nbins+1, dtype=int)
    xbins = sdata[bins]
    prob = (bins[1:]-bins[:-1]) / (xbins[1:]-xbins[:-1]) / n
    binsum = np.zeros(nbins)
    for i in range(nbins):
        binsum[i] = sdata[bins[i]+1:bins[i+1]].sum() + (sdata[bins[i]]+sdata[bins[i+1]])/2

    return plt.scatter(binsum / (bins[1:]-bins[:-1]), prob, s=5, edgecolor='none', **kwargs) #(xbins[:-1]+xbins[1:])/2

def inequality(a):
    aa = np.cumsum(np.sort(a, axis=None))
    return 1 - aa.sum() / aa[-1] / (aa.size+1) * 2

def haitjema_coef(data, meta):
    top = data['ztop']
    d = top.mean()
    H = data['head'][0].mean() - data['zbot'][-1].mean()
    R = meta['climatic'][-1]
    K = meta['hyd_cond']
    gt = meta['projection']['geodata']

    L2 = abs(gt[1]*gt[5] - gt[2]*gt[4]) * top.size
    m = 16

    return R*L2 / (m*K*H*d)

def critical_drainage(meta):
    dmeta = meta['dem_metadata']
    return (dmeta['uplift_rate'] / dmeta['k_coef']) ** (1/dmeta['area_exp']) * dmeta['slope_exp'] ** (dmeta['slope_exp']/dmeta['area_exp'])

class PlotFunctions:
    def __init__(self, **kwargs):
        self.params = {}

    def __call__(self, fname, *args, **kwargs):
        f = getattr(self, fname)
        f(*args, **kwargs)

    def fig(self, sx, sy, *args, **kwargs):
        sx = float(sx)
        sy = float(sy)
        fig = plt.gcf()
        fig.set_size_inches(sx, sy)
        if len(args) > 0:
            self(*args, **kwargs)

    def sub(self, x, y, *args, **kwargs):
        x = int(x)
        y = int(y)
        n = x*y
        i0 = 0
        iplot = 1
        for i, arg in enumerate(args):
            if arg == '+':
                if i > i0:
                    plt.subplot(x, y, iplot)
                    self(*args[i0:i], **kwargs)
                iplot += 1
                i0 = i+1
        if len(args) > i0+1:
            plt.subplot(x, y, iplot)
            self(*args[i0:], **kwargs)

    def seep_RK(self, *watersheds):
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
                X.append(meta['climatic'][-1] / meta['hyd_cond'])
                outflow = data['outflow'][0]#[0,1:-1,1:-1]
                Y.append((outflow > 0).mean())
            
            plt.plot(X, Y, label=watershed)
        
        plt.xlabel('R/K')
        plt.xscale('log')
        plt.ylabel('Seepage area fraction')
        plt.yscale('log')
        plt.legend()

    def view_seepage(self, watershed, model_name=None):
        if model_name is None:
            rk_needed = None
            for model_name in util.loop_models(watershed, 'R{:d}'):
                desc = {
                    'watershed': watershed,
                    'model_name': model_name,
                }
                data = util.load_data(**desc)
                meta = util.load_meta(**desc)
                outflow = data['outflow'][0]
                if rk_needed is None:
                    rk_needed = np.full(outflow.shape, np.inf)
                rk = meta['climatic'][-1] / meta['hyd_cond']
                seep = outflow > 0
                rk_needed[seep] = np.minimum(rk_needed[seep], rk)
            rk_needed[~np.isfinite(rk_needed)] = np.nan

            plt.imshow(rk_needed, norm=mcl.LogNorm(vmin=np.nanmin(rk_needed), vmax=np.nanmax(rk_needed)))
            plt.colorbar()
        else:
            desc = {'watershed': watershed, 'model_name': model_name}
            data = util.load_data(**desc)
            meta = util.load_meta(**desc)
            outflow = np.ma.masked_less_equal(data['outflow'][0], 0.)
            plt.imshow(outflow)

    def view_length(self, watershed, model_name):
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        meta = util.load_meta(**desc)
        length = data['path_length']
        print(length.mean())
        gt = meta['projection']['geodata']
        xsize = (gt[1]**2 + gt[4]**2)**0.5 * length.shape[1]
        ysize = (gt[2]**2 + gt[5]**2)**0.5 * length.shape[0]
        plt.imshow(length, norm=mcl.LogNorm(vmin=length[length>0].min(), vmax=length.max()), extent=(0., xsize, ysize, 0.), rasterized=True)
        plt.colorbar()

    def view_time(self, watershed, model_name):
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        meta = util.load_meta(**desc)
        time = data['path_time'] / 31536000.
        print(time.mean())
        gt = meta['projection']['geodata']
        xsize = (gt[1]**2 + gt[4]**2)**0.5 * time.shape[1]
        ysize = (gt[2]**2 + gt[5]**2)**0.5 * time.shape[0]
        plt.imshow(time, norm=mcl.LogNorm(vmin=time[time>0].min(), vmax=time.max()), extent=(0., xsize, ysize, 0.), rasterized=True)
        plt.colorbar()

    def seep_ineq_RK(self, *watersheds):
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

    def seep_pdf(self, *models):
        n = len(models) // 2
        for i in range(n):
            watershed, model_name = models[2*i:2*i+2]
            print('{} {}'.format(watershed, model_name))
            desc = {
                'watershed': watershed,
                'model_name': model_name,
            }
            data = util.load_data(**desc)
            outflow = data['outflow'][0,1:-1,1:-1]
            is_outflow = outflow > 0.0
            outflow = outflow[is_outflow]
            nbins = 50
            bins = np.linspace(0.0, outflow.max(), nbins+1)
            prob = np.histogram(outflow, bins=bins, density=True) [0]
            plt.plot((bins[1:]+bins[:-1]) / 2, prob, label='{} {}'.format(watershed, model_name))
        plt.legend()

    def time_pdf(self, *models):
        n = len(models) // 2
        for i in range(n):
            watershed, model_name = models[2*i:2*i+2]
            print('{} {}'.format(watershed, model_name))
            desc = {
                'watershed': watershed,
                'model_name': model_name,
            }
            data = util.load_data(**desc)
            meta = util.load_meta(**desc)
            rk = meta['climatic'][-1] / meta['hyd_cond']
            time = data['path_time'] / 31536000.# * rk
            #is_transit = time > 0.0
            #time = time[is_transit]
            nbins = 100
            bins = np.linspace(0.0, time.max(), nbins+1)
            prob = np.histogram(time, bins=bins, density=True) [0]
            bincenter = (bins[1:]+bins[:-1]) / 2 #np.sqrt(bins[1:]*bins[:-1])
            sc = plt.scatter(bincenter, prob, s=5, edgecolor='none', label='{} {}'.format(watershed, model_name))
            print(time.mean())
            #print(dir(sc))

            mean = time.mean()
            interval = (bins[:-1] >= mean) & (bins[1:] < mean*10) & (prob > 0.0)
            #prob_is_valid = prob > 0.0
            slp, off = np.polyfit(bincenter[interval], np.log(prob[interval]), 1)
            print(off, slp)
            print(np.exp(off) / -slp)
            plt.plot([0, mean*15], np.exp([off, slp*mean*15+off]), color=sc.get_facecolor(), linestyle='--', linewidth=0.5)

        plt.legend()
        plt.yscale('log')
        plt.xlabel('Transit time $\\frac{t}{\\phi}$ (years)')
        plt.ylabel('Probability density')

    def length_pdf(self, *models):
        n = len(models) // 2
        for i in range(n):
            watershed, model_name = models[2*i:2*i+2]
            print('{} {}'.format(watershed, model_name))
            desc = {
                'watershed': watershed,
                'model_name': model_name,
            }
            data = util.load_data(**desc)
            meta = util.load_meta(**desc)
            dem_meta = meta['dem_metadata']
            m = dem_meta['area_exp']
            critical = (dem_meta['uplift_rate'] / dem_meta['k_coef']) ** (1/m) * dem_meta['slope_limit'] ** (-dem_meta['slope_exp']/m)
            leng = data['path_length_3d'] / critical ** 0.5
            nbins = 100
            bins = np.linspace(0.0, leng.max(), nbins+1)
            prob = np.histogram(leng, bins=bins, density=True) [0]
            bincenter = (bins[1:]+bins[:-1]) / 2 #np.sqrt(bins[1:]*bins[:-1])
            sc = plt.scatter(bincenter, prob, s=5, edgecolor='none', label='{} {}'.format(watershed, model_name))
            print(leng.mean(), critical)
            #print(dir(sc))

            #mean = leng.mean()
            #interval = (bins[:-1] >= mean) & (bins[1:] < mean*10) & (prob > 0.0)
            ##prob_is_valid = prob > 0.0
            #slp, off = np.polyfit(bincenter[interval], np.log(prob[interval]), 1)
            #print(off, slp)
            #print(np.exp(off) / -slp)
            #plt.plot([0, mean*15], np.exp([off, slp*mean*15+off]), color=sc.get_facecolor(), linestyle='--', linewidth=0.5)

        plt.legend()
        plt.yscale('log')
        #plt.xlabel('Path length $L$')
        plt.xlabel('Normalized path length $\\frac{L}{L_c}$')
        plt.ylabel('Probability density')

    def time_pdf_var(self, *args):
        for model in iterate_models(*args):
            #print(model)
            data = util.load_data(**model)
            time = data['path_time'] / 31536000.
            variable_pdf(time, nbins=300, label='{watershed} {model_name}'.format(**model))
        plt.yscale('log')
        plt.legend()

    def mean_length(self, *args, norm=False):
        if args[0] == '-n':
            norm = True
            args = args[1:]
        for watershed in args:
            X = []
            Y = []
            for model_name in util.loop_models(watershed):
                desc = {'watershed': watershed, 'model_name': model_name}
                data = util.load_data(**desc)
                meta = util.load_meta(**desc)
                len_mean = data['path_length_3d'].mean()
                RK = meta['climatic'][-1] / meta['hyd_cond']

                if norm:
                    dmeta = meta['dem_metadata']
                    critical = (dmeta['uplift_rate']/dmeta['k_coef'])**(1/dmeta['area_exp']) * dmeta['slope_limit']**(-dmeta['slope_exp']/dmeta['area_exp'])
                    len_mean /= critical**0.5
                    
                    #d = data['ztop'].mean()
                    #h = data['head'][0].mean()
                    #RK /= d*(h+100)
                    #RK /= d
                    
                X.append(RK)
                Y.append(len_mean)
            plt.plot(X, Y, label=watershed)
        if norm:
            plt.xlabel('Normalized recharge $\\frac{R}{K}$') #/d
            plt.ylabel('Mean normalized path length $\\frac{\\bar{L}}{L_c}$')
            #plt.ylabel('Mean path length $\\bar{L}$')
        else:
            plt.xlabel('Normalized recharge $\\frac{R}{K}$')
            plt.ylabel('Mean path length $\\bar{L}$')
        plt.xscale('log')
        plt.yscale('log')
        plt.legend()

    def mean_length_haitjema(self, *args):
        Xfit = []
        Yfit = []
        for watershed in args:
            X = []
            Y = []
            for model_name in util.loop_models(watershed):
                desc = {'watershed': watershed, 'model_name': model_name}
                data = util.load_data(**desc)
                meta = util.load_meta(**desc)
                len_mean = data['path_length_3d'].mean()
                hait = haitjema_coef(data, meta)
                critical = critical_drainage(meta) ** 0.5
                if hait >= 1.0 and len_mean >= critical:
                    Xfit.append(hait)
                    Yfit.append(len_mean)
                X.append(hait)
                Y.append(len_mean)
            #print(critical)
            (p,) = plt.plot(X, Y, label=watershed, marker='|')
            print(watershed)
            print(X)
            print(Y)
            # Calculate intercept point(s) of 'critical' to place ticks
            Xt = []
            Yt = []
            for i in range(len(X)-1):
                if (Y[i] > critical) ^ (Y[i+1] > critical):
                    x0, x1, y0, y1 = np.log((X[i], X[i+1], Y[i], Y[i+1]))
                    #print(x0, x1, y0, y1, np.log(critical))
                    x = (np.log(critical)-y0) / (y1-y0) * (x1-x0) + x0
                    Xt.append(np.exp(x))
                    Yt.append(critical)
            #print(Xt, Yt)
            plt.scatter(Xt, Yt, c=p.get_c(), zorder=100)
            #plt.axhline(critical**0.5, c=p.get_c(), linestyle='--', linewidth=0.5)
        a, b = np.polyfit(np.log(Xfit), np.log(Yfit), 1)
        b = np.exp(b)
        xmax = np.max(Xfit)
        xmid = xmax**0.25
        plt.plot([1, xmax], [b, b*xmax**a], linestyle='--', c='black', zorder=120)
        plt.annotate('$\\bar{{L_p}} = {:.2f} \\left(\\frac{{RL^2}}{{16KHd}}\\right)^{{{:6.4f}}}$'.format(b, a), xy=(xmid, b*xmid**a), xytext=(20,20), textcoords='offset pixels', zorder=121)
        plt.xlabel('Haitjema parameter $\\frac{RL^2}{16KHd}$')
        plt.ylabel('Mean path length $\\bar{L_p}$')

        plt.xscale('log')
        plt.yscale('log')
        plt.legend()

    #def haitjema(*args):
        #for watershed in args:
            #for model_name in util.loop_models(watershed):
                #desc = {'watershed': watershed, 'model_name': model_name}
                #data = util.load_data(**desc)
                #meta = util.load_meta(**desc)

                #top = data['ztop']
                #d = top.mean()
                #H = data['head'][0].mean() - data['zbot'][-1].mean()
                #R = meta['climatic'][-1]
                #K = meta['hyd_cond']
                #gt = meta['projection']['geodata']

                #L2 = abs(gt[1]*gt[5] - gt[2]*gt[4]) * top.size
                #m = 16

                #hait = R*L2 / (m*K*H*d)

    def slope_ratio(self, watershed, model_name, drainage):
        from osgeo import gdal
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        meta = util.load_meta(**desc)
        dmeta = meta['dem_metadata']
        area = gdal.Open(os.path.join(util.fspath, os.path.expanduser(drainage))).ReadAsArray()

        topo_slope = (dmeta['uplift_rate'] / dmeta['k_coef']) ** (1/dmeta['slope_exp']) * area ** (-dmeta['area_exp']/dmeta['slope_exp'])
        hydro_slope = meta['climatic'][-1] * area**0.5 / (meta['hyd_cond'] * (data['ztop']-data['zbot'][-1]))

        plt.imshow(topo_slope / hydro_slope, norm=mcl.LogNorm(vmin=0.1, vmax=10.), cmap='coolwarm')
        #plt.colorbar()

    def head_slope_drainage(self, watershed, model_name, drainage):
        from osgeo import gdal
        from slope import slope_down_d8
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        meta = util.load_meta(**desc)
        area_obj = gdal.Open(os.path.join(util.fspath, os.path.expanduser(drainage)))
        area = area_obj.ReadAsArray()
        isvalid = (area != area_obj.GetRasterBand(1).GetNoDataValue()) & (area > 0.)
        area = area[isvalid]

        head = data['head'][0]
        gt = meta['projection']['geodata']
        spacing = abs(gt[1]*gt[5] - gt[2]*gt[4])**0.5
        slope = slope_down_d8(head, spacing=spacing)
        #plt.subplot(1,2,1)
        #plt.imshow(slope)
        #plt.colorbar()
        #plt.subplot(1,2,2)
        slope = slope[isvalid]
        #topo_slope = (dmeta['uplift_rate'] / dmeta['k_coef']) ** (1/dmeta['slope_exp']) * area ** (-dmeta['area_exp']/dmeta['slope_exp'])
        #hydro_slope = meta['climatic'][-1] * area**0.5 / (meta['hyd_cond'] * (data['ztop']-data['zbot'][-1]))
        nbins = 50
        amin, amax = area.min(), area.max()
        bins = np.geomspace(amin, amax, nbins+1)
        bins[-1] += 1.

        binref = np.digitize(area, bins) - 1
        binmedian = np.zeros(nbins)
        for i in range(nbins):
            slopes = slope[binref == i]
            binmedian[i] = np.median(slopes)
            
        #bincount = np.zeros(nbins)
        #binsum = np.zeros(nbins)
        #for i, n in enumerate(binref):
            #bincount[n] += 1
            #binsum[n] += slope[i]
        bincenter = np.sqrt(bins[:-1]*bins[1:])
        #plt.plot(bincenter, binsum / bincount)
        plt.plot(bincenter, binmedian, label='Water table slope')
        #plt.scatter(area, slope, s=1, alpha=0.2)

        plt.axvline(critical_drainage(meta), linestyle='--', color='black', label='$A_c$')
        plt.axvline(data['path_length'].mean()**2, linestyle='--', color='red', label='$L_p^2$')
        plt.xscale('log')
        plt.yscale('log')
        #lims = (plt.gca().get_xlim(), plt.gca().get_ylim())
        #print(lims)

        dmeta = meta['dem_metadata']
        shm_coef = meta['climatic'][-1] / (meta['hyd_cond']*(head-data['zbot'][-1]).mean())
        plt.plot([amin, amax], [shm_coef * amin**0.5, shm_coef * amax**0.5], label='$S_{topo}$ model')
        stm_exp = -dmeta['area_exp'] / dmeta['slope_exp']
        stm_coef = (dmeta['uplift_rate'] / dmeta['k_coef']) ** (1/dmeta['slope_exp'])
        plt.plot([amin, amax], [stm_coef * amin**stm_exp, stm_coef * amax**stm_exp], label='$S_{hydro}$ model')
        plt.legend()

        #plt.xlim(*lims[0])
        #plt.ylim(*lims[1])

        plt.xlabel('Drainage area')
        plt.ylabel('Water table slope')

    def view_head_slope(self, watershed, model_name):
        from slope import slope_down_d8
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        meta = util.load_meta(**desc)
        head = data['head'][0]
        gt = meta['projection']['geodata']
        spacing = abs(gt[1]*gt[5] - gt[2]*gt[4])**0.5
        slope = slope_down_d8(head, spacing=spacing)

        plt.imshow(slope)
        #plt.colorbar()

    def cross_section(self, watershed, model_name, stype, *args):
        import flopy
        desc = {'watershed': watershed, 'model_name': model_name}
        ml = util.load_model(**desc)
        data = util.load_data(**desc)
        line = {}
        if stype == 'line':
            line_arg = []
            for i in range(0, len(args)//2 * 2, 2):
                line_arg.append((float(args[i]), float(args[i+1])))
            print(line_arg)
        else:
            line_arg = int(args[0])
        line[stype] = line_arg
        sect = flopy.plot.PlotCrossSection(model=ml, line=line)
        sect.plot_grid(linewidth=1., color='black', alpha=1-0.5**0.5)
        head = data['head']
        sect.plot_array(head, head=head)

    def view_water_depth(self, watershed, model_name):
        desc = {'watershed': watershed, 'model_name': model_name}
        data = util.load_data(**desc)
        head = data['head']
        zbot = data['zbot']
        water_table = head[-1]
        for n in range(zbot.shape[0]-2, -1, -1):
            headn = head[n]
            is_water = headn > zbot[n]
            water_table[is_water] = headn[is_water]
        plt.imshow(np.maximum(data['ztop'] - water_table, 0.))

#functions = {
    #'seep_RK': plot_seepage_RK,
    #'seep_ineq_RK': plot_seepage_ineq_RK,
    #'seep_pdf': plot_seepage_pdf,
    #'time_pdf': time_pdf,
    #'length_pdf': length_pdf,
    #'time_pdf_var': time_pdf_var,
    #'view_seepage': view_seepage,
    #'view_length': view_length,
    #'view_time': view_time,
#}

if __name__ == '__main__':
    import sys

    pf = PlotFunctions()
    pf(*sys.argv[1:])

    plt.tight_layout()
    plt.show()
