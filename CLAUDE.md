# CLAUDE.md — Agentic Traffic Decision-Support System (*Saarthi*)

This file is your instruction set. Read it fully before writing any code. Build the project **phase by phase, in order**, and obey the operating rules below at all times. When anything is ambiguous or blocked, **stop and ask me** rather than guessing.

---

## 1. What we are building

An **agentic decision-support system for traffic authorities** (control-room operators and enforcement officers — *not* commuters). It watches a junction, optimizes its signals in real time, explains *why* the junction congests, and tells the authority what to do about it — in plain language, in Indian languages.

**The thesis (do not lose sight of this):**
- The **reasoning layer** (root-cause attribution + plain-language advice) is the spine and the differentiator. Most effort goes here.
- **Perception** (vehicle/pedestrian detection, plate reading) is an **off-the-shelf tool** the system calls. Keep it shallow. Do not over-engineer it.
- The **proof** is a **quantified before/after wait-time reduction** measured in SUMO simulation. This number is the headline of the whole project. Protect it.

**Architecture — two decision speeds:**
- **Fast control layer** (heuristic / RL): reflexive, second-by-second signal decisions at one junction, optimizing wait time.
- **Slow reasoning layer** (LLM agents via LangGraph + Claude/Anthropic): deliberative root-cause attribution, language, and judgment.

This fast/slow split is deliberate and is the answer to "is this RL or agentic?" — it is both, by design, each doing what it is good at. Reflect this separation in the code structure.

---

## 2. Operating rules (CRITICAL — follow on every phase)

### Git rules — read carefully
- **Work directly on the `main` branch. Never create, switch, or merge branches.**
- **Never execute any git command yourself.** Do not run `git init` (assume the repo exists), `git add`, `git commit`, or `git push`. You may *read* git state (e.g. `git status`, `git log`) only if needed to write a good commit message.
- **At the end of every phase**, STOP and give me the exact git commands to run **myself**, in a single copy-pasteable code block, in this form:
  ```bash
  git add -A
  git commit -m "<clear conventional commit message for this phase>"
  ```
- **Do NOT include `git push` anywhere.** I handle pushing myself.
- Write a clear, conventional commit message (e.g. `feat: max-pressure controller + before/after benchmark`).
- After presenting the commit commands, **pause and wait for me to confirm** I have committed before you begin the next phase. Do not auto-proceed.

### End-of-phase protocol (do this at the close of EVERY phase)
1. Give a short summary of what was built and how to run/verify it.
2. State explicitly whether the phase's **acceptance criteria** are met.
3. List any **⚠️ items that need my manual intervention** that came up (keys, installs, footage, decisions).
4. Provide the **git commit commands** for me to run (per the git rules above — no push).
5. **Stop and wait** for my go-ahead.

### Things that require MY intervention — flag, don't fake
Whenever a step needs something only I can provide or do, **flag it inline with a `⚠️ USER ACTION NEEDED:` prefix and pause if you're blocked.** Never invent API keys, never fabricate datasets, never fake results or demo output. Likely intervention points (collect these as you go for the final README):
- Installing **SUMO** (system-level install + `SUMO_HOME`, not a pip package).
- Providing the **Anthropic API key**.
- Providing **sample traffic video footage** (ideally Indian roads) for perception/ANPR.
- Downloading any model weights that aren't auto-fetched.
- The **pedestrian-responsive phasing decision** (see Phase 1).
- Running git commit/push, and recording the final demo.

### Coding standards
- Python 3.11+. Use type hints and concise docstrings on public functions/classes.
- Keep modules small and single-purpose; match the repo structure in §3.
- All configuration and secrets via a central `config/settings.py` reading from `.env`. **No secrets in code.** Maintain `.env.example`.
- Use the `logging` module in library code (not `print`); `print`/UI output only in scripts and the dashboard.
- Make every component **runnable and verifiable on its own** (a `scripts/` entry point or a `__main__`). I must be able to see each phase work before moving on.
- Write a few lightweight tests for non-trivial logic (controllers, feature computation) in `tests/`.
- Pin major dependencies in `requirements.txt`.

---

## 3. Target repository structure

Create this structure as you go (not all at once — build each part in its phase):

