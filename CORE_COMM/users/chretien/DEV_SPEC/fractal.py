import numpy as np

def fractal_dimension(a):
    n = int(np.ceil(np.log2(min(a.shape))))

    n_limit = np.zeros(n)
    for i in range(n, 0, -1):
        s = 2**i
        print(s)
        nb_limit = 0
        nb_tot = 0
        for x in range(0, a.shape[0], s):
            for y in range(0, a.shape[1], s):
                part = a[x:x+s, y:y+s]
                if part.any() and not part.all():
                    nb_limit += 1
                nb_tot += 1
        n_limit[n-i] = nb_limit / nb_tot
    return n_limit
