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

Everything installs into this folder — a `.venv/` for Python and a local
`node_modules/` for the harness. Nothing is installed globally and nothing is
written outside this directory.

```powershell
# Python side
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Harness side (local install, not `npm i -g`, not a bare `npx`)
npm install
```

Then one command:

```powershell
.\start.ps1
```

It starts all three servers, waits until each answers, prints `[ok]` or `[FAIL]`
per service, and opens the two URLs you actually look at:

| URL | What |
|---|---|
| http://localhost:8001 | the dashboard |
| http://localhost:8790 | TrueForge chat |

`:8000` is the MCP endpoint — machine-to-machine, nothing to open. Logs land in
`.logs\`, and `.\stop.ps1` shuts everything down (matching on command line, so
unrelated python/node on your machine is left alone).

On macOS/Linux the equivalents are `source .venv/bin/activate` and, in place of
the launcher script:

```bash
XDG_DATA_HOME="$PWD/.trueforge-local" \
SQLITE_PATH="$PWD/.trueforge-local/db/db.sqlite" \
PORT=8790 node node_modules/@truefoundry/trueforge/dist/cli.js
```

### Why a launcher script instead of `npx @truefoundry/trueforge`

`npx` resolves the package through a shared cache, and TrueForge then keeps its
SQLite database and sandbox working directories under the OS-wide app-data path
(`%LOCALAPPDATA%\trueforge` on Windows). `run_trueforge.ps1` pins both into
`.trueforge-local/` inside this folder, so the harness leaves no trace outside
the project and `rm -rf .trueforge-local` is a complete reset.

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

## The dashboard

`dashboard.html` is a single vanilla file (no build step, no npm, no chart
library) that polls `:8001/progress` and renders the run as a materials-testing
instrument: the live stress–strain fit, the 7 parameters as arc gauges, and the
RMSE descent against the 3% pass bar.

Open it directly, or serve it to avoid `file://` fetch restrictions:

```powershell
.\.venv\Scripts\python.exe -m http.server 8002
# http://localhost:8002/dashboard.html
```

To see it populated without burning LLM tokens, `seed_demo.py` drives the *real*
`evaluate_model` / `commit_calibration` functions with a coordinate descent
standing in for the agent — the curves and RMSE it shows are genuine model
output, not fixtures:

```powershell
.\.venv\Scripts\python.exe seed_demo.py --delay 0.8   # paced, so it animates live
```

Note that this bypasses the approval gate by calling the tool bodies directly;
it demonstrates the dashboard, not the safety gate.

**One thing the dashboard deliberately does not claim.** TrueForge holds
`commit_calibration` *before* its Python body runs, so `progress_state.json` has
no signal for "a human is being asked right now". The dashboard shows an
amber state labelled `inferred` when a converged fit goes quiet, and says in the
UI that the real approve/reject happens in TrueForge's own chat. It runs
alongside that window, not instead of it.

## Wiring it into TrueForge

Start the harness with `.\run_trueforge.ps1` (see Quick start). Then, in the
harness config: connect a model (any provider — bring your own
key if running online), add this server as a remote MCP tool source at
`http://localhost:8000/mcp`, and load `SKILL.md` as a skill for the agent.
Give it one instruction: *"Calibrate the SMA model against the experimental
data and commit the result once you're confident in it."* Then watch it call
`get_experimental_data`, iterate on `evaluate_model`, and pause at
`commit_calibration` for your approval.

## Known gaps (cut for time, not forgotten)

- **Sandbox code execution isn't exercised, and on Windows it can't be.**
  The search loop runs entirely through the two MCP tools; the agent never
  writes/runs its own code in TrueForge's sandbox. On this machine that isn't
  just a time cut — TrueForge 0.1.4 logs
  `LocalSandboxProvider supports macOS and Linux only (got win32)` at startup,
  so the local sandbox is unavailable on Windows regardless. Demonstrating this
  criterion needs macOS, Linux, or WSL.

- **TrueForge needs a one-line patch to start on Windows at all.**
  `scripts/patch-kysely-esm.mjs` (wired to `npm postinstall`, idempotent, and a
  no-op off Windows) fixes it. The bug is upstream in kysely, not in TrueForge:
  `FileMigrationProvider` calls `await import(filePath)` with an OS path, and
  Node's ESM loader reads the leading `D:` as a URL scheme, so startup dies with
  `ERR_UNSUPPORTED_ESM_URL_SCHEME ... Received protocol 'd:'` before the HTTP
  listener opens. Verified against trueforge 0.1.4 *and* 0.2.0-rc.0, on both C:
  and D: — it is Windows-wide, not specific to this checkout. Remove the script
  once kysely ships the fix.
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
| `dashboard_api.py` | stdlib-only read-only feed of run progress on `:8001` |
| `dashboard.html` | the live instrument dashboard (single file, no build) |
| `seed_demo.py` | drives a real search locally so the dashboard has data |
| `run_trueforge.ps1` | starts TrueForge with all state pinned inside this folder |
| `scripts/patch-kysely-esm.mjs` | Windows ESM-loader fix, applied on `npm install` |
| `requirements.txt` | fastmcp, numpy |
