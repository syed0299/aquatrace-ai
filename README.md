# AquaTrace AI: prototype

**From detecting marine debris to predicting its next move.** Bay of Bengal pilot (Phase 1).

AquaTrace AI finds *potential* floating-debris hotspots in NASA and ESA satellite data. It forecasts where
each one will drift over the next 24 and 48 hours using ocean currents and wind, back-tracks where it came
from, ranks everything into a cleanup-priority list, and plans a vessel route to intercept it. It all runs
on an interactive map.

```
OBSERVE ─▶ DETECT ─▶ FUSE ─▶ FORECAST ─▶ PRIORITIZE ─▶ ACT
PACE OCI    AI model   OSCAR     particle      risk score    route planner
Sentinel-2  + FDI      MERRA-2   drift model   + source      + shoreline alerts
```

## Getting started on a new machine

Requirements: **Python 3.11+** (developed on 3.14, macOS). Node.js 18+ is optional, because a built copy of
the web app is included in `frontend/dist`.

```bash
./setup.sh                    # creates .venv, installs Python packages, rebuilds the web app if npm exists
./run_demo.sh                 # serves the API + web app at http://localhost:8000
```

That's enough for the full demo: the saved runs (live + two replays), metrics, what-if forecasts and route
planning all work offline from the files included here. The trained classifier is included too, so the detection
pipeline can run on new satellite data without retraining. On Windows, create the venv manually
(`python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`) and start the server with
`cd backend` then `..\.venv\Scripts\uvicorn aquatrace.api:app --port 8000`.

Already have an older copy of the project? Follow `UPDATING_AN_EXISTING_COPY.txt` (swap four folders, keep `data/` and `.venv/`).

### What is included, and what isn't

