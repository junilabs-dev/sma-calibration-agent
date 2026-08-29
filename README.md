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

**Merged PR:** [#1 — Live calibration dashboard, local TrueForge harness, and a
Windows startup fix](https://github.com/junilabs-dev/sma-calibration-agent/pull/1)
(10 commits, 14 files, +6021/−43)

**What Qodo flagged — four bugs, two of them High:**

| # | Severity | Finding |
|---|---|---|
| 1 | High | `scripts/patch-kysely-esm.mjs` inserted the `pathToFileURL` import only when the file began with a `///` reference line |
| 2 | High | `stop.ps1` matched bare names like `server.py` across every python/node/pwsh process on the machine |
| 3 | Medium | `server.py` rewrote `progress_state.json` in place while the dashboard polled it |
| 4 | Medium | `start.ps1` read `TRUEFORGE_PORT` in the child launcher but checked and printed a hardcoded 8790 |

**What I changed — all four fixed, none dismissed** (commit `c541146`):

1. kysely does currently start with that reference line, so the patch worked —
   but `String.replace` with no match returns its input unchanged, so if that
   line ever went away the patch would have added a call to an undefined
   function and failed at migration time with no warning. The import now lands
   unconditionally, after any leading reference lines.
2. This was the worst of the four, because the script's own comment claimed
   unrelated processes were left alone while the code did the opposite. It
   would have killed another checkout's `server.py`. It now matches the
   checkout path, which every process started here carries on its command line.
3. A poll landing mid-write read a half-written file and reported `NO SIGNAL`
   on a healthy run — the kind of fault that only shows up while being
   demonstrated. The write goes through a temp file and an atomic rename, and
   the dashboard holds its last good state until three consecutive failures.
4. A custom port started fine and then failed its own health check for 75
   seconds. The resolved port now flows through the check, the URL and the
   browser launch.

**Verification, rather than assertion:** the patch was re-tested against a
kysely file with the reference line deliberately removed; 150 writes against
three concurrent pollers produced zero corrupt reads; and `TRUEFORGE_PORT=8795`
now reports `[ok]`.

**PR history:** Qodo's first pass raised the four findings above. After
`c541146` its follow-up review reports **Bugs (0)** with all four marked
Resolved, and the PR moved to *Ready to merge*.

**The three things this hits, explicitly:**
1. **Reaches a real tool** — a custom MCP server (`server.py`) exposing the
   material model as callable tools, not a thin prompt wrapper.
2. **Runs code somewhere safe** — the model evaluation runs server-side, not
   inside the LLM's head; nothing the agent "generates" touches this machine
   directly.
3. **Stops before anything irreversible** — `commit_calibration` is annotated
   `destructiveHint: true` and is where the finalized parameters get written.
   It sits behind TrueForge's approval gate: `require_approval_for_tools`
   defaults to `["@write", "@destructive"]`, so the annotation is what the gate
   keys off. The harness emits `tool.approval_required` and blocks until a
   `user.tool_approval` decision is posted back — `run_agent.py` handles that
   from the terminal, and `--deny` shows the gate refusing.

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
- **Approval-gate wiring: resolved.** This was the open question. TrueForge's
  own schema settles it — an agent's MCP server entry carries
  `require_approval_for_tools`, defaulting to `["@write", "@destructive"]`, and
  `commit_calibration` is annotated `destructiveHint: true`, so it matches
  `@destructive` without any extra configuration. `run_agent.py` sets the
  selector explicitly regardless, since a default that changes quietly is a
  poor thing for a safety gate to rest on. When the gate fires the harness
  emits `tool.approval_required` and stops until a `user.tool_approval` item is
  posted back; `run_agent.py --deny` demonstrates it refusing.
  Still outstanding: this is confirmed from the schema and the wiring, but has
  not yet been exercised end-to-end against a live model.
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
