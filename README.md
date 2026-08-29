# SMA Calibration Agent — built on TrueForge

An agent that inverse-identifies the 7 parameters of a superelastic
shape-memory-alloy (SMA / NiTi) constitutive model from a noisy tensile-test
trace — the thing a materials engineer normally does by hand over hours of
trial and error — and asks a human to sign off before it trusts the result.

## AI assistance disclosure

Claude (Anthropic) was used extensively while building this: drafting the
constitutive model and MCP server code, the SKILL.md search strategy, and
the dashboard design direction, in an ongoing back-and-forth during the
hackathon window. The physics parameterization, the inverse-identification
approach (Gauss-Newton/Levenberg-Marquardt-style residual minimization), the
choice of what the safety gate should actually check, and the overall
project direction come from my own background in inverse material
characterization (UMAT development and tensile-test/nanoindentation
parameter fitting during my research work) — Claude wrote code to that
direction and I reviewed and understood it before submitting, not the other
way around. [Juni: expand this paragraph in your own words once you've
actually walked through server.py and sma_model.py end to end — a judge can
ask you to explain any part of this, so this disclosure should only say what
you can personally back up.]

## Qodo Code Review Evidence

<!-- REQUIRED by the hackathon rules (#10) -- fill in once real PRs exist,
     do not submit with this placeholder still in place.
- Link to at least one representative merged PR containing real hackathon code
- 1-2 sentences on what Qodo actually flagged, and what you changed vs. intentionally kept as-is
- A short note on the PR history: does a later review show the flagged issues addressed?
-->
- Merged PR: `[link here]`
- What Qodo surfaced: `[fill in]`
- What I changed / intentionally dismissed and why: `[fill in]`

**The three things this hits, explicitly:**
1. **Reaches a real tool** — a custom MCP server (`server.py`) exposing the
   material model as callable tools, not a thin prompt wrapper.
2. **Runs code somewhere safe** — the model evaluation runs server-side, not
   inside the LLM's head; nothing the agent "generates" touches this machine
   directly.
3. **Stops before anything irreversible** — `commit_calibration` is annotated
   `destructiveHint: true` and is where the finalized parameters get written.
   It should sit behind TrueForge's approval gate; **verify this against
   TrueForge's current approvals docs at setup time** (see Known gaps below —
   this is the one piece I couldn't 100% confirm before the deadline).

## Why a surrogate model, not real Abaqus

`sma_model.py` is a closed-form, pure-Python idealized superelastic model
(the same "flag-shaped" hysteresis parameterization used in Abaqus's
built-in superelasticity material), **not** a live Abaqus/UMAT solve. That's
deliberate: it runs in milliseconds, needs no license, and — this matters for
judging — **runs on a stranger's laptop with nothing but `pip install`**,
which a real Abaqus call can't promise. The "experimental" data is synthetic:
generated from a fixed, undisclosed true parameter set with realistic noise
added (see `TRUE_PARAMS` in `sma_model.py`), not pulled from a specific paper
or from any confidential research data — so it's 100% safe to publish in a
public repo.

The underlying calibration math (iterative residual-minimization against a
constitutive model) is adapted from Gauss-Newton/Levenberg-Marquardt
parameter-fitting work I've done before for tensile-test and nanoindentation
inverse problems — used here as a *library/technique*, not submitted as-is;
everything in this repo (the tools, the harness wiring, the approval gate,
the skill file) was built fresh for this hackathon.

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py
# serving on http://localhost:8000/mcp
```

Sanity-check without any MCP client at all:

```bash
python3 -c "
import server
d = server.get_experimental_data()
print(d['n_points'], 'points, peak stress', max(d['stress_mpa']), 'MPa')
r = server.evaluate_model(E_A=45000, E_M=22000, eps_L=0.04, sig_AS_s=400, sig_AS_f=460, sig_SA_s=230, sig_SA_f=120)
print('rmse_pct_of_peak:', r['rmse_pct_of_peak'])
"
```

## Wiring it into TrueForge

```bash
npx @truefoundry/trueforge
```
Then, in the harness config: connect a model (any provider — bring your own
key if running online), add this server as a remote MCP tool source at
`http://localhost:8000/mcp`, and load `SKILL.md` as a skill for the agent.
Give it one instruction: *"Calibrate the SMA model against the experimental
data and commit the result once you're confident in it."* Then watch it call
`get_experimental_data`, iterate on `evaluate_model`, and pause at
`commit_calibration` for your approval.

## Known gaps (cut for time, not forgotten)

- **Sandbox code execution isn't exercised.** The search loop runs entirely
  through the two MCP tools; the agent never writes/runs its own code in
  TrueForge's sandbox. Cheapest fix if there's time left: after convergence,
  ask the agent to write a short matplotlib script in the sandbox to plot
  predicted vs. experimental stress-strain — it already has both arrays in
  context by then, so it's a small ask.
- **Approval-gate wiring is annotation-based, unverified against a live
  TrueForge run.** `commit_calibration` is marked `destructiveHint: true`
  per the MCP spec — confirm TrueForge's approvals actually key off that
  annotation on your installed version, or whether tools need to be listed
  explicitly somewhere in the harness config.
- No blog post / social posts / custom UI. Bundled TrueForge chat UI is used
  as-is.

## Files

| File | What |
|---|---|
| `sma_model.py` | the physics: constitutive model + synthetic data generator |
| `server.py` | the MCP server: 3 tools wrapping the model |
| `SKILL.md` | search-strategy guidance loaded into the agent |
| `requirements.txt` | fastmcp, numpy |