```
saarthi/                        # repo root (already a git repo)
├── CLAUDE.md                   # this file
├── README.md                   # written in the final phase
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py             # central config, reads .env
├── sim/                        # SUMO assets
│   ├── networks/               # .net.xml
│   ├── routes/                 # .rou.xml demand (rush/off-peak/weekday/weekend)
│   └── scenarios/              # scenario configs (.sumocfg) + a scenario loader
├── control/
│   ├── base.py                 # controller interface
│   ├── fixed_time.py           # baseline
│   ├── max_pressure.py         # Tier 1 adaptive controller
│   └── rl/                     # Tier 2 (Phase 6, optional)
├── perception/
│   ├── detector.py             # YOLO vehicle/pedestrian detection
│   └── anpr.py                 # plate detection + OCR
├── agents/
│   ├── supervisor.py           # LangGraph supervisor / graph wiring
│   ├── analyst.py              # root-cause attribution agent
│   └── enforcement.py          # challan-drafting agent
├── core/
│   ├── features.py             # compute summary features for the analyst
│   ├── metrics.py              # wait-time / queue metrics + benchmark runner
│   ├── models.py               # pydantic data models (events, verdicts, challans)
│   ├── llm.py                  # Claude client wrapper (+ multilingual rendering)
│   └── db.py                   # SQLite access
├── dashboard/
│   └── app.py                  # Streamlit authority dashboard
├── data/
│   ├── videos/                 # MY sample footage goes here
│   ├── outputs/                # charts, exported results
│   └── app.db                  # SQLite (gitignored)
├── scripts/
│   ├── run_baseline.py
│   ├── run_benchmark.py        # fixed-time vs max-pressure (vs RL) chart
│   ├── run_perception.py
│   └── run_analysis.py
└── tests/
```

Add a `.gitignore` early (ignore `.env`, `data/app.db`, `data/outputs/*`, model weights, `__pycache__`, SUMO temp files).

---

## 4. Tech stack

| Concern | Use |
|---|---|
| Simulation | Eclipse **SUMO** + `traci` + `sumolib` |
| Adaptive control (Tier 1) | custom **max-pressure** via TraCI |
| RL (Tier 2, optional) | **sumo-rl** + **stable-baselines3** (PPO or DQN) + gymnasium |
| Detection | **ultralytics** (YOLO) |
| ANPR | plate detector + **EasyOCR** (or PaddleOCR) + OpenCV |
| Agents | **LangGraph** + **langchain-anthropic** (Claude) |
| Backend (if needed) | **FastAPI** + uvicorn |
| Dashboard | **Streamlit** (pragmatic default; charts/tables fast) |
| Storage | **SQLite** (via SQLAlchemy or stdlib) |
| Data/plotting | pandas, matplotlib (or plotly) |
| Models/validation | pydantic |

Default the dashboard to **Streamlit** for speed unless I tell you otherwise.

---

## 5. Implementation phases

> Build strictly in order. A complete, defensible, demoable submission must exist by the **end of Phase 2** (adaptive control + analyst verdict + a result chart). Phases 3–5 add the P1 features and polish; Phase 6 is optional upside; Phase 7 is documentation. Honor the end-of-phase protocol (§2) after each one.

### Phase 0 — Foundation & SUMO baseline
**Goal:** project skeleton + a single junction simulating with a fixed-time signal and logged wait-time metrics.

Tasks:
- Scaffold the repo structure (§3), `requirements.txt`, `.env.example`, `.gitignore`, `config/settings.py`.
- `⚠️ USER ACTION NEEDED:` confirm SUMO is installed and `SUMO_HOME` is set; if not, give me exact install steps for my OS and pause.
- Build one **single-junction** SUMO network (4-way intersection) in `sim/networks/`, with a fixed-time traffic light program.
- Create at least a baseline demand/route file and a `.sumocfg` scenario.
- Implement `control/base.py` (controller interface: observe → decide phase → apply) and `control/fixed_time.py`.
- Implement `core/metrics.py` to run a scenario via TraCI and record **average vehicle waiting time** and **average/peak queue length**.
- `scripts/run_baseline.py` runs the fixed-time scenario and prints + saves the baseline metrics.

**Acceptance:** I can run `python scripts/run_baseline.py` and see baseline wait-time/queue numbers for the junction.

→ End-of-phase protocol. Suggested commit: `chore: project scaffold + SUMO single-junction fixed-time baseline`.

---

### Phase 1 — Adaptive signal control (the floor)
**Goal:** a real-time, demand-responsive controller that beats fixed-time, with a quantified before/after.

