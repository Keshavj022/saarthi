# Deploying Saarthi to Hugging Face Spaces 🤗

Saarthi runs on Hugging Face Spaces as a **Docker Space** — the app is a custom
FastAPI server that needs the SUMO binaries (shipped inside the `eclipse-sumo`
wheel), so the Gradio/Streamlit SDKs don't fit, but Docker does.

Everything here is **already verified locally** with Docker: the image builds, SUMO
+ `netconvert` + TraCI run inside the container, and the dashboard serves on
port 7860 — exactly as the Space will.

---

## What's in the repo for this

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image: Debian + the SUMO runtime libs + the lean Python deps, runs `uvicorn backend.app:app` on port **7860**. |
| `requirements-hf.txt` | A **lean** dependency set — the web app's runtime (FastAPI + SUMO + the LangGraph/Claude reasoning layer). Perception (YOLO/EasyOCR) and RL (stable-baselines3) are intentionally excluded, so the image is small and the build is fast. |
| `.dockerignore` | Keeps the image small (excludes `.venv`, model weights, generated nets, the RL policy, tests, etc.). |
| `README.md` frontmatter | The YAML block at the very top (`sdk: docker`, `app_port: 7860`) configures the Space. |

---

## Deploy in 4 steps

### 1. Create the Space
Go to **https://huggingface.co/new-space** and choose:
- **SDK:** `Docker` → *Blank*
- **Hardware:** `CPU basic` (free) is enough — the heavy ML libs are excluded.
- Give it a name, e.g. `saarthi`.

### 2. Add your Anthropic API key as a Secret
In the Space → **Settings → Variables and secrets → New secret**:
- **Name:** `ANTHROPIC_API_KEY`
- **Value:** `sk-ant-...`

`config/settings.py` reads it automatically. *(Optional — without it the live
simulation, before/after benchmark, and animated dashboard still work; only the
AI verdict / advisory / challan steps degrade gracefully.)*

### 3. Push this repo to the Space
A Space is just a git repo. From the project root:

```bash
# one-time: add the Space as a remote (use your username + space name)
git remote add space https://huggingface.co/spaces/<your-username>/saarthi

# push (HF will build the Dockerfile and start the app)
git push space main
```

> Authenticate with a Hugging Face **access token** (Settings → Access Tokens on
> huggingface.co) when prompted, or run `huggingface-cli login` first.

### 4. Wait for the build
The first build takes a few minutes (installing the SUMO wheel + the reasoning
deps). When it finishes, the Space opens straight onto the **Live Simulation** —
drag the demand sliders, hit *Run*, switch controllers, open *Analysis*.

---

## Test the exact image locally first (optional but recommended)

```bash
docker build -t saarthi-hf .
docker run --rm -p 7860:7860 -e ANTHROPIC_API_KEY=sk-ant-... saarthi-hf
# → open http://localhost:7860
```

---

## Notes & expectations

- **Lean image.** The Space uses `requirements-hf.txt`, not `requirements.txt`.
  The live dashboard never calls YOLO/EasyOCR or the RL policy at runtime, so they
  aren't installed. (To run perception/RL on the Space too, point the `Dockerfile`
  at `requirements.txt` and drop the `rl_policy.zip` / `*.pt` lines from
  `.dockerignore` — the image will be several GB larger.)
- **"Self-learning AI" (RL) is disabled on the Space.** The trained policy is
  excluded to keep the image small, so the UI auto-hides it. **Fixed timer** and
  **Smart adaptive** (the headline −44.6% result) work everywhere.
- **Storage is ephemeral.** The committed `data/outputs/*` artifacts (benchmarks,
  verdicts, advisories) ship inside the image, so the dashboard tells the whole
  story out of the box. The challan SQLite DB and the generated `net_*.net.xml`
  files are rebuilt on demand at runtime.
- **Concurrency.** One SUMO/TraCI run happens at a time (a process lock); if two
  visitors hit *Run* together, the second sees a friendly "already running" notice.
  `CPU basic` handles the single-junction sims comfortably.
- **No Git LFS needed** — every committed asset is small (the 6.5 MB `yolov8n.pt`
  is git-ignored and excluded from the image anyway).
