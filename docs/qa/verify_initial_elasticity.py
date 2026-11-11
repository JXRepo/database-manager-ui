"""
Compare the initial 33 response with texture averaged cubic elasticity

This offline diagnostic assumes equal grain volumes and MTEX's default Bunge
Euler angles in radians. It does not modify the source or run a CPFEM model.
NumPy is needed only to run this diagnostic, not by the application.
"""

import argparse
import json
from pathlib import Path

import numpy as np


COMPONENTS = ("11", "22", "33", "23", "13", "12")
BASIS = np.zeros((6, 3, 3))
for index, component in enumerate(COMPONENTS):
    row, column = (int(value) - 1 for value in component)
    if row == column:
        BASIS[index, row, column] = 1
    else:
        BASIS[index, row, column] = BASIS[index, column, row] = 1 / np.sqrt(2)


def rotation_matrices(angles):
    """
    Map crystal coordinates to specimen coordinates

    The active product Rz(phi1) Rx(Phi) Rz(phi2) follows MTEX's convention.

    Parameters
    ----------
    angles : ndarray of shape (n, 3)
        Bunge Euler angles in radians, ordered phi1, Phi, phi2.

    Returns
    -------
    ndarray of shape (n, 3, 3)
        Crystal to specimen rotation matrices.
    """
    phi1, phi, phi2 = angles.T
    c1, c, c2 = np.cos(phi1), np.cos(phi), np.cos(phi2)
    s1, s, s2 = np.sin(phi1), np.sin(phi), np.sin(phi2)
    return np.array([
        [c1 * c2 - s1 * s2 * c, -c1 * s2 - s1 * c2 * c, s1 * s],
        [s1 * c2 + c1 * s2 * c, -s1 * s2 + c1 * c2 * c, -c1 * s],
        [s2 * s, c2 * s, c],
    ]).transpose(2, 0, 1)


def grain_stiffness(c11, c12, c44, rotations):
    """
    Rotate cubic stiffness and express it in an orthonormal Mandel basis

    Using the same basis for stress and strain avoids engineering shear factors
    when inverting or averaging the tensors.

    Parameters
    ----------
    c11, c12, c44 : float
        Cubic stiffness constants in MPa.
    rotations : ndarray of shape (n, 3, 3)
        Crystal to specimen rotation matrices.

    Returns
    -------
    ndarray of shape (n, 6, 6)
        Stiffness matrices in MPa, ordered 11, 22, 33, 23, 13, 12.
    """
    identity = np.eye(3)
    tensor = c12 * np.einsum("ij,kl->ijkl", identity, identity)
    tensor += c44 * (
        np.einsum("ik,jl->ijkl", identity, identity)
        + np.einsum("il,jk->ijkl", identity, identity)
    )
    for axis in range(3):
        tensor[axis, axis, axis, axis] += c11 - c12 - 2 * c44
    rotated = np.einsum(
        "nia,njb,nkc,nld,abcd->nijkl",
        rotations, rotations, rotations, rotations, tensor,
        optimize=True,
    )
    return np.einsum("aij,nijkl,bkl->nab", BASIS, rotated, BASIS)


def fit_line(x, y):
    """
    Fit a slope with a free intercept and report its coefficient of determination

    Parameters
    ----------
    x, y : ndarray
        Paired one dimensional samples in their original order.

    Returns
    -------
    tuple of float
        Slope, intercept and R squared.
    """
    dx, dy = x - x.mean(), y - y.mean()
    slope = (dx @ dy) / (dx @ dx)
    intercept = y.mean() - slope * x.mean()
    r_squared = 1 - np.sum((y - slope * x - intercept) ** 2) / (dy @ dy)
    return float(slope), float(intercept), float(r_squared)


