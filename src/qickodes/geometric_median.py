import numpy as np
from geom_median.numpy import compute_geometric_median


def geometric_median(data: np.ndarray, ftol: float = 1e-6) -> np.ndarray:
    """Compute the geometric median of the data.

    data.shape[0] is the number of data points and data.shape[-1] is the dimensionality of each data point.
    The computation is iterated over the remaining axes.

    Parameters
    ----------
    data : np.ndarray
        The data.
    ftol : float
        If objective value does not improve by at least this `ftol` fraction, terminate the algorithm.
    """
    result_shape = data.shape[1:]
    num_points = data.shape[0]
    num_components = data.shape[-1]
    data = data.reshape(num_points, -1, num_components)
    result = np.empty(result_shape).reshape(-1, num_components)
    for i in range(data.shape[1]):
        result[i, :] = compute_geometric_median(data[:, i, :], ftol=ftol).median
    return result.reshape(result_shape)
