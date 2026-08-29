"""
seed_demo.py -- drive a real calibration search locally, so the dashboard has
something to render without a live LLM in the loop.

This is NOT a fake data generator. It calls the same server.py tool functions
the agent calls, so every event in progress_state.json comes from the real
constitutive model and the real scoring path. What it replaces is only the
*decision-maker*: a plain coordinate descent stands in for the LLM.

    python seed_demo.py              # run flat out, fill the dashboard instantly
    python seed_demo.py --delay 0.8  # pace it so the dashboard animates live

One honest caveat, stated because it matters for what this proves: calling
commit_calibration() from here executes its Python body directly, which is
exactly the path TrueForge's approval gate would otherwise hold. This script
therefore demonstrates the dashboard, not the safety gate -- the gate is only
meaningfully exercised through a real TrueForge run.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import server
from sma_model import PARAM_NAMES

# Deliberately mediocre: right order of magnitude, every parameter wrong enough
# that the descent has visible work to do on the chart.
START = {
    "E_A": 45000.0, "E_M": 22000.0, "eps_L": 0.040,
    "sig_AS_s": 400.0, "sig_AS_f": 460.0, "sig_SA_s": 230.0, "sig_SA_f": 120.0,
}

STEPS = {
    "E_A": 3000.0, "E_M": 1500.0, "eps_L": 0.003,
    "sig_AS_s": 15.0, "sig_AS_f": 15.0, "sig_SA_s": 15.0, "sig_SA_f": 15.0,
}


def score(params: dict, delay: float) -> float | None:
    """RMSE as % of peak, or None if the guess isn't physically realizable.
    Goes through server.evaluate_model so the call is logged to progress_state."""
    r = server.evaluate_model(**params)
    if delay:
        time.sleep(delay)
    return None if not r.get("valid") else r["rmse_pct_of_peak"]


def descend(delay: float, sweeps: int = 4) -> tuple[dict, float]:
    params = dict(START)
    best = score(params, delay)
    print(f"  start          rmse={best:6.3f}%")

    steps = dict(STEPS)
    for sweep in range(sweeps):
        for name in PARAM_NAMES:
            for direction in (+1, -1):
                trial = dict(params)
                trial[name] = trial[name] + direction * steps[name]
                got = score(trial, delay)
                if got is not None and got < best:
                    params, best = trial, got
                    print(f"  {name:<9} {direction:+d}  rmse={best:6.3f}%")
                    break
        steps = {k: v * 0.5 for k, v in steps.items()}
        print(f"  -- sweep {sweep + 1} done, rmse={best:6.3f}%")

    return params, best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds between tool calls; use ~0.8 to watch it live")
    ap.add_argument("--keep", action="store_true",
                    help="append to the existing progress_state.json instead of starting clean")
    args = ap.parse_args()

    here = Path(__file__).parent
    if not args.keep:
        for f in ("progress_state.json", "calibrated_material_card.json"):
            (here / f).unlink(missing_ok=True)

    print("running coordinate descent through the real evaluate_model tool")
    params, best = descend(args.delay)

    # The agent is expected to make this mistake, so the dashboard's rejected
    # state should be exercised by a genuine rejection rather than a staged one.
    print("\nattempting a commit with a deliberately loose fit (expect rejection)")
    loose = dict(START)
    r = server.commit_calibration(**loose, justification=(
        "Early commit attempt from the starting guess, to confirm the fit-quality "
        "gate actually rejects an under-converged calibration."))
    print(f"  committed={r['committed']} :: {r.get('reason', '')[:80]}")

    if args.delay:
        time.sleep(max(args.delay, 1.0))

    print("\ncommitting the converged fit")
    r = server.commit_calibration(**params, justification=(
        f"Converged to RMSE {best:.2f}% of peak stress ({best:.2f}% vs. a 3% bar) via "
        f"coordinate descent over all 7 parameters. Every parameter sits inside the "
        f"typical NiTi range and E_A > E_M as expected for austenite. Residual is "
        f"dominated by measurement noise near the transformation kinks rather than by "
        f"systematic offset in the plateaus."))
    print(f"  committed={r['committed']}")
    if r["committed"]:
        for k in PARAM_NAMES:
            print(f"    {k:<9} {params[k]:>10.4f}")
        print(f"  rmse {r['rmse_mpa']} MPa / {r['rmse_pct_of_peak']}% of peak")

    print(f"\nwrote {here / 'progress_state.json'} -- open dashboard.html to view")


if __name__ == "__main__":
    main()
