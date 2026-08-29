# Master prompt — SMA calibration dashboard UI

Paste everything below this line into a fresh Claude (Claude Code recommended,
since you're building files in this repo) session, in the repo root.

---

You're building a standalone visual dashboard for an SMA (shape-memory-alloy)
material-calibration agent. This is for a hackathon submission — the agent
itself (a TrueForge-driven LLM loop) already exists and works; your job is
only the human-facing window onto it. The judged criteria this dashboard
needs to earn are "Best UI" and "Presentation" — it needs to make a
30-second glance convey "this is a real precision-instrument tool watching a
real optimization happen," not "this is a generic AI dashboard template."

## What already exists (don't modify the interfaces, only consume them)

- `server.py` — an MCP server exposing 3 tools to the agent (`get_experimental_data`,
  `evaluate_model`, `commit_calibration`). This is the agent's interface. Leave it alone.
- `dashboard_api.py` — a tiny already-working, already-tested plain HTTP
  endpoint (stdlib only, CORS enabled) at `http://localhost:8001/progress`.
  This is YOUR data source. It returns:

```json
{
  "experimental": { "strain": [0.0, 0.0011, ...], "stress_mpa": [0.6, 4.2, ...] },
  "history": [
    { "type": "evaluate", "params": {"E_A":..,"E_M":..,"eps_L":..,"sig_AS_s":..,"sig_AS_f":..,"sig_SA_s":..,"sig_SA_f":..},
      "rmse_pct_of_peak": 5.37, "predicted_stress_mpa": [...], "at_utc": "..." },
    { "type": "commit_attempt", "committed": false, "reason": "...", "at_utc": "..." },
    { "type": "commit_success", "params": {...}, "rmse_mpa": 10.7, "rmse_pct_of_peak": 1.37,
      "justification": "...", "warnings": [], "committed_at_utc": "..." }
  ]
}
```

Poll it every 1–2s. `history` is append-only for the whole run.

## The one honest limitation — don't paper over this

TrueForge's approval pause happens on the harness side, *before* `commit_calibration`'s
Python body ever runs — so this endpoint has no reliable signal for "a human
approval is currently pending." Don't fake a fake-confident "awaiting approval"
state. You may add a *labeled-as-inferred* soft hint (e.g. if the latest
`evaluate` was under the pass threshold and ~8s have passed with no new
event), but the real approve/reject interaction happens in TrueForge's own
chat UI — this dashboard runs alongside it for the demo, not instead of it.
Say so, once, quietly in the UI copy (e.g. a small caption near the
committed/pending area) rather than pretending this window has full visibility.

## Design direction

Ground this in the subject: a materials-testing instrument, not a SaaS
dashboard. Think the control panel on a universal testing machine, an
oscilloscope readout, a calibration certificate — precise, dense-but-calm,
built for someone reading numbers under pressure, not marketing swipe. Avoid
generic AI-dashboard defaults: no near-black-plus-single-neon-accent glow
card, no rounded-everything SaaS look, no generic dashboard iconography.

**Palette** (use these, don't substitute):
- `#0A0C0E` background (graphite, cool undertone — not pure black)
- `#15181C` panel/surface (one step up)
- `#E8E5DE` primary text (warm vellum white, not pure #FFF)
- `#6FA8A3` teal — live/converging data, the experimental + predicted curves
- `#D9A15B` amber — attention / inferred-pending state only
- `#B5563C` rust — invalid/rejected commit attempts

**Type**: IBM Plex Sans for headers and labels, IBM Plex Mono for every
number (params, RMSE, timestamps) — same type family, so display and data
feel related instead of randomly paired. Numbers should look like they came
off an instrument, not a website.

**Layout**: single viewport, no scrolling, no marketing chrome. Roughly:

```
┌───────────────────────────────────────────┬──────────────┐
│  stress-strain chart                       │  wheel        │
│  (experimental scatter, teal predicted     │  (ambient,    │
│  line updating on every `evaluate` event)  │  bleeds off   │
│                                             │  the edge)    │
├───────────────────────────────────────────┴──────────────┤
│  7 parameter dial readouts   |   RMSE trend + state banner │
└─────────────────────────────────────────────────────────────┘
```

## The signature element: the wheel

This is the one bold move — keep everything else disciplined around it.
A thin ring (stroke only, no fill — it should read as a ghost/instrument
bezel, not a solid graphic), large enough to bleed off one edge of the
viewport, with fine tick marks around its circumference like a calibration
dial or aperture ring (a long tick every 30°, short ticks between). Low
opacity (15–25%) so it sits as atmosphere behind the real content, not
competing with it.

Rotation: this is a plain CSS `transform: rotate()` animation —
mathematically that *is* rotation about the Z axis (the axis pointing out of
the screen at the viewer), so a flat 2D rotate is exactly right; you do not
need `perspective` or `transform-style: preserve-3d` for this.

Make the rotation mean something instead of just decorating: spin faster /
more restlessly while `rmse_pct_of_peak` is high, and let it slow to a
near-stop as the fit converges — like a spinning top settling into balance.
If wiring the speed to live RMSE is fiddly under time pressure, a constant
slow drift (60–120s per full rotation) is a fine fallback — just don't make
it fast or attention-grabbing either way.

## Parameter readouts

Each of the 7 parameters as a small arc gauge (partial ring, ~270° sweep,
same visual family as the big wheel but functional-sized), needle/fill
showing current value against its typical range (E_A: 30–70k MPa, E_M:
15–35k MPa, eps_L: 0.03–0.06, sig_AS_s: 300–500 MPa, sig_AS_f: sig_AS_s+40–100,
sig_SA_s: 150–320 MPa, sig_SA_f: 80–220 MPa — from `SKILL.md`), label above,
monospace value below. This ties the decorative wheel and the functional
data display into one coherent visual language instead of two unrelated ideas.

## Code style — read this twice

Write this like a sharp engineer finishing the feature at 1am, not like an
AI generating a tutorial. Concretely:

- Don't put a comment above every function restating its name in prose
  (`// renders the chart` above `function renderChart()`) — the name already says that.
- Don't comment individual obvious lines (`// increment`, `// loop over history`).
- Do comment the handful of spots where the reasoning genuinely isn't
  obvious — why the "pending" state is inferred and not real, any non-obvious
  SVG math, any browser quirk workaround.
- A comment should read like a terse note to a future maintainer, not an
  explanation for someone who's never seen code before.
- Most functions should have zero comments. That's correct, not unfinished.
- Same standard for CSS and variable names: name things so they don't need
  explaining, rather than naming them vaguely and explaining in a comment.

## Build constraints

Single file: `dashboard.html`, vanilla HTML/CSS/JS, inline SVG for both the
chart and the wheel. No React, no build step, no npm install, no external
chart library — it's one scatter series and one line series on fixed axes,
which is less code as hand-rolled SVG than as a Chart.js integration anyway.
It should run by opening the file directly in a browser (with `server.py`
and `dashboard_api.py` both already running) and just work. No API keys, no
config. If you'd genuinely rather use React for some reason, that's fine,
but default to plain — the clock matters more than the stack right now.

## One more thing — how this gets committed

This repo has a hard rule: every substantive change merges through a GitHub
pull request that Qodo has reviewed first — no direct pushes to `main`, even
for this dashboard. Qodo should already be installed on the repo before you
start (if it isn't yet, stop and say so rather than building ahead of it).
Do your work on a branch, open the PR when `dashboard.html` is ready, and
don't merge it yourself — leave it for review.

## Deliverable

One file, `dashboard.html`, in the repo root, that polls
`localhost:8001/progress` and renders the three states above.
