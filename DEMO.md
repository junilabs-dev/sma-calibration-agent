# NEUTRINO — demo script and project explanation

Everything needed to record the three-minute submission video, plus the
explanation behind the project for anyone who asks in more depth than the video
allows.

---

## 1 · What this is, in my own words

This is **NEUTRINO**, my inverse solver workstation. It is a **prototype, not a
production tool** — but it is a working one. The agent really runs, the tools are
really called, and the approval gate really blocks a write.

**TrueForge is the host.** It is what lets an LLM drive the solver at all: it
runs the agent loop, discovers and dispatches my MCP tools, holds session state,
and owns the approval gate. My solver plugs into it as an MCP tool source, and
TrueForge orchestrates the search over it. Without the harness this is a Python
module you call by hand; with it, the search is driven by a model that reads the
residual and decides what to change next.

**The solver is mine.** The framing, the parameterisation, the acceptance
criteria and the search strategy come from my own research background rather
than from a library:

- ~1 year working on inverse solvers, in a **research workflow** — scripts and
  notebooks, not a product
- ~6 months formulating this particular solver framework
- ~1–2 months building **MODULON**, the wider suite this belongs to

My earlier inverse-solver work targeted a different material problem. NEUTRINO
uses **SMA (superelastic NiTi) as the test subject**, and is deliberately built
against **known data** — a synthetic trace generated from a parameter set the
agent never sees — because for a prototype the point is to check whether the
search recovers a known answer, not to publish a new material characterisation.
That is what makes the result checkable: you can measure how close it got.

**How the pieces connect.** TrueForge is wired to the solver by `run_agent.py`,
which registers the agent, opens a session and streams turns over the harness's
HTTP API. The same run can be started from either end — the workstation
dashboard or TrueForge's own chat — because both go through the harness. The
only difference is where the approval prompt appears.

**On the interface.** Every MODULON module shares this visual language
deliberately. The suite is aimed at engineers who need to read numbers under
pressure, so the priorities are the same throughout: dense but organised, every
figure traceable to where it came from, and nothing on screen that the system
cannot actually observe.

---

## 2 · Architecture

```
                    ┌──────────────────────────────┐
                    │        LLM  (Gemini)         │
                    └──────────────┬───────────────┘
                                   │  model calls
                    ┌──────────────▼───────────────┐
                    │      TRUEFORGE  :8790        │   ← the host
                    │  agent loop · sessions ·     │
                    │  MCP dispatch · APPROVAL GATE│
                    └───┬──────────────────────┬───┘
        registers/drives │                      │ tool calls
                         │                      │
        ┌────────────────▼──────┐   ┌───────────▼─────────────┐
        │  run_agent.py         │   │  server.py   :8000/mcp  │
        │  configure_trueforge  │   │  ┌───────────────────┐  │
        └────────────┬──────────┘   │  │ get_experimental… │  │
                     │              │  │ evaluate_model    │  │
                     │              │  │ commit_calibration│◄─┼── destructiveHint
                     │              │  └─────────┬─────────┘  │    (gated)
                     │              └────────────┼────────────┘
                     │                           │ writes
                     │              ┌────────────▼────────────┐
                     │              │  progress_state.json    │
                     │              │  sma_model.py (physics) │
                     │              └────────────┬────────────┘
                     │ approval handshake        │ polled
        ┌────────────▼───────────────────────────▼────────────┐
        │        dashboard_api.py  →  NEUTRINO  :8001         │
        │   charts · gauges · residuals · APPROVE / DENY      │
        └─────────────────────────────────────────────────────┘
```

**The gate, precisely:** `commit_calibration` is annotated `destructiveHint` in
the MCP server. The agent's MCP entry sets
`require_approval_for_tools: ["@destructive"]`. TrueForge matches the annotation,
emits `tool.approval_required`, and **stops the tool before its Python body
runs**. Nothing continues until a `user.tool_approval` decision is posted back.
No decision is not an approval — the wait times out into a denial.

---

## 3 · Before recording

```powershell
cd "d:\micro project\Neutrino"
Remove-Item progress_state.json, calibrated_material_card.json -ErrorAction SilentlyContinue
.\start.ps1
```

- [ ] `[ok] [ok] [ok]` for all three services
- [ ] **Leave that PowerShell window open** — closing it kills the services
- [ ] Two browser windows side by side:
      **left** TrueForge `localhost:8790` · **right** NEUTRINO `localhost:8001`
- [ ] One practice run with the camera **off**, to see how long the approval
      takes (~2.5 min last time) and what TrueForge's approval prompt looks like
- [ ] Reset again after practice
- [ ] Record with **Win + Alt + R**

---

## 4 · The script

### 0:00 – 0:25 · The problem

