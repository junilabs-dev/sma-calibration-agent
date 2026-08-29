---
name: sma-material-calibration
description: How to inverse-identify the 7 parameters of a superelastic shape-memory-alloy (SMA) constitutive model against a noisy tensile-test trace, using the sma-calibration MCP tools.
---

# SMA material-model calibration

You are calibrating a 7-parameter idealized superelastic (pseudoelastic) model
of a NiTi-type shape-memory alloy against one experimental tensile test: a
single load-then-unload cycle. You do not know the true parameters. You only
know the noisy stress-strain trace and can query the model as many times as
you like.

## The parameters you're solving for

| Param | Meaning | Typical NiTi range |
|---|---|---|
| E_A | austenite (loading) elastic modulus, MPa | 30,000 - 70,000 |
| E_M | martensite (transformed) elastic modulus, MPa | 15,000 - 35,000 |
| eps_L | max transformation strain (dimensionless) | 0.03 - 0.06 |
| sig_AS_s | forward-transform start stress, MPa | 300 - 500 |
| sig_AS_f | forward-transform finish stress, MPa | sig_AS_s + (40-100) |
| sig_SA_s | reverse-transform start stress, MPa | 150 - 320 |
| sig_SA_f | reverse-transform finish stress, MPa | 80 - 220 |

Hard constraint the tool enforces: `sig_AS_f > sig_AS_s > sig_SA_s > sig_SA_f > 0`
(otherwise the hysteresis loop doesn't dissipate energy, which isn't physical).
`E_A` is usually noticeably stiffer than `E_M` for NiTi.

## Workflow

1. Call `get_experimental_data()` once. Note the peak stress and where the
   curve visibly kinks (that's roughly where transformation starts/ends on
   loading, and where the reverse plateau sits on unloading) -- eyeballing
   those kinks gives you a much better starting guess than the range midpoints.
2. Call `evaluate_model(...)` with a first guess built from step 1.
3. Read `rmse_pct_of_peak`. This is a residual-minimization problem, not a
   one-shot guess -- treat it like a manual Gauss-Newton search:
   - Change **one or two** parameters at a time, keep the rest fixed.
   - Re-evaluate. If `rmse_pct_of_peak` went down, keep going in that
     direction (larger step); if it went up, reverse direction and take a
     smaller step. This is coordinate descent, not random guessing.
   - Rough attribution, so you're not searching blind:
     - Whole-curve vertical offset -> `sig_AS_s` (loading) / `sig_SA_s` (unloading) are off.
     - Loading elastic slope wrong before the first kink -> `E_A`.
     - Plateau too short/long (wrong strain span) -> `eps_L`.
     - Steep climb after the plateau doesn't match -> `E_M`.
     - Unloading plateau at the wrong stress level -> `sig_SA_s`/`sig_SA_f`.
   - If a call returns `valid: false`, it names the exact reason (e.g. "eps2
     exceeds the test's strain range") -- fix that specific parameter, don't
     just retry the same region with different random values.
4. Stop iterating once `rmse_pct_of_peak` is comfortably under the
   `pass_threshold_pct` returned by the tool (currently 3%), not just barely
   under it -- leave margin, since `commit_calibration` re-checks this itself.
5. Only then call `commit_calibration(...)`. This is the irreversible step --
   it writes the finalized material card to disk. Expect (and wait for) human
   approval before it executes. Write a real `justification`: state the final
   RMSE, and name anything that still looks slightly off so a human reviewer
   isn't surprised by it.

## What "done" looks like

A parameter set with `rmse_pct_of_peak` well under 3%, every parameter inside
(or close to, with a stated reason if not) the typical ranges above, and a
`commit_calibration` call a human has approved. Don't call `commit_calibration`
speculatively or more than once per genuinely improved fit -- it's meant to be
the single, deliberate final step, not part of the search loop.
