"""
sma_model.py -- 1D idealized superelastic (pseudoelastic) SMA constitutive model.

Fast, closed-form surrogate for a uniaxial NiTi-type shape-memory-alloy
tension test -- NOT a full 3D Abaqus/UMAT solve. Reproduces the classic
"flag-shaped" loading/unloading hysteresis used in simplified superelastic
models (same spirit as the parameterization behind Abaqus's built-in
superelasticity material model), with 7 parameters:

    E_A       austenite Young's modulus            (MPa)
    E_M       martensite Young's modulus            (MPa)
    eps_L     maximum transformation strain         (-)
    sig_AS_s  forward transformation start stress   (MPa)  [loading plateau start]
    sig_AS_f  forward transformation finish stress  (MPa)  [loading plateau end]
    sig_SA_s  reverse transformation start stress   (MPa)  [unloading plateau start]
    sig_SA_f  reverse transformation finish stress  (MPa)  [unloading plateau end]

Physical ordering required: sig_AS_f > sig_AS_s > sig_SA_s > sig_SA_f > 0.

Deliberately pure-Python + numpy only: runs in milliseconds, no Abaqus
license, no solver queue, fully reproducible on a judge's laptop.

IMPORTANT for the hackathon build: TRUE_PARAMS below exists only to
generate the synthetic "experimental" trace. Don't give the TrueForge
agent file/read access to this module -- it should only ever see the
noisy curve from get_experimental_data() and the results of
evaluate_model(). Otherwise the inverse-identification task is trivial.
"""

from __future__ import annotations
import numpy as np

PARAM_NAMES = ["E_A", "E_M", "eps_L", "sig_AS_s", "sig_AS_f", "sig_SA_s", "sig_SA_f"]

# Fixed test protocol: the synthetic "experiment" and every model evaluation
# load to the same EPS_MAX then unload to zero. Keeping this fixed is what
# makes evaluate_model() outputs comparable point-for-point against the
# experimental curve.
EPS_MAX = 0.065
N_PER_BRANCH = 60


def _validity_reason(p: dict) -> str | None:
    """None if params are physically valid and the test protocol resolves
    to a real closed hysteresis loop; otherwise a short human-readable reason."""
    required = PARAM_NAMES
    missing = [k for k in required if k not in p]
    if missing:
        return f"missing parameter(s): {missing}"

    E_A, E_M, eps_L = p["E_A"], p["E_M"], p["eps_L"]
    s1, s2, s3, s4 = p["sig_AS_s"], p["sig_AS_f"], p["sig_SA_s"], p["sig_SA_f"]

    if E_A <= 0 or E_M <= 0:
        return "E_A and E_M must both be positive"
    if eps_L <= 0 or eps_L > 0.15:
        return "eps_L must be in (0, 0.15] -- real NiTi transformation strains don't exceed ~10-12%"
    if not (s2 > s1 > s3 > s4 > 0):
        return "requires sig_AS_f > sig_AS_s > sig_SA_s > sig_SA_f > 0 (hysteresis must dissipate energy)"

    eps1 = s1 / E_A
    eps2 = eps1 + eps_L
    if EPS_MAX <= eps2:
        return (f"EPS_MAX ({EPS_MAX}) must exceed full-transformation strain "
                f"eps2 ({eps2:.4f}) -- loosen sig_AS_s/E_A/eps_L")

    sigma_max = s2 + E_M * (EPS_MAX - eps2)
    eps3 = EPS_MAX - (sigma_max - s3) / E_M
    eps4 = s4 / E_A
    if not (eps4 < eps3):
        return "unloading geometry degenerates (eps4 >= eps3) -- check sig_SA_s/sig_SA_f/E_M"

    return None


def is_physically_valid(params: dict) -> bool:
    return _validity_reason(params) is None


def _strain_path() -> np.ndarray:
    load = np.linspace(0.0, EPS_MAX, N_PER_BRANCH)
    unload = np.linspace(EPS_MAX, 0.0, N_PER_BRANCH)
    return np.concatenate([load, unload[1:]])  # don't duplicate the peak point