def verify_tensor_math(rotations, matrices, constants):
    """
    Check rotation convention, shear scaling and a cubic directional identity

    Parameters
    ----------
    rotations : ndarray of shape (n, 3, 3)
        Rotations used for the source orientations.
    matrices : ndarray of shape (n, 6, 6)
        Rotated cubic stiffness matrices.
    constants : tuple of float
        C11, C12 and C44 in MPa.
    """
    reference = np.array([
        [0.8872, -0.4417, 0.1330],
        [0.3797, 0.5355, -0.7544],
        [0.2620, 0.7198, 0.6428],
    ])
    known = rotation_matrices(np.deg2rad([[10, 50, 20]]))[0]
    np.testing.assert_allclose(known, reference, atol=0.00005)
    identity = np.broadcast_to(np.eye(3), rotations.shape)
    np.testing.assert_allclose(rotations @ rotations.transpose(0, 2, 1), identity, atol=1e-14)
    np.testing.assert_allclose(np.linalg.det(rotations), 1, atol=1e-14)
    assert np.linalg.eigvalsh(matrices).min() > 0

    c11, c12, c44 = constants
    isotropic = grain_stiffness(c12 + 2 * c44, c12, c44, rotations)
    np.testing.assert_allclose(isotropic, np.broadcast_to(isotropic[0], isotropic.shape), atol=1e-8)

    # check every rotated axial compliance against the cubic closed form
    s11 = (c11 + c12) / ((c11 - c12) * (c11 + 2 * c12))
    s12 = -c12 / ((c11 - c12) * (c11 + 2 * c12))
    direction = rotations[:, 2, :]
    inverse_e = s11 + (s11 - s12 - 1 / (2 * c44)) * (np.sum(direction ** 4, axis=1) - 1)
    np.testing.assert_allclose(np.linalg.inv(matrices)[:, 2, 2], inverse_e, rtol=1e-12)


def main():
    """
    Print reproducible diagnostics for the supplied copper example

    An optional downloaded public source is compared locally. No network request
    is made, and no source arrays are written or rounded.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--public-copy", type=Path)
    args = parser.parse_args()
    data = json.loads(args.source.read_text())
    phase = data["phase"][0]
    if args.public_copy:
        public = json.loads(args.public_copy.read_text())
        for group in ("stress", "total_strain", "plastic_strain"):
            assert data[group] == public[group], f"Public source differs: {group}"
        for field in ("orientation", "constitutive_model"):
            assert phase[field] == public["material"][0][field], f"Public source differs: {field}"
        print("Public source: all curve arrays, orientations and constitutive parameters match")

    assert data["units"]["Angle"] == "Radian"
    assert data["units"]["Stress"] == data["units"]["Stiffness"] == "MPa"
    assert data["units"]["Strain"] == 1
    orientation = phase["orientation"]
    euler = orientation["euler_angles"]
    angles = np.column_stack([euler[key] for key in ("Phi1", "Phi", "Phi2")])
    assert len(angles) == orientation["grain_count"]
    parameters = phase["constitutive_model"]["elastic_parameters"]
    constants = tuple(parameters[key] for key in ("C11", "C12", "C44"))
    rotations = rotation_matrices(angles)
    matrices = grain_stiffness(*constants, rotations)
    verify_tensor_math(rotations, matrices, constants)
    print("Tensor checks: MTEX reference, proper rotations, positivity, isotropic invariance, cubic identity passed")

    voigt = matrices.mean(axis=0)
    reuss = np.linalg.inv(np.linalg.inv(matrices).mean(axis=0))
    assert np.linalg.eigvalsh(voigt - reuss).min() > -1e-8
    estimates = {"Reuss": reuss, "Voigt": voigt, "Hill": (voigt + reuss) / 2}
    stress = np.column_stack([data["stress"]["stress_" + key][:25] for key in COMPONENTS])
    stress[:, 3:] *= np.sqrt(2)
    x = np.array(data["total_strain"]["strain_33"][:25])
    y = stress[:, 2]
    plastic = np.array(data["plastic_strain"]["plastic_strain_33"][:25])
    observed, intercept, r_squared = fit_line(x, y)
    dy = y - y.mean()
    path = dy @ (stress - stress.mean(axis=0)) / (dy @ dy)
    print(f"Orientations: {len(angles)}; equal volume weights; initial indices: 0–24")
    print(f"Observed slope: {observed / 1000:.9f} GPa; intercept: {intercept:.12f} MPa; R2: {r_squared:.12f}")
    print(f"Maximum absolute plastic/total strain: {100 * np.max(abs(plastic / x)):.12f}%")
    print("Stress path in Mandel order:", path)
    for name, stiffness in estimates.items():
        compliance = np.linalg.inv(stiffness)
        youngs = 1 / compliance[2, 2]
        path_slope = 1 / (compliance @ path)[2]
        print(
            f"{name}: E3={youngs / 1000:.9f} GPa; path slope={path_slope / 1000:.9f} GPa; "
            f"observed/predicted difference={100 * (observed / path_slope - 1):.9f}%; "
            f"path/E3 difference={100 * (path_slope / youngs - 1):.9f}%"
        )
    for count in (5, 10, 15, 20, 25):
        slope, _, _ = fit_line(x[:count], y[:count])
        print(f"First {count} samples: {slope / 1000:.9f} GPa")


if __name__ == "__main__":
    main()