**Cloned from GitHub?** The trained classifier is too large for git (GitHub's limit is 100 MB per file). Download
`marida_rf.joblib` from the repository's **Releases** page and put it in `models/`, or retrain it (below). Everything
else in this section is in the repository.

| Included | Not included (and how to get it) |
|---|---|
| All source code (`backend/`, `frontend/src`) and the built web app (`frontend/dist`) | `.venv/` and `node_modules/`: recreated by `./setup.sh` |
| Saved pipeline runs, overlays and validation results (`outputs/`) | Raw satellite downloads (~10 GB): fetched automatically when you re-run the pipeline |
| Trained debris classifier `models/marida_rf.joblib` (~400 MB, LZMA-compressed; loads in ~15 s) | MARIDA training images (1.2 GB): only needed to retrain (below) |
| Model metrics, calibration and experiment results (`models/*.json`) | |
| Cached currents/wind for the saved runs and the buoy validation (`data/processed/*.nc`) | Sentinel-2 scene cache: re-downloaded on demand |
| Coastline data and NOAA drifter tracks (`data/raw/naturalearth`, `data/raw/drifters`) | Your Earthdata login: each person uses their own (below) |
| Pitch deck with results (`presentation/`) and app screenshots (`docs/screenshots/`) | |

### Retraining the debris classifier (optional: the trained model is included)

```bash
mkdir -p data/raw/marida && cd data/raw/marida
curl -L -o MARIDA.zip "https://zenodo.org/records/5151941/files/MARIDA.zip?download=1"   # 1.2 GB
unzip -q MARIDA.zip && cd ../../../backend
../.venv/bin/python -m aquatrace.marida        # ~3 min; writes models/marida_rf.joblib + metrics
../.venv/bin/python -m aquatrace.calibration
```

## Quick start (demo)

```bash
./run_demo.sh                 # builds the web app if needed, serves http://localhost:8000
```

In the app:
- **Top bar:** switch between the `Live` run and replays, see which datasets the run used, open **Model trust**.
- **Left briefing:** headline numbers, first landfall, fastest drift, and the ranked list. Filter by tier and sort;
  hovering a row highlights its pin.
- **Map:** animated ocean currents (and wind) flowing over a bathymetric basemap. Pins pulse by priority; tracks,
  48 h uncertainty cones and drifting particles follow the time bar.
- **Click a hotspot:** the drawer shows the action, risk gauge, drift compass, where it came from, and the evidence.
- **Time bar:** press **Space** to play 48 h (night bands = hours crews can't work), arrows to scrub, 1×/2×/4× speed.
- **Right toolbar:** basemap (Ocean / Satellite / Night), layer toggles, **What-if** (click the sea to drop a debris
  patch), **Cleanup route** (vessel routed to where each patch *will be*), and back to the whole Bay. **Esc** closes panels.
- Links can open an exact view: `?run=20260314_pace&select=HS-07&hour=24&route=Chennai&basemap=dark&show=wind&trust=1`.

## Running the pipeline

```bash
cd backend
../.venv/bin/python -m aquatrace.pipeline --live                  # near-real-time: latest passes → now → +48 h
../.venv/bin/python -m aquatrace.pipeline --date 2026-03-14       # replay a past date (NASA data)
../.venv/bin/python -m aquatrace.marida                           # train the debris classifier
../.venv/bin/python -m aquatrace.calibration                      # confidence calibration check
../.venv/bin/python -m aquatrace.experiments                      # model selection on the validation split
../.venv/bin/python -m aquatrace.experiments_v2                   # round-2 model selection (validation split)
../.venv/bin/python -m aquatrace.tune_drift                       # tune drift on Jan 2025 buoys, check on Feb
../.venv/bin/python -m aquatrace.validate --holdout                # buoy validation on the held-out month
../.venv/bin/python -m aquatrace.pipeline --live --issued 2026-09-30T19:00   # re-issue a past live run
```

For a daily live map, run `--live` about 3 hours after the Bay pass (~16:00 IST), when NASA publishes the
near-real-time PACE product.

### NASA Earthdata login (for the datasets named in the deck)

1. Create a free account at https://urs.earthdata.nasa.gov
2. In your profile, open **Applications → Authorized Apps** and approve **NASA GESDISC DATA ARCHIVE** (needed for MERRA-2).
3. Save the login once: `.venv/bin/python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"`

## Data sources

| Stage | Dataset | Notes |
|---|---|---|
| Observe (regional) | **NASA PACE OCI L2 SFREFL**: hyperspectral, 122 bands, ~1.2 km | near-real-time product online ~3 h after each daily pass |
| Observe (coastal) | **ESA Sentinel-2 L2A**, 10–20 m | Earth Search STAC, no login |
| Currents | **NASA OSCAR v2.0**, 0.25°, daily | Open-Meteo Marine (Mercator SMOC) for live forecasts |
| Wind | **NASA MERRA-2** 10 m wind, hourly (Bay subset via NASA cloud OPeNDAP) | Open-Meteo GFS/ECMWF for live forecasts |
| AI training | **MARIDA**: labelled Sentinel-2 marine-debris dataset | 15 classes, official splits |
| Validation | **NOAA Global Drifter Program** buoys | 6-hourly QC tracks |
| Coast / land | Natural Earth 10 m | beaching and routing |

## Results

### Detection: two-expert classifier, MARIDA test split

| Metric | First model | Round 1 | **Round 2 (current)** |
|---|---|---|---|
| Overall accuracy (15 classes) | 79.5 % | 91.9 % | **94.1 %** |
| Floating material F1 (debris + sargassum) | 0.89 | 0.94 (P 0.91, R 0.97) | **0.93** (P 0.90, R 0.97) |
| Marine debris F1 | 0.62 | 0.75 (P 0.67, R 0.86) | **0.78** (P 0.70, R 0.89) |
| Macro F1 (all 15 classes equal) | 0.58 | 0.74 | **0.78** |

Every choice was made on the **validation** split (`models/experiments_val.json`, `models/experiments_v2_val.json`)
before the test split was scored. The test split has been scored twice in the project, once per round, and the
round-2 model was kept regardless of its test score.
- **Neighbourhood texture features** (3×3 and 7×7 mean, std and contrast). Debris lines, ships, waves and foam
  differ in shape as well as colour. This alone added about 8 points of accuracy (round 1).
- **Feature set v2** (round 2): 15×15 context and edge strength (Sobel gradient) of ΔFDI, ΔNDVI and the blue / NIR
  bands, 44 features in total. Debris windrows are thin lines with sharp edges.
- **Two experts** (round 2): Extra Trees decides *floating material or not* (it has the best debris F1 and is well
  calibrated). A 50/50 soft vote of Extra Trees and gradient boosting names every other class, where boosting is much
  stronger (water types, wakes, waves). On validation: accuracy 88.3 → 94.1 %, debris F1 unchanged (0.846 → 0.843).
  12 of 15 classes improved on test (Wakes +0.13, Mixed Water +0.10, Waves +0.07).
- **Background-relative spectra** (each pixel minus its surrounding water). A raw-reflectance model mistook
  ordinary Bay water for clouds and wakes, because MARIDA and Sentinel-2 L2A are processed differently.
- Tried and rejected on validation: more training pixels (no gain), a lower debris decision threshold (lower F1).

**Confidence calibration** (`models/calibration.json`, the deck's "TRUST" metric): expected calibration error
0.9 % for floating material and 0.6 % for debris. In the mid range the model is slightly *under*-confident
(it says 66 % and is right 83 % of the time), which is the safe direction for a cleanup tool.

### Forecast: drift model vs real buoys (NOAA drifters, Bay of Bengal)

Drift settings were tuned on **January 2025** buoys (`python -m aquatrace.tune_drift`) and scored once on
**February 2025** buoys they never saw (87 forecasts, 5 drifters; `outputs/drift_validation.json`).

| NASA OSCAR + MERRA-2 forcing, Feb 2025 (held out) | 24 h median error | 48 h median error | Real buoy inside the 90 % cone (24 h / 48 h) |
|---|---|---|---|
| **AquaTrace (currents + 2–3 % wind + current error)** | **16.6 km** | **30.4 km** | **79 % / 86 %** |
| Before tuning (1–3 % wind, diffusion only) | 16.3 km | 29.3 km | 6 % / 5 % |
| Currents only (no wind) | 19.4 km | 37.0 km | |
| "Debris stays where it was seen" | 37.1 km | 73.8 km | |
| Improvement over the snapshot | **55 %** | **59 %** | |

- **The uncertainty cone is now honest.** Before, the 90 % cone drawn on the map held the real buoy only 5 % of the
  time: it showed diffusion alone, but real errors grow in proportion to time, which is the signature of errors
  in the current data. Each particle now carries its own current error (σ = 0.16 m/s, in ± pairs so the cone's
  centre does not move). That is in the range of typical errors of satellite-derived currents (0.1–0.2 m/s) and gives a
  79–86 % hit rate on the held-out month.
- **Position error is limited by the forcing data** (daily, 25 km currents). Tuning changed it by about 1 km,
  within the noise of 5 buoys. Scaling the currents up or down made it worse, and the Mercator SMOC currents
  (Open-Meteo) were less accurate (43 km at 48 h).
- **Wind + current fusion is measurably better** than currents alone (37.0 → 30.4 km at 48 h). On January the
  error was lowest at 2.5 % windage, so the ensemble samples 2–3 %.

## How each part works

- **Detect** (`detect.py`): PACE's 122 bands are resampled to Sentinel-2-equivalent bands so one model serves both
  sensors. Land, cloud (+ buffer), glint, bright objects, the shoreline strip and inland water are masked. Pixels are
  scored by the Floating Debris Index (FDI) against their local water background, then checked by the classifier
  (ships, wakes, waves and clouds rejected). Hotspot confidence = anomaly strength + size + ML probability
  (the ML weight is lower on PACE's 1.2 km pixels).
- **Forecast** (`drift.py`): 300 particles per hotspot move with `current + windage × wind + current error` (RK4,
  hourly) plus a random walk. The spread is the **uncertainty cone**, calibrated on real buoys. Particles reaching
  land are **beached**.
- **Nowcast** (live mode): each detection is moved from its satellite time to *now*, so the map stays current between
  passes and under clouds.
- **Source tracking** (`source.py`): the same model run **backwards** 72 h. Back-tracked particles that reach land
  point to a coastal or river source (12 named river mouths around the Bay).
- **Prioritize** (`risk.py`): risk = 35 % confidence + 25 % proximity to sensitive sites / coast + 15 % beaching +
  15 % recurrence across passes + 10 % forecast certainty (spread caused by the hotspot's own flow). Tiers: High ≥ 60, Medium ≥ 40. Plain-language actions
  (intercept by vessel / send a shoreline team / monitor).
- **Route** (`route.py`): greedy moving-target interception from a port. Each stop is aimed at the forecast position at
  the boat's arrival time. Legs over land and stops beyond the 48 h forecast are skipped.

## Honest limitations (say these before a judge asks)

- **No satellite shows every piece of plastic live.** PACE passes once a day (~1.2 km pixels), Sentinel-2 every few days
  near the coast, and clouds block both. We show *potential* floating-material hotspots with confidence, and the
  drift model carries them forward between passes.
- **MARIDA scenes are not from the Bay of Bengal.** Detection scores are on MARIDA's test split. Local ground truth
  (drones, beach surveys, fishermen reports) is Phase 2.
- **NASA OSCAR / MERRA-2 arrive days to weeks late**, so NASA runs are replays. Live runs use forecast currents and wind.
- The buoy validation checks the current/wind field with surface drifters, a proxy for debris, not debris itself.
- Routes are straight lines between waypoints (no detailed sea-lane routing).
- The model file is larger than GitHub's 100 MB limit, so `.gitignore` excludes it. Share it separately or use
  Git LFS if you put the project on GitHub.

## Project layout

```
backend/aquatrace/
  config.py          region, forecast and model settings
  sources/           nasa.py (PACE, OSCAR, MERRA-2) · openmeteo.py · sentinel2.py · coast.py
  forcing.py         common gridded velocity field + interpolation
  detect.py          indices, texture features, anomaly, hotspots, map overlays
  marida.py          classifier training + metrics      experiments.py  model selection (validation split)
  calibration.py     reliability curve / ECE
  drift.py           Lagrangian particle model (forward and backward)
  source.py          source back-tracking               route.py        cleanup route planner
  risk.py            risk score + recommended action
  validate.py        buoy validation + windage calibration
  pipeline.py        replay (--date) and live (--live) runs → outputs/runs/<id>/run.json
  api.py             FastAPI: runs, metrics, what-if forecasts, routes, and the web app
frontend/            React + Vite + Leaflet map app (dist/ = built copy)
models/              classifier metrics, calibration, experiment log (+ trained model once retrained)
outputs/             pipeline runs (runs/<id>/run.json + overlays), buoy validation, windage calibration
data/                processed forcing caches, coastline, drifter tracks (raw satellite data is downloaded on demand)
docs/screenshots/    app screenshots used in the deck; shoot_cdp.py recaptures them (waits for map tiles)
docs/evidence/       how detection works, from the raw pixels (make_evidence.py → deck slide 11, report 6.1)
presentation/        Innothon'26 pitch deck with the results slides
DEMO.md              4-minute demo script and judge Q&A
CLAUDE.md            guide for AI coding assistants (Claude Code) working on this repo
```
