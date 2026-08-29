"""
server.py -- MCP server for the SMA material-model calibration agent.

Exposes three tools to a TrueForge agent:

  1. get_experimental_data()  -- read-only: the noisy "tensile test" trace
  2. evaluate_model(...)      -- read-only: run the constitutive model for a
                                  guessed parameter set, get predicted curve + error
  3. commit_calibration(...)  -- DESTRUCTIVE / irreversible: writes the final
                                  parameter set to calibrated_material_card.json.
                                  Annotated destructiveHint=True so TrueForge's
                                  approval gate should hold it for human sign-off
                                  before it runs. Verify this against TrueForge's
                                  current approvals docs (trueforge.dev) -- if your
                                  harness version needs an explicit allow/deny-list
                                  entry instead of relying on the annotation, add
                                  "commit_calibration" to that list.

Run:
    python server.py
Serves on http://localhost:8000/mcp (streamable HTTP), matching TrueFoundry's
own MCP quickstart pattern so it plugs into TrueForge as a remote MCP server.
"""

from datetime import datetime, timezone
import json
from pathlib import Path

from fastmcp import FastMCP

from sma_model import (
    PARAM_NAMES,
    evaluate_superelastic,
    generate_synthetic_experiment,
    is_physically_valid,
    rmse,
)

mcp = FastMCP("sma-calibration")

# Fixed at server startup so every evaluate_model() call in this run is being
# scored against the exact same "experiment" -- reproducible, comparable.
_STRAIN, _STRESS = generate_synthetic_experiment()
_PEAK = float(_STRESS.max())
_OUTPUT_PATH = Path(__file__).parent / "calibrated_material_card.json"
_PROGRESS_PATH = Path(__file__).parent / "progress_state.json"


