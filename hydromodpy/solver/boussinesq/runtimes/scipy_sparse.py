"""SciPy sparse-linear-algebra runtime for the Boussinesq backend.

This backend keeps the same damped Newton strategy as the historical dense
runtime, but changes how each Newton system is assembled and solved:

- the smooth residual blocks use a semi-analytic sparse Jacobian;
- the saturation-excess block keeps a graph-colored finite-difference
  correction because it still contains the least smooth operators;
- the resulting sparse linear system is solved with ``scipy.sparse.linalg``.

That makes this runtime a practical intermediate step between the original
dense prototypes and a later fully analytic or PETSc-based backend.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable

_log = logging.getLogger(__name__)

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
)
from hydromodpy.solver.boussinesq.runtimes.head_only_common import (
    build_steady_assembly_callback,
    build_transient_assembly_callback,
)
from hydromodpy.solver.boussinesq.jacobian.fd import (
    build_cell_coupling_rows_by_column,
    build_colored_sparse_fd_jacobian_triplets,
    color_columns_by_row_overlap,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtimes.newton_common import (
    _newton_loop_template,
)
from hydromodpy.solver.boussinesq.runtimes.partition_utils import (
    interiorize_regularized_partition_initial_guess,
    regularized_partition_jacobian_shift,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)


def _require_scipy_sparse():
    """Import SciPy sparse modules lazily so backend choice stays explicit."""
    try:
        from scipy import sparse as scipy_sparse
        from scipy.sparse import linalg as scipy_sparse_linalg
        from scipy.sparse.linalg import MatrixRankWarning
    except Exception as exc:  # pragma: no cover - depends on optional import state
        raise RuntimeError(
            "Boussinesq runtime_backend='scipy_sparse' requires scipy to be installed."
        ) from exc
    return scipy_sparse, scipy_sparse_linalg, MatrixRankWarning


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one transient implicit step with sparse Newton iterations."""
    solve_setup = build_transient_assembly_callback(inputs)
    jacobian_rows_by_col = build_cell_coupling_rows_by_column(
        n_cells=inputs.mesh.n_cells,
        edge_cell_a=inputs.mesh.edge_cell_a,
        edge_cell_b=inputs.mesh.edge_cell_b,
    )
    jacobian_column_groups = color_columns_by_row_overlap(jacobian_rows_by_col)

    def _saturation_correction_for(candidate_head: np.ndarray) -> np.ndarray:
        return inputs.mesh.cell_area_m2 * np.asarray(
            solve_setup.assembly_for(candidate_head).saturation_excess_rate_m_s,
            dtype=float,
        )

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        saturation_correction_for=_saturation_correction_for,
        jacobian_rows_by_col=jacobian_rows_by_col,
        jacobian_column_groups=jacobian_column_groups,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=float(inputs.dt_seconds),
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        fd_rel_step=float(solve_setup.options.fd_rel_step),
        min_damping=float(solve_setup.options.min_damping),
        backend_name="scipy_sparse",
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance with sparse Newton iterations."""
    solve_setup = build_steady_assembly_callback(
        inputs,
        head_transform=lambda values: interiorize_regularized_partition_initial_guess(
            inputs.mesh,
            np.asarray(values, dtype=float),
        ),
    )
    jacobian_rows_by_col = build_cell_coupling_rows_by_column(
        n_cells=inputs.mesh.n_cells,
        edge_cell_a=inputs.mesh.edge_cell_a,
        edge_cell_b=inputs.mesh.edge_cell_b,
    )
    jacobian_column_groups = color_columns_by_row_overlap(jacobian_rows_by_col)

    def _saturation_correction_for(candidate_head: np.ndarray) -> np.ndarray:
        return inputs.mesh.cell_area_m2 * np.asarray(
            solve_setup.assembly_for(candidate_head).saturation_excess_rate_m_s,
            dtype=float,
        )

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        saturation_correction_for=_saturation_correction_for,
        jacobian_rows_by_col=jacobian_rows_by_col,
        jacobian_column_groups=jacobian_column_groups,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=None,
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        fd_rel_step=float(solve_setup.options.fd_rel_step),
        min_damping=float(solve_setup.options.min_damping),
        backend_name="scipy_sparse",
    )


def _solve_nonlinear_system(
    *,
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly],
    saturation_correction_for: Callable[[np.ndarray], np.ndarray],
    jacobian_rows_by_col: tuple[np.ndarray, ...],
    jacobian_column_groups: tuple[np.ndarray, ...],
    head_initial_guess_m: np.ndarray,
    mesh: BoussinesqMesh,
    dt_seconds: float | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    max_iterations: int,
    tol_residual_inf: float,
    fd_rel_step: float,
    min_damping: float,
    backend_name: str,
) -> RuntimeSolveResult:
    """Run the shared sparse Newton loop for one head-only nonlinear system."""
    scipy_sparse, scipy_sparse_linalg, matrix_rank_warning = _require_scipy_sparse()

    def _build_sparse_newton_jacobian(
        head_m: np.ndarray,
        assembly: BoussinesqAssembly,
        _residual_m3_s: np.ndarray,
        _residual_norm_inf: float,
        _initial_residual_norm_inf: float,
        _iteration: int,
    ):
        return _build_sparse_jacobian(
            scipy_sparse=scipy_sparse,
            assembly_for=assembly_for,
            saturation_correction_for=saturation_correction_for,
            mesh=mesh,
            head_m=head_m,
            assembly=assembly,
            jacobian_rows_by_col=jacobian_rows_by_col,
            jacobian_column_groups=jacobian_column_groups,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
            fd_rel_step=float(fd_rel_step),
        )

    def _solve_sparse_linear_system(
        jacobian,
        residual_m3_s: np.ndarray,
        residual_norm_inf_value: float,
        initial_residual_norm_inf_value: float,
    ) -> np.ndarray:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", matrix_rank_warning)
                delta = scipy_sparse_linalg.spsolve(jacobian, -residual_m3_s)
        except matrix_rank_warning:
            try:
                delta = _solve_shifted_sparse_system(
                    scipy_sparse_linalg=scipy_sparse_linalg,
                    scipy_sparse=scipy_sparse,
                    jacobian=jacobian,
                    rhs=-residual_m3_s,
                    diagonal_shift=regularized_partition_jacobian_shift(
                        jacobian.diagonal(),
                        residual_norm_inf=residual_norm_inf_value,
                        initial_residual_norm_inf=initial_residual_norm_inf_value,
                    ),
                )
            except (RuntimeError, ValueError, TypeError) as exc:
                raise RuntimeError("Sparse Newton Jacobian solve failed.") from exc
        except (RuntimeError, ValueError, TypeError):
            try:
                delta = _solve_shifted_sparse_system(
                    scipy_sparse_linalg=scipy_sparse_linalg,
                    scipy_sparse=scipy_sparse,
                    jacobian=jacobian,
                    rhs=-residual_m3_s,
                    diagonal_shift=regularized_partition_jacobian_shift(
                        jacobian.diagonal(),
                        residual_norm_inf=residual_norm_inf_value,
                        initial_residual_norm_inf=initial_residual_norm_inf_value,
                    ),
                )
            except (RuntimeError, ValueError, TypeError) as exc:
                raise RuntimeError("Sparse Newton Jacobian solve failed.") from exc
        delta = np.asarray(delta, dtype=float).reshape(-1)
        if not np.all(np.isfinite(delta)):
            raise RuntimeError("Sparse Newton Jacobian solve failed.")
        return delta

    def _log_start(
        residual_norm_inf_value: float,
        tol_residual_inf_value: float,
        max_iterations_value: int,
    ) -> None:
        _log.debug(
            "sparse Newton start: residual_norm=%.4e tol=%.4e max_iter=%d",
            residual_norm_inf_value,
            tol_residual_inf_value,
            max_iterations_value,
        )

    def _log_iteration(
        iteration: int,
        residual_norm_inf_value: float,
        damping: float,
    ) -> None:
        _log.debug(
            "  iter %3d: residual_norm=%.4e damping=%.2e",
            iteration,
            residual_norm_inf_value,
            damping,
        )

    return _newton_loop_template(
        assembly_for=assembly_for,
        head_initial_guess_m=head_initial_guess_m,
        max_iterations=max_iterations,
        tol_residual_inf=tol_residual_inf,
        min_damping=min_damping,
        backend_name=backend_name,
        newton_label="sparse",
        build_jacobian=_build_sparse_newton_jacobian,
        solve_linear_system=_solve_sparse_linear_system,
        log_start=_log_start,
        log_iteration=_log_iteration,
    )


def _solve_shifted_sparse_system(
    *,
    scipy_sparse_linalg,
    scipy_sparse,
    jacobian,
    rhs: np.ndarray,
    diagonal_shift: float,
) -> np.ndarray:
    """Solve one sparse Newton system with adaptive diagonal regularization."""
    identity = scipy_sparse.eye(jacobian.shape[0], format="csc")
    shift = max(float(diagonal_shift), 0.0)
    last_error: Exception | None = None
    for _ in range(6):
        try:
            system_matrix = jacobian if shift == 0.0 else jacobian + shift * identity
            return scipy_sparse_linalg.spsolve(system_matrix, rhs)
        except Exception as exc:  # pragma: no cover - depends on sparse backend state
            last_error = exc
            shift = max(1.0e-8, shift * 10.0 if shift > 0.0 else 1.0e-8)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Sparse Newton Jacobian solve failed.")


def _build_sparse_jacobian(
    *,
    scipy_sparse,
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly],
    saturation_correction_for: Callable[[np.ndarray], np.ndarray],
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    assembly: BoussinesqAssembly,
    jacobian_rows_by_col: tuple[np.ndarray, ...],
    jacobian_column_groups: tuple[np.ndarray, ...],
    dt_seconds: float | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    fd_rel_step: float,
):
    """Build the hybrid sparse Jacobian used by one Newton iteration."""
    base_triplets = build_sparse_semianalytic_base_jacobian_triplets(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    saturation_residual = np.asarray(
        mesh.cell_area_m2 * assembly.saturation_excess_rate_m_s,
        dtype=float,
    )
    saturation_triplets = build_colored_sparse_fd_jacobian_triplets(
        saturation_correction_for,
        head_m,
        saturation_residual,
        rows_by_col=jacobian_rows_by_col,
        column_groups=jacobian_column_groups,
        rel_step=float(fd_rel_step),
    )
    data, row_indices, col_indices = _concatenate_triplets(
        base_triplets,
        saturation_triplets,
    )
    jacobian = scipy_sparse.csc_matrix(
        (data, (row_indices, col_indices)),
        shape=(head_m.size, head_m.size),
        dtype=float,
    )
    jacobian.sum_duplicates()
    jacobian.eliminate_zeros()
    return jacobian


def _concatenate_triplets(
    *triplet_sets: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Concatenate sparse triplets while tolerating empty contributors."""
    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []
    for data, row_indices, col_indices in triplet_sets:
        if np.asarray(data).size == 0:
            continue
        data_parts.append(np.asarray(data, dtype=float).reshape(-1))
        row_parts.append(np.asarray(row_indices, dtype=int).reshape(-1))
        col_parts.append(np.asarray(col_indices, dtype=int).reshape(-1))
    if not data_parts:
        return (
            np.asarray([], dtype=float),
            np.asarray([], dtype=int),
            np.asarray([], dtype=int),
        )
    return (
        np.concatenate(data_parts).astype(float, copy=False),
        np.concatenate(row_parts).astype(int, copy=False),
        np.concatenate(col_parts).astype(int, copy=False),
    )


__all__ = ["solve_steady_problem", "solve_transient_step"]
