
import numpy as np

class RoquesRecession:
    def __init__(self, df=-1):
        """ This method creates an object of the RoquesRecession class with a discharge time series (t,q) and store the \
        recession prperties. >For more details see Roques et al. (2017) AWR. """
        self.df_obs = df  # pandas dataframe storing the discharge time series (t,q)
        self.aH = -1
        self.bH = -1
        self.aL = -1
        self.bL = -1
        self.ts = -1
        self.rsH = -1
        self.rsL = -1


    def recession_extraction_roques_methods(self, df_obs, column_names=('Datetime', 'Q'), min_recession_time=5,
                                            t_overland=1):
        """
        This methods extracts the recession time constant, the exponent factors in the relationship dQ/dt = a.Q^b with
        the Roques et al. (2017) method.
        Roques, C et al. (2017), Improved streamflow recession parameter
        estimation with attention to calculation of − dQ/dt, WRR.
        :param df_obs: pandas dataframe containing at least a Datetime column and Q_obs column (discharge series)
        :return: (tau_roques, a_q, b_q) the average time recession constant, the a and b factor in the relationship
        dQ/dt = a.Q^b
        """

        t = df_obs[column_names[0]].apply(lambda x: x.toordinal()).values
        q = df_obs[column_names[1]].values

        t_interp = np.arange(np.ceil(min(t)), np.floor(max(t)) + 1, 1)  # d
        
        from scipy import interpolate
        f = interpolate.interp1d(t, q)
        q_interp = f(t_interp)
        t = np.transpose(t_interp)
        q = np.transpose(q_interp)

        # define prominence
        d = np.abs(np.diff(q))
        prominence = 5 * np.nanmin(d[d > 0])

        idmax, pmax, idmin, pmin = self.IDRecession(q, t, prominence, min_recession_time, t_overland)

        date_event, d_all, date_H, d_H, aH, bH, rsH, date_L, d_L, aL, bL, ts, rsL = self.SRanalysis(q, t, idmin, idmax)

        # import matlab.engine
        # eng = matlab.engine.start_matlab()
        # eng.addpath(eng.genpath('~/Documents/MATLAB/RecessionAnalysisRoques/'))
        # # identify individual recessions
        # visu = 0
        # q = matlab.double(q.tolist())
        # t = matlab.double(t.tolist())
        # q = eng.transpose(q)
        # t = eng.transpose(t)

        # [idmax, pmax, idmin, pmin] = eng.IDRecession(q, t, prominence.tolist(), min_recession_time, t_overland, visu, nargout=4)

        # # perform recession analysis on individual recessions
        # [aH, bH, aL, bL, ts, d_all, d_L, gofH, gofL, gofT] = eng.SRanalysis(q, idmin, idmax, visu, nargout=10)

        # aL = np.asarray(aL)
        # bL = np.asarray(bL)
        # ts = np.asarray(ts)
        # aL = np.nan
        # bL = np.nan
        # ts = np.nan
        self.ts = np.nanmedian(ts)
        self.aL = np.nanmedian(aL)
        self.bL = np.nanmedian(bL)
        self.aH = np.nanmedian(aH)
        self.bH = np.nanmedian(bH)
        self.rsH = np.nanmedian(rsH)
        self.rsL = np.nanmedian(rsL)
        return date_event, d_all, date_H, d_H, aH, bH, rsH, date_L, d_L, aL, bL, ts, rsL

    def IDRecession(self, data, time, prominence, min_recession_time, t_overland):
        time2 = time - min(time) + 1

        # time2 = np.reshape(time2, (1,-1))
        # data = np.reshape(data, (1,-1))
        # nt = np.shape(time2)
        # nt = nt[0]
        # nd = np.shape(data)
        # nd = nd[0]
        #
        # if nt > 1:
        #     time2 = time2.transpose()
        # if nd > 1:
        #     data = data.transpose()

        from scipy import signal
        [locs_max, pks_max] = signal.find_peaks(data, height=0, prominence=prominence)
        pks_max = pks_max['peak_heights']
        [locs_min, pks_min] = signal.find_peaks(-data, height=np.nanmin(-data))
        pks_min = pks_min['peak_heights']
        pks_min = -pks_min

        #  If series start by a minimum then supress it
        if locs_min[0] < locs_max[0]:
            locs_min = locs_min[1:]
            pks_min = pks_min[1:]

        # Attribute one minimum for one peak event
        locs_min2 = np.zeros(np.shape(locs_max))
        pks_min2 = np.zeros(np.shape(locs_max))

        for pp in range(len(locs_max))[:-1]:
            bool_indic = (locs_max[pp] < locs_min) & (locs_min < locs_max[pp + 1])

            if sum(bool_indic):
                locmin_temp = locs_min[bool_indic]
                pksmin_temp = pks_min[bool_indic]
                indic2 = pksmin_temp == min(pksmin_temp)
                lcmin = locmin_temp[indic2]
                pkmin = pksmin_temp[indic2]
                locs_min2[pp] = lcmin[-1]
                pks_min2[pp] = pkmin[-1]
            else:
                locs_min2[pp] = np.nan
                pks_min2[pp] = np.nan

        # If last event is a peak then delete it
        if locs_max[-1] > locs_min2[-1]:
            locs_min2 = locs_min2[:-1]
            locs_max = locs_max[:-1]
            pks_min2 = pks_min2[:-1]
            pks_max = pks_max[:-1]

        # delete nan values in locs_min2
        locs_max = locs_max[~np.isnan(locs_min2)]
        pks_min2 = pks_min2[~np.isnan(locs_min2)]
        pks_max = pks_max[~np.isnan(locs_min2)]
        locs_min2 = locs_min2[~np.isnan(locs_min2)]

        # delete short events
        bool_short_events = locs_min2 - locs_max >= min_recession_time
        locs_max = locs_max[bool_short_events]
        pks_min2 = pks_min2[bool_short_events]
        pks_max = pks_max[bool_short_events]
        locs_min2 = locs_min2[bool_short_events]

        # delete long events
        bool_long_events = locs_min2 - locs_max <= 250
        locs_max = locs_max[bool_long_events]
        pks_min2 = pks_min2[bool_long_events]
        pks_max = pks_max[bool_long_events]
        locs_min2 = locs_min2[bool_long_events]

        # Find new loc max to exclude first fast overland flow
        t_overland = int(t_overland)
        locs_max = locs_max + t_overland  # after peak
        pks_max = data[locs_max]

        # Delete errors
        D = pks_max >= pks_min2
        locs_min2 = locs_min2[D]
        locs_max = locs_max[D]
        pks_min2 = pks_min2[D]
        pks_max = pks_max[D]

        # Delete recession if flow data contain NaNs
        N = np.zeros((len(locs_max),))
        for i in np.arange(0, len(locs_max)):
            Q = data[locs_max[i]:np.int(locs_min2[i])]
            N[i] = np.sum(np.isnan(Q))
        N = N == 0
        locs_min2 = locs_min2[N]
        locs_max = locs_max[N]
        pks_min2 = pks_min2[N]
        pks_max = pks_max[N]

        idmax = locs_max
        pmax = pks_max
        idmin = locs_min2
        pmin = pks_min2
        return idmax, pmax, idmin, pmin

    def SRanalysis(self, q, t, idmin, idmax):
        aH = np.zeros((len(idmax),))
        bH = np.zeros((len(idmax),))
        aL = np.zeros((len(idmax),))
        bL = np.zeros((len(idmax),))
        ts = np.zeros((len(idmax),))
        d_all = np.zeros((len(idmax),))
        date_event = np.zeros((len(idmax),))
        date_H = np.zeros((len(idmax),))
        date_L = np.zeros((len(idmax),))
        d_L = np.zeros((len(idmax),))
        d_H = np.zeros((len(idmax),))
        # gofH = np.zeros((len(idmax),))
        # gofL = np.zeros((len(idmax),))
        # gofT = np.zeros((len(idmax),))
        rsH = np.zeros((len(idmax),))
        rsL = np.zeros((len(idmax),))

        limrsq = 0

        #  Limit of recession time to fit a and b
        lr = 3
        # Define the quantile ranges for early and late times
        H1 = 1
        H2 = 0.5
        L1 = 0.5
        L2 = 0

        for zz in np.arange(0, len(idmax)):
            time_event = np.arange(1, (idmin[zz] - idmax[zz]) + 2)
            date_temp = t[int(idmax[zz]):int(idmin[zz] + 1)]
            
            d_all[zz] = len(time_event)
            Qevent = q[int(idmax[zz]):int(idmin[zz] + 1)]
            date_event[zz] = np.nanmean(date_temp)

            # Fit exponential function on the data
            #     [xDataexp, yDataexp] = prepareCurveData(time_event', Qevent./max(Qevent));
            xDataexp = time_event
            yDataexp = Qevent / max(Qevent)
            # Set up fittype and options.
            from scipy.optimize import curve_fit
            f = lambda x, a, b, c: a * np.exp(-b * x) + c
            try:
                popt, pcov = curve_fit(f, xDataexp, yDataexp, p0=[0.1, 0.1, 0.1], method='trf', ftol=1e-6,
                                       xtol=1e-6, maxfev=1000)  # max_nfev=800,
            except:
                popt = np.array([-1, -1])

            if popt[0] and popt[1] > 0:
                step_max = 0.2 * len(time_event)
                cc = np.ceil(step_max * np.exp(-1 / (popt[1] * time_event))) + 1
                Lderiv = int(len(time_event) - cc[-1])
                dQ_dt = np.zeros((Lderiv,))
                Q_deriv = np.zeros((Lderiv,))
                Rsq = np.zeros((Lderiv,))
                t_deriv = np.zeros((Lderiv,))
                date_deriv = np.zeros((Lderiv,))
                from sklearn.linear_model import LinearRegression

                for ee in np.arange(0, int(len(time_event) - cc[-1])):
                    X = time_event[ee:int(ee + cc[ee] + 1)].reshape((-1, 1))
                    Xbis = date_temp[ee:int(ee + cc[ee] + 1)].reshape((-1, 1))
                    Y = Qevent[ee:int(ee + cc[ee] + 1)].reshape((-1, 1))
                    model = LinearRegression(fit_intercept=True)
                    model.fit(X, Y)
                    dQdt = np.array([model.intercept_, model.coef_]).flatten()
                    Rsq[ee] = np.max([0, model.score(X, Y)])
                    if dQdt[1] > 0:
                        dQdt[1] = np.nan
                    elif Rsq[ee] < limrsq:
                        dQdt[1] = np.nan
                    elif np.log10(dQdt[1]) < -8:
                        dQdt[1] = np.nan

                    dQ_dt[ee] = -1 * dQdt[1]
                    Q_deriv[ee] = np.nanmean(Y)
                    t_deriv[ee] = np.nanmean(X)
                    date_deriv[ee] = np.nanmean(Xbis)
            else:
                dQ_dt = np.array(-999)
                Q_deriv = np.array(-999)
                Rsq = np.array(-999)
                date_deriv = np.array(-999)

            # Fit the power law for a and b linear fit: log(y) = p(1) * log(x) + p(2)
            nonan_bool = (~np.isnan(Q_deriv)) & (~np.isnan(dQ_dt))
            Q_deriv = Q_deriv[nonan_bool]
            dQ_dt = dQ_dt[nonan_bool]
            Rsq = Rsq[nonan_bool]
            date_deriv = date_deriv[nonan_bool]
            # fit early-time flow
            H = (Q_deriv < np.nanquantile(q, H1)) & (Q_deriv > np.nanquantile(q, H2))
            ck_H = np.sum(np.log(Q_deriv[H]))
            ck_H = np.isnan(ck_H)
            
            from sklearn.metrics import r2_score
            
            if (np.sum(H) >= lr and ck_H==False):
                f2 = lambda x, b, a: b * x + a
                try:
                    popt, pcov = curve_fit(f2, np.log(Q_deriv[H]), np.log(dQ_dt[H]), ftol=1e-6, xtol=1e-6,
                                           maxfev=600, sigma=np.diag(1 / (Rsq[H])))
                except:
                    popt = np.array([-1, -1])
                bH[zz] = popt[0]
                aH[zz] = np.exp(popt[1])
                
                y_pred_H = f2(np.log(Q_deriv[H]), *popt)
                rsH[zz] = r2_score(np.log(dQ_dt[H]), y_pred_H)
                
                if bH[zz] < 0:
                    bH[zz] = np.nan
                    aH[zz] = np.nan
                    rsH[zz] = np.nan
            else:
                bH[zz] = np.nan
                aH[zz] = np.nan
                rsH[zz] = np.nan

            # date and duration of recession in early-time
            d_H[zz] = np.sum(H)
            date_H[zz] = np.nanmean(date_deriv[H])
            
            # if np.sum(H) < lr:
            #     d_H[zz] = np.nan
            #     date_H[zz] = np.nan


            #  fit late-time flow
            L = (Q_deriv < np.nanquantile(q, L1)) & (Q_deriv > np.nanquantile(q, L2))
            ck_L = np.sum(np.log(Q_deriv[L]))
            ck_L = np.isnan(ck_L)
            
            if (np.sum(L) >= lr and ck_L==False):
                f2 = lambda x, b, a: b * x + a
                try:
                    pL, pcov = curve_fit(f2, np.log(Q_deriv[L]), np.log(dQ_dt[L]), ftol=1e-6, xtol=1e-6,
                                         maxfev=600, sigma=np.diag(1 / (Rsq[L])))
                except:
                    pL = np.array([-1, -1])
                bL[zz] = pL[0]
                aL[zz] = np.exp(pL[1])
                
                y_pred_L = f2(np.log(Q_deriv[L]), *pL)
                rsL[zz] = r2_score(np.log(dQ_dt[L]), y_pred_L)
                
                if bL[zz] < 0:
                    bL[zz] = np.nan
                    aL[zz] = np.nan
                    rsL[zz] = np.nan
            else:
                bL[zz] = np.nan
                aL[zz] = np.nan
                rsL[zz] = np.nan

            # date and duration of recession in late-time
            d_L[zz] = np.sum(L)
            date_L[zz] = np.nanmean(date_deriv[L])
            
            # if np.sum(L) < lr:
            #     d_L[zz] = np.nan
            #     date_L[zz] = np.nan

            # Fit slope of b=1 for characteristic time scale
            if (np.sum(L) >= lr and ck_L==False):
                f3 = lambda x, a: x + a
                try:
                    popt, pcov = curve_fit(f3, np.log(Q_deriv[L]), np.log(dQ_dt[L]), p0=0.1, ftol=1e-6, xtol=1e-6,
                                           maxfev=600, sigma=np.diag(1 / (Rsq[L])))
                except:
                    popt = np.array(-1)
                ts[zz] = 1 / (np.exp(popt))
                if ts[zz] < 0:  
                    ts[zz] = np.nan
            else:
                ts[zz] = np.nan

        return date_event, d_all, date_H, d_H, aH, bH, rsH, date_L, d_L, aL, bL, ts, rsL

    # @staticmethod
    # def test():
    #     import pandas as pd
    #     #  df_obs = pd.read_csv('~/PycharmProjects/fhysa/roquesTestwithnan.csv')
    #     df_obs = pd.read_csv('RoquesRecessionExample.csv')
    #     from datetime import date
    #     datetimes = [date.fromordinal(df_obs.t[i]) for i in df_obs.index]
    #     df_obs['Datetime'] = datetimes
    #     # t = df_obs['Unnamed: 0']
    #     # q = df_obs.q
    #     # datetime = df_obs.Datetime
    #     RR = RoquesRecession(df_obs)
    #     ts, aL, bL, aH, bH, d_all, d_L = RR.recession_extraction_roques_methods(df_obs, column_names=('Datetime', 'q')
    #                                                                             , min_recession_time=5, t_overland=1)
    #     return ts, aL, bL, aH, bH, d_all, d_L