def _write_progress(event: dict) -> None:
    """Append one call's result to progress_state.json so a separate
    dashboard (see dashboard_api.py) can poll and render it live. This is
    plain file I/O, not part of the MCP protocol -- the agent never sees it."""
    state = {"experimental": {"strain": _STRAIN.tolist(), "stress_mpa": _STRESS.tolist()}, "history": []}
    if _PROGRESS_PATH.exists():
        try:
            state = json.loads(_PROGRESS_PATH.read_text())
        except json.JSONDecodeError:
            pass
    state.setdefault("history", []).append(event)
    # Written via a temp file and renamed: the dashboard polls this path about
    # once a second, and a plain write_text leaves a window where it reads a
    # half-written file. Path.replace is atomic, so a reader sees either the old
    # state or the new one.
    tmp = _PROGRESS_PATH.with_name(_PROGRESS_PATH.name + ".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(_PROGRESS_PATH)

# Fit-quality bar a calibration must clear before commit_calibration will accept it.
_RMSE_PASS_PCT_OF_PEAK = 3.0  # RMSE must be under 3% of peak stress


def _params_from_args(E_A, E_M, eps_L, sig_AS_s, sig_AS_f, sig_SA_s, sig_SA_f) -> dict:
    return dict(zip(PARAM_NAMES, [E_A, E_M, eps_L, sig_AS_s, sig_AS_f, sig_SA_s, sig_SA_f]))


@mcp.tool
def get_experimental_data() -> dict:
    """Return the synthetic tensile-test trace (strain, stress_mpa) for a
    superelastic NiTi-type SMA specimen: a single load-to-EPS_MAX-then-unload
    cycle, with realistic measurement noise added. This is the ground truth
    you are calibrating a 7-parameter constitutive model against. Call this
    first, once, and keep the values in context -- it does not change."""
    return {
        "strain": [round(float(x), 6) for x in _STRAIN],
        "stress_mpa": [round(float(x), 3) for x in _STRESS],
        "n_points": len(_STRAIN),
        "note": (
            "Single load(0->eps_max)-then-unload(eps_max->0) cycle, index "
            f"{int(_STRAIN.argmax())} is the strain reversal point. Units: "
            "strain is dimensionless, stress is MPa."
        ),
    }


@mcp.tool
def evaluate_model(
    E_A: float,
    E_M: float,
    eps_L: float,
    sig_AS_s: float,
    sig_AS_f: float,
    sig_SA_s: float,
    sig_SA_f: float,
) -> dict:
    """Run the idealized superelastic SMA model for one guessed parameter set
    and score it against the experimental trace from get_experimental_data().
    Params: E_A, E_M in MPa (austenite/martensite modulus); eps_L dimensionless
    (max transformation strain); sig_AS_s/sig_AS_f in MPa (forward transform
    start/finish stress, the loading plateau); sig_SA_s/sig_SA_f in MPa
    (reverse transform start/finish stress, the unloading plateau). Required
    ordering: sig_AS_f > sig_AS_s > sig_SA_s > sig_SA_f > 0.
    Returns rmse_mpa, rmse_pct_of_peak, and a residual summary saying where the
    fit is worst and whether each plateau sits above or below the measurement --
    use the signed means to decide which direction to move a stress parameter.
    Returns valid=False with a specific reason if the guess is not physically
    realizable under this test's strain range -- read that reason and adjust the
    parameter it names, don't just retry blindly."""
    params = _params_from_args(E_A, E_M, eps_L, sig_AS_s, sig_AS_f, sig_SA_s, sig_SA_f)
    try:
        pred = evaluate_superelastic(params, _STRAIN)
    except ValueError as e:
        return {"valid": False, "error": str(e)}

    err = rmse(pred, _STRESS)
    residual = pred - _STRESS
    peak_idx = int(_STRAIN.argmax())
    worst = int(abs(residual).argmax())

    # The full 119-point curve goes to the dashboard, not to the agent. Returning
    # it here put ~120 numbers into context on every iteration, and a search runs
    # dozens of iterations -- enough to exhaust a free-tier token budget before
    # converging. A signed residual summary is what actually steers the search:
    # which branch is worst, and whether each plateau sits high or low.
    result = {
        "valid": True,
        "rmse_mpa": round(err, 3),
        "rmse_pct_of_peak": round(100 * err / _PEAK, 3),
        "pass_threshold_pct": _RMSE_PASS_PCT_OF_PEAK,
        "residual_summary": {
            "worst_abs_error_mpa": round(float(abs(residual[worst])), 2),
            "worst_at_strain": round(float(_STRAIN[worst]), 5),
            "worst_on_branch": "loading" if worst <= peak_idx else "unloading",
            "mean_signed_error_loading_mpa": round(float(residual[:peak_idx + 1].mean()), 2),
            "mean_signed_error_unloading_mpa": round(float(residual[peak_idx + 1:].mean()), 2),
            "note": "signed: positive means the model sits above the measurement there",
        },
    }
    _write_progress({
        "type": "evaluate",
        "params": params,
        "rmse_pct_of_peak": result["rmse_pct_of_peak"],
        "predicted_stress_mpa": [round(float(x), 3) for x in pred],
        "at_utc": datetime.now(timezone.utc).isoformat(),
    })
    return result


@mcp.tool(
    annotations={
        "destructiveHint": True,
        "idempotentHint": False,
        "readOnlyHint": False,
        "openWorldHint": False,
        "title": "Commit calibrated material parameters (irreversible)",
    }
)
def commit_calibration(
    E_A: float,
    E_M: float,
    eps_L: float,
    sig_AS_s: float,
    sig_AS_f: float,
    sig_SA_s: float,
    sig_SA_f: float,
    justification: str,
) -> dict:
    """IRREVERSIBLE: finalize a parameter set as the validated material card
    for this specimen, writing it to calibrated_material_card.json. Only call
    this once evaluate_model shows a converged, physically valid fit -- this
    is the step a human should approve before it runs. `justification` (a
    couple of sentences) must state the final RMSE and why the fit is
    trustworthy; calls without a real justification are rejected."""
    params = _params_from_args(E_A, E_M, eps_L, sig_AS_s, sig_AS_f, sig_SA_s, sig_SA_f)

    if not justification or len(justification.strip()) < 15:
        result = {"committed": False, "reason": "justification is missing or too short -- explain the fit quality and why it's trustworthy"}
        _write_progress({"type": "commit_attempt", **result, "at_utc": datetime.now(timezone.utc).isoformat()})
        return result

    if not is_physically_valid(params):
        try:
            evaluate_superelastic(params, _STRAIN)
        except ValueError as e:
            result = {"committed": False, "reason": f"physically invalid: {e}"}
            _write_progress({"type": "commit_attempt", **result, "at_utc": datetime.now(timezone.utc).isoformat()})
            return result

    pred = evaluate_superelastic(params, _STRAIN)
    err = rmse(pred, _STRESS)
    err_pct = 100 * err / _PEAK
    if err_pct > _RMSE_PASS_PCT_OF_PEAK:
        result = {
            "committed": False,
            "reason": f"fit too loose: RMSE is {err_pct:.2f}% of peak stress, "
                      f"needs to be under {_RMSE_PASS_PCT_OF_PEAK}%. Keep iterating with evaluate_model.",
        }
        _write_progress({"type": "commit_attempt", **result, "at_utc": datetime.now(timezone.utc).isoformat()})
        return result

    warnings = []
    if E_A <= E_M:
        warnings.append("E_A <= E_M is unusual for NiTi (austenite is typically stiffer) -- double-check before trusting this card.")

    card = {
        "params": params,
        "rmse_mpa": round(err, 3),
        "rmse_pct_of_peak": round(err_pct, 3),
        "justification": justification.strip(),
        "warnings": warnings,
        "committed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _OUTPUT_PATH.write_text(json.dumps(card, indent=2))
    _write_progress({"type": "commit_success", **card})
    return {"committed": True, "path": str(_OUTPUT_PATH), **card}


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000, path="/mcp")
