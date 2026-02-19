# hcdm.py

import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from quadprog import solve_qp



def quantile_def(alpha, mu, sigma2):
    sigma_log = np.sqrt(np.log(1 + sigma2 / (mu**2)))
    mu_log = np.log(mu) - 0.5 * sigma_log**2
    q_alpha2 = norm.ppf(alpha / 2, loc=mu_log, scale=sigma_log)
    q_1_minus_alpha2 = norm.ppf(1 - alpha / 2, loc=mu_log, scale=sigma_log)
    return np.exp(q_alpha2), np.exp(q_1_minus_alpha2)


def compute_plot_IC(Kj, varj, alpha, litho_names):
    logm, logM = [], []
    for i in range(len(Kj)):
        m, M = quantile_def(alpha, Kj[i], varj[i])
        logm.append(np.log10(m))
        logM.append(np.log10(M))

    plt.figure(figsize=(8, 5))
    for i in range(len(litho_names)):
        plt.plot([i+1, i+1], [logm[i], logM[i]], color='k', linewidth=1)
        plt.errorbar(
            i+1, np.log10(Kj[i]),
            yerr=[[np.log10(Kj[i]) - logm[i]], [logM[i] - np.log10(Kj[i])]],
            fmt='none', ecolor='k', linewidth=1
        )
        plt.scatter(
            i+1, np.log10(Kj[i]),
            s=110, marker='s',
            edgecolor='#8E142F', facecolor='#E63F49', linewidth=1
        )

    plt.xticks(range(1, len(litho_names)+1), litho_names)
    plt.ylabel('Log(K_j) [m/s]')
    plt.tight_layout()
    plt.show()


def solving_linear_system_qp(A, B, variable):
    H = 2 * (A.T @ A)
    f = -2 * (A.T @ B)
    n = A.shape[1]
    lb = np.zeros(n) if variable == 1 else np.ones(n) * 1e-30
    G = np.eye(n)
    h = lb
    result = solve_qp(H.astype(float), -f.astype(float), G.astype(float), h.astype(float))
    return result[0]

def check_positivity_Kj(Kj):
    print("\n=== Check positivity of Kj ===")
    if np.all(Kj > 0):
        print("→ All Kj values are positive.")
        return True
    else:
        print("→ WARNING: some values of Kj are non positive!")
        print("Non positive values:", Kj[Kj <= 0])
        return False

def check_positivity_varj(varj):
    print("\n=== Checking positivity of varj ===")
    if np.all(varj > 0):
        print("→ All varj values are positive.")
        return True
    else:
        print("→ WARNING: some varj values are NOT positive!")
        print("Problematic values:", varj[varj <= 0])
        return False


def check_stability_Kj(A, B, Kj_ref, a_values=[1, 2, 3, 4], tol=1e-6):
    """
    Check the numerical stability of Kj_new with respect to the scaling parameter 'a'.
    
    Parameters
    ----------
    A : ndarray
        Matrix used in the QP system.
    B : ndarray
        Right-hand side vector (Keq_new_wb).
    Kj_ref : ndarray
        Reference solution obtained using the chosen value of 'a'.
    a_values : list or range
        Values of 'a' to test for stability.
    tol : float
        Tolerance for the relative difference.
    """

    print("\n=== Checking stability of Kj_new with respect to scaling parameter 'a' ===")

    stable = True
    for a in a_values:
        k2 = solving_linear_system_qp(A, B * 10**a, 1)
        Kj_test = k2 / 10**a

        rel_diff = np.linalg.norm(Kj_test - Kj_ref) / np.linalg.norm(Kj_ref)

        print(f"a = {a}, relative difference = {rel_diff:.3e}")

        if rel_diff > tol:
            stable = False

    if stable:
        print("→ Kj_new is stable with respect to scaling (good).")
    else:
        print("→ WARNING: Kj_new shows instability with respect to scaling.")

    return stable

def check_stability_varj(B, vareq2, varj_ref, b_values=range(3, 13), tol=1e-6):
    """
    Check the numerical stability of varj with respect to the scaling parameter 'b'.
    
    Parameters
    ----------
    B : ndarray
        Matrix used in the QP system for variance estimation.
    vareq2 : ndarray
        Squared residuals (Keq_new_wb - A_nwb @ Kj_new)**2.
    varj_ref : ndarray
        Reference solution obtained using the chosen value of b.
    b_values : list or range
        Values of 'b' to test for stability.
    tol : float
        Tolerance for the relative difference.
    """

    print("\n=== Checking stability of varj with respect to scaling parameter 'b' ===")

    stable = True
    for b in b_values:
        var2 = solving_linear_system_qp(B, vareq2 * 10**b, 2)
        varj_test = var2 / 10**b

        rel_diff = np.linalg.norm(varj_test - varj_ref) / np.linalg.norm(varj_ref)

        print(f"b = {b}, relative difference = {rel_diff:.3e}")

        if rel_diff > tol:
            stable = False

    if stable:
        print("→ varj is stable with respect to scaling (good).")
    else:
        print("→ WARNING: varj shows instability with respect to scaling.")

    return stable

# -----------------------------
# Main function
# -----------------------------

def run_hcdm(K_eff, A_lith, litho_names, a=2, b=8, alpha=0.1):
    # Solve for Kj
    k2 = solving_linear_system_qp(A_lith, K_eff * 10**a, 1)
    Kj = k2 / 10**a
    
    # --- Check stability and positivity of k ---
    check_positivity_Kj(Kj)
    check_stability_Kj(A_lith, K_eff, Kj, a_values = list(range(1, 11)), tol=1e-6)

    # Solve for varj
    vareq2 = (K_eff - A_lith @ Kj)**2
    B = A_lith**2
    var2 = solving_linear_system_qp(B, vareq2 * 10**b, 2)
    varj = var2 / 10**b
    
    # --- Diagnostics for varj ---
    check_positivity_varj(varj)
    check_stability_varj(B, vareq2, varj, b_values=range(3, 13), tol=1e-6)

    # Lognormal parameters
    sigma = np.sqrt(np.log(1 + varj / (Kj**2)))
    mu = np.log(Kj) - sigma**2 / 2
    sj = sigma / np.log(10)
    mj = mu / np.log(10)
    
    # Print results
    print("\n=== Lognormal parameters ===")

    print("sigma (natural log):")
    print(sigma)

    print("\nmu (natural log):")
    print(mu)

    print("\nsj (log10 std):")
    print(sj)

    print("\nmj (log10 mean):")
    print(mj)
    
    # Prepare table data
    data = np.column_stack([mj, sj])
    data = np.round(data, 4)

    columns = ["mj (log10 mean)", "sj (log10 std)"]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.axis("off")

    # Create table
    table = ax.table(
        cellText=data,
        rowLabels=litho_names,
        colLabels=columns,
        loc="center",
        cellLoc="center"
    )

    # --- Styling improvements ---
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.3, 1.3)

    # Bold header + gray background
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_text_props(weight='bold')
            cell.set_facecolor("#d9d9d9")

    # Alternating row colors (safe version)
    for (row, col), cell in table.get_celld().items():
        if row > 0:  # skip header
            if row % 2 == 0:
                cell.set_facecolor("#f2f2f2")
            else:
                cell.set_facecolor("white")

    plt.title("Lognormal Parameters per Lithology Class", pad=20, fontsize=14)
    plt.tight_layout()
    plt.show()

    # Plot IC
    compute_plot_IC(Kj, varj, alpha, litho_names)

    return Kj, varj, mj, sj