**Show:** the NEUTRINO dashboard

> "A shape memory alloy is described by seven material parameters.
> You cannot measure them directly — you only get a stress–strain curve from a
> tensile test.
> Recovering the parameters from that curve is an inverse problem.
> An engineer normally does this by hand, over several hours, and the answer
> depends on who did it.
> This agent does the search. But a human still signs off before anything is
> written."

### 0:25 – 0:50 · What TrueForge is doing

**Show:** hover the **TRUEFORGE HARNESS** panel, right-hand column

> "The agent runs entirely on TrueForge, and TrueForge is the host here — it is
> what lets a model drive my solver at all.
> This panel is read live from the harness: the registered agent, the session
> count, and three MCP tools.
> I built a custom MCP server that exposes my material solver as callable tools.
> TrueForge does the discovery, the dispatch and the agent loop.
> This dashboard only watches. It does not run anything."

### 0:50 – 1:10 · Two ways in, one harness

**Show:** hover **RUN SOLVER** for two seconds, then move to the TrueForge window

> "There are two ways to drive this, and both go through TrueForge.
> I can start it from TrueForge's own chat, on the left.
> Or from the workstation's RUN SOLVER button on the right, which calls
> TrueForge's HTTP API directly — registers the agent, opens a session, streams
> the turn.
> The approval appears wherever you started it.
> I'll use the chat, so you can see the harness doing the work."

**Do:** select agent `sma-calibrator`, paste and send:

```
Calibrate the SMA model against the experimental data and commit the result once you're confident in it.
```

> "One instruction. No parameters, no starting guess."

### 1:10 – 2:00 · The search

**Show:** TrueForge's tool calls appearing, then point at the dashboard

> "TrueForge is calling my MCP server now.
> It reads the experimental data once, then iterates on the model.
> And the workstation tracks it live — the cyan line is the model, the dots are
> the measurement.
> You can see it converging. The parameter gauges are moving and the error is
> falling.
> Every line in the activity log is a real tool call through the harness."

### 2:00 – 2:35 · The gate ← the shot that matters

**Show:** the approval prompt

> "And now it stops.
> The commit tool is annotated as destructive in my MCP server.
> TrueForge sees that annotation and holds the call *before* the Python code
> runs. Nothing has been written to disk."

**Do:** press **DENY**

> "I'll refuse it. The write is blocked."

*(the agent asks again)*

> "It asks again. The gate holds every attempt, not just the first."

**Do:** press **APPROVE**

> "Now I approve — and only now is the material card written."

### 2:35 – 3:00 · Close

**Show:** click the **SENSITIVITY** tab

> "One honest note. The plateau stresses recover to about one percent.
> Two parameters are further off, and this tab shows why — moving them barely
> changes the residual, so the search has little to work with.
> That is the conditioning of the inverse problem, not a broken fit.
> This is a prototype, built against known data so the answer can be checked.
> It is the first module of MODULON, a suite I'm building for the whole
> computational-mechanics pipeline.
> I also had to fix an upstream bug to get here — TrueForge does not start on
> Windows at all — and that fix is in the repository."

**Do:** hold two seconds, stop recording.

---

## 5 · What each beat proves to a judge

| Requirement | Where it lands |
|---|---|
| Custom MCP server, real tools | 0:25 |
| Harness runs the loop and dispatch | 0:25, 1:10 |
| Driven from TrueForge's own UI | 0:50 |
| Also driven programmatically via the API | 0:50 |
| `destructiveHint` → approval gate | 2:00 |
| The gate actually **refuses** a write | 2:15 |
| Understands the limits of the result | 2:35 |
| Contributed a fix back upstream | 2:50 |

---

## 6 · If something goes wrong

| Symptom | Cause and fix |
|---|---|
| No approval prompt after ~4 min | Check `.logs\agent.log`. Usually a rate limit — it retries, but wait 60s and restart the run |
| Run stops silently | Free tier allows ~15 requests/minute. Wait a minute, run again |
| Dashboard says `NO SIGNAL` | `dashboard_api.py` stopped. `.\start.ps1` restarts everything |
| Chart not updating | Do not refresh — it polls on its own |
| Services died between takes | The PowerShell window that ran `start.ps1` was closed. Start it again and keep it open |
| Agent commits without a justification | The model occasionally omits the argument; validation rejects it and it retries. Harmless, just slower |

---

## 7 · Fallback

If TrueForge's chat approval does not read well on camera, change one line:

> "I'll use the workstation button, which drives the same harness through its
> API."

and press **RUN SOLVER** instead. That path is verified end to end: the gate was
reached in 148 seconds, DENY was delivered to the agent, and no material card
was written. The rest of the script is unchanged.