def transition_strains(params: dict) -> dict:
    """The four strains where the flag changes regime, for the given params:

        eps1  end of austenite-elastic loading  (below it, E_A governs)
        eps2  end of the forward plateau        (above it, E_M governs)
        eps3  start of the reverse plateau on unloading
        eps4  end of the reverse plateau        (below it, E_A governs again)

    Exposed so callers can attribute a residual to the regime it falls in
    rather than averaging across regimes that different parameters control.
    """
    E_A, E_M, eps_L = params["E_A"], params["E_M"], params["eps_L"]
    eps1 = params["sig_AS_s"] / E_A
    eps2 = eps1 + eps_L
    sigma_max = params["sig_AS_f"] + E_M * (EPS_MAX - eps2)
    return {
        "eps1": eps1,
        "eps2": eps2,
        "eps3": EPS_MAX - (sigma_max - params["sig_SA_s"]) / E_M,
        "eps4": params["sig_SA_f"] / E_A,
    }


def evaluate_superelastic(params: dict, strain: np.ndarray) -> np.ndarray:
    """Predicted stress at each strain point along a single 0->EPS_MAX->0
    load/unload cycle. Raises ValueError with a human-readable reason if
    params aren't physically valid."""
    reason = _validity_reason(params)
    if reason is not None:
        raise ValueError(reason)

    E_A, E_M, eps_L = params["E_A"], params["E_M"], params["eps_L"]
    sig_AS_s, sig_AS_f = params["sig_AS_s"], params["sig_AS_f"]
    sig_SA_s, sig_SA_f = params["sig_SA_s"], params["sig_SA_f"]

    eps1 = sig_AS_s / E_A
    eps2 = eps1 + eps_L
    sigma_max = sig_AS_f + E_M * (EPS_MAX - eps2)
    eps3 = EPS_MAX - (sigma_max - sig_SA_s) / E_M
    eps4 = sig_SA_f / E_A

    peak_idx = int(np.argmax(strain))
    stress = np.empty_like(strain, dtype=float)

    for i, e in enumerate(strain):
        if i <= peak_idx:  # loading branch
            if e <= eps1:
                stress[i] = E_A * e
            elif e <= eps2:
                stress[i] = sig_AS_s + (sig_AS_f - sig_AS_s) * (e - eps1) / eps_L
            else:
                stress[i] = sig_AS_f + E_M * (e - eps2)
        else:  # unloading branch
            if e >= eps3:
                stress[i] = sigma_max - E_M * (EPS_MAX - e)
            elif e >= eps4:
                stress[i] = sig_SA_s + (sig_SA_f - sig_SA_s) * (e - eps3) / (eps4 - eps3)
            else:
                stress[i] = E_A * e

    return stress


# --- synthetic "experimental" data ------------------------------------------

TRUE_PARAMS = {
    "E_A": 51000.0,     # MPa -- illustrative NiTi-typical value, NOT sourced from a specific paper
    "E_M": 24000.0,     # MPa
    "eps_L": 0.045,
    "sig_AS_s": 420.0,  # MPa
    "sig_AS_f": 480.0,  # MPa
    "sig_SA_s": 250.0,  # MPa
    "sig_SA_f": 140.0,  # MPa
}


def generate_synthetic_experiment(seed: int = 42, noise_pct: float = 0.03, noise_floor_mpa: float = 2.0):
    """Deterministic (given `seed`) noisy load-unload trace standing in for a
    real tensile test on TRUE_PARAMS. The agent must recover parameters close
    to TRUE_PARAMS using only this trace + evaluate_model() -- it never sees
    TRUE_PARAMS directly."""
    strain = _strain_path()
    clean_stress = evaluate_superelastic(TRUE_PARAMS, strain)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, size=clean_stress.shape) * (noise_pct * np.abs(clean_stress) + noise_floor_mpa)
    return strain, clean_stress + noise


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))