> **⚠️ DECISION REQUIRED FROM ME BEFORE YOU BUILD THE SCENARIOS:** ask me whether **pedestrian-responsive phasing** is in scope. It changes the SUMO build (pedestrian demand + a pedestrian phase) and must be decided now, not later.
> - If **yes**: model pedestrian demand at crossings in SUMO and include pedestrian count/waiting in the controller's inputs so it serves a pedestrian phase on demand and skips it when empty.
> - If **no** (default if I don't decide): build the vehicle-only adaptive controller now; pedestrians will instead inform the *advisory* layer in Phase 2/4.
> Do not proceed past this point until I answer.

Tasks:
- Implement `control/max_pressure.py`: at each step, read per-lane occupancy/queue via TraCI, compute movement **pressure**, and activate the max-pressure phase. No fixed cycle, no preset countdown — the signal changes because road state changed. Respect a minimum green time for safety/realism.
- Add demand profiles in `sim/routes/`: **rush-hour, off-peak, weekday, weekend** variants (these double as the analyst's temporal data later).
- `scripts/run_benchmark.py`: run the **same** scenario under fixed-time and max-pressure, compute the **% wait-time reduction**, and render a labeled **bar chart** (`data/outputs/benchmark.png`).

**Acceptance:** the benchmark shows max-pressure with measurably lower average wait than fixed-time, and the chart is saved. This is the headline number — make it correct and reproducible.

→ End-of-phase protocol. Suggested commit: `feat: real-time max-pressure adaptive control + before/after benchmark`.

---

### Phase 2 — Multi-agent core (the spine)
**Goal:** the LangGraph supervisor + Analyst producing a root-cause verdict and recommendation. After this phase the project is a complete, defensible submission.

Tasks:
- `⚠️ USER ACTION NEEDED:` confirm the Anthropic API key is in `.env`; pause if missing.
- `core/llm.py`: a thin Claude client wrapper (chat + a `render_in_language()` helper for later).
- `core/features.py`: from simulation runs, compute structured summary features — per-approach average queue, queue growth over time, peak congestion windows by time bucket, and (if pedestrians are modeled) pedestrian wait and correlation between pedestrian phase and vehicle backup. Output a clean JSON-able dict. **Computed features make the attribution credible — do not let the LLM guess from raw logs.**
- `agents/analyst.py`: takes the feature dict, prompts Claude, returns a **structured** root-cause attribution (e.g. `{cause_breakdown: {vehicles, pedestrians, parking}, recommendation, justification}` via a pydantic model in `core/models.py`).
- `agents/supervisor.py`: a LangGraph supervisor that holds shared state and routes to the Analyst (and later Enforcement). Wire it so it's extensible for more agents.
- `scripts/run_analysis.py`: runs a scenario, computes features, invokes the supervisor→analyst, and **prints the verdict** plus references the benchmark chart.

**Acceptance:** I can run the analysis end-to-end and get a coherent, structured "why this junction congests + what to do" verdict grounded in the computed features. A minimal text/CLI output is fine here — the polished dashboard is Phase 5.

→ End-of-phase protocol. Suggested commit: `feat: LangGraph supervisor + root-cause analyst agent (Claude)`.

---

### Phase 3 — Perception pipeline (the tool)
**Goal:** ingest real video and produce detection events. Keep it lean and off-the-shelf.

Tasks:
- `⚠️ USER ACTION NEEDED:` I must place sample footage in `data/videos/`. Ask me for it; if absent, build the module against a placeholder and tell me what clips you need (e.g. a junction with visible plates).
- `perception/detector.py`: YOLO (ultralytics) detection of **vehicles and pedestrians** on a video; output counts and tracks. The `person` class gives pedestrian counts for free.
- `perception/anpr.py`: detect license plates and OCR them (EasyOCR/PaddleOCR + OpenCV). Treat this as a **POC on clear footage**; document accuracy honestly.
- `scripts/run_perception.py`: runs detection + ANPR on a sample clip and prints/saves structured detection events (timestamp, class, count, plate string).

**Acceptance:** running the script on my footage yields vehicle/pedestrian counts and at least some read plates, emitted as structured events.

→ End-of-phase protocol. Suggested commit: `feat: YOLO detection + ANPR perception pipeline`.

---

### Phase 4 — Enforcement agent + multilingual output + temporal analysis (P1)
**Goal:** the remaining P1 value, folded into the spine.

Tasks:
- **Enforcement agent** (`agents/enforcement.py`): given a violation event with a plate, judge whether it's a real violation, assemble evidence, and **draft a challan** stored in SQLite (`core/db.py`) with status **`pending_review`**. **Never auto-issue — human-in-the-loop always.** Implement a simple, clearly-documented violation trigger (e.g. red-light crossing on the sample clip if feasible; otherwise a configurable/simulated trigger — flag for me which footage would make this real).
- **Multilingual output:** use `core/llm.py`'s language helper so the Analyst's advisory renders in **plain Hindi** (and optionally Tamil/others) for the authority, and challans draft in the citizen's language. **Output-side only — do not build multilingual input.**
- **Temporal analysis:** have the Analyst detect and state time-based patterns ("congests 6–8pm on weekdays") across the rush/off-peak/weekday/weekend scenarios from Phase 1.

**Acceptance:** a flagged event produces a human-reviewable challan record; the advisory is available in Hindi; the analyst reports a temporal pattern.

→ End-of-phase protocol. Suggested commit: `feat: enforcement (human-review challans) + multilingual advisory + temporal patterns`.

---

### Phase 5 — Authority dashboard + demo assembly
**Goal:** one judge-facing surface that tells the whole story; assemble the demo flow.

Tasks:
- `dashboard/app.py` (Streamlit): a single authority dashboard showing
  1. the **before/after benchmark chart** (fixed-time vs max-pressure [vs RL if present]),
  2. the **root-cause verdict** + recommendation,
  3. the **multilingual advisory** (toggle English/Hindi),
  4. the **challan queue** (pending review).
- **No `localStorage`/browser storage assumptions**; keep state in the app/session and read from SQLite/outputs.
- Wire it to real outputs from the prior phases — nothing mocked.
- Add a short `scripts/`-level or README "demo flow" that walks: problem → perception input → benchmark headline → root-cause verdict → Hindi advisory → drafted challan → close.

**Acceptance:** launching the dashboard shows the chart, the verdict, the Hindi advisory, and the challan queue, all from real pipeline output.

→ End-of-phase protocol. Suggested commit: `feat: Streamlit authority dashboard + demo flow`.

---

### Phase 6 — Optional upside (build ONLY if I tell you to)
**Goal:** stronger number and/or richer root-cause — never load-bearing. **Ask me before starting; if I say skip, go straight to Phase 7.**

Tasks (each independent):
- **RL Tier-2 controller** (`control/rl/`): wrap the junction with **sumo-rl** and train a **stable-baselines3** policy (PPO/DQN) on a **single junction only**. Shape the reward on total wait (not raw throughput) to avoid starving side streets. If it converges and beats max-pressure, add it as a third bar in the benchmark. If training is unstable or slow, **stop, report, and fall back to max-pressure** — do not let this jeopardize the headline.
  > **Hard guardrail: single junction only. No multi-junction / multi-agent RL.**
- **Parking-encroachment detection:** extend perception to separate **stationary vs moving** vehicles (tracking across frames) to detect lane-narrowing from illegal parking, and feed it to the Analyst as a third root-cause factor. This is the heaviest CV lift and the lowest-scored layer — only if time allows.

**Acceptance:** whichever sub-tasks I approved work and are integrated, with a clean fallback if RL didn't converge.

→ End-of-phase protocol. Suggested commit (adjust to what was built): `feat: RL signal controller (Tier 2)` and/or `feat: parking-encroachment detection`.

---

### Phase 7 — Comprehensive README + intervention guide
**Goal:** a README that lets anyone understand, set up, run, and judge the project — and tells *me* exactly what I must do by hand.

Write `README.md` covering **everything**:
- **Overview & problem** — what it does, who it's for (the authority), the thesis.
- **Architecture** — the fast/slow two-layer design (include an ASCII or mermaid diagram), the agent roster, and the data flow (SUMO ↔ control ↔ agents ↔ perception ↔ dashboard).
- **Features** — adaptive control, root-cause attribution, multilingual advisory, human-review enforcement, temporal analysis, (and RL/parking if built).
- **Tech stack.**
- **Full setup** — prerequisites (incl. **SUMO install + `SUMO_HOME`**), `pip install -r requirements.txt`, `.env` setup, where to put footage.
- **How to run** — each script and the dashboard, with commands; **how to reproduce the before/after benchmark** specifically.
- **Demo flow** — the scripted walkthrough.
- **Project structure.**
- **⚠️ Things that need my manual intervention** — a dedicated, prominent section compiling everything flagged during the build: install SUMO, obtain/set the Anthropic API key, provide sample footage, download any weights, the pedestrian-responsiveness decision, run git commit/push myself, record the demo, plus anything else that came up.
- **Results** — state the achieved wait-time reduction and (honestly) ANPR/RL caveats.
- **Future scope & explicitly out-of-scope** — note the consumer-facing rerouting app, multilingual input, multi-junction RL, and auto-issued challans are intentionally out of scope (shows discipline, not omission).
- **FAR AWAY submission notes** — repo has full source, docs, setup, and a maintained commit history.

**Acceptance:** the README is complete and accurate enough that I could hand the repo to a stranger and they could set it up and run the demo, and I have a clear checklist of my own manual steps.

→ End-of-phase protocol. Suggested commit: `docs: comprehensive README + manual intervention guide`.

---

## 6. Reminders
- Spine first, perception lean, the benchmark number is sacred.
- One junction. One user: the authority.
- Flag `⚠️ USER ACTION NEEDED` and pause when blocked — never fabricate keys, data, or results.
- End of every phase: summary → acceptance → intervention items → **git commit commands for me (no push, don't execute)** → **stop and wait**.
