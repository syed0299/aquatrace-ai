# CLAUDE.md

Guidance for Claude Code (and other contributors) working on **AquaTrace AI**: marine-debris hotspot
detection (NASA PACE / Sentinel-2 + ML), 24–48 h Lagrangian drift forecasting (NASA OSCAR currents + MERRA-2
wind), source back-tracking, cleanup risk ranking and route planning for a Bay of Bengal pilot. Built for the
Innothon'26 hackathon. See `README.md` for results and `DEMO.md` for the pitch.

## Commands

```bash
./setup.sh                                   # .venv + Python deps (+ frontend build if npm exists)
./run_demo.sh                                # FastAPI + built web app on http://localhost:8000
cd frontend && npm run dev                   # frontend dev server on :5173 (proxies /api to :8000)
cd frontend && npm run build                 # rebuild dist/ (the backend serves it; restart not needed)

cd backend                                   # all Python modules run from here with ../.venv/bin/python
python -m aquatrace.pipeline --live          # near-real-time run (needs Earthdata login for PACE)
python -m aquatrace.pipeline --date 2026-03-14            # replay a past date (NASA data if logged in)
python -m aquatrace.pipeline --date 2026-03-05 --source s2  # Sentinel-2 + Open-Meteo only, no login
python -m aquatrace.marida                   # train classifier (needs data/raw/marida, see README)
python -m aquatrace.experiments              # model selection on the validation split
python -m aquatrace.calibration              # reliability curve / ECE from the saved test probabilities
python -m aquatrace.experiments_v2           # round-2 selection: feature set v2, ensembles, two experts
python -m aquatrace.tune_drift               # drift settings: tune on Jan 2025 buoys, check on Feb
python -m aquatrace.validate --holdout        # buoy validation on the held-out month (writes drift_validation.json)
python -m aquatrace.pipeline --live --issued 2026-09-30T19:00   # re-issue a past live run with cached data
```

There is no unit-test suite yet. To verify a change: `python -m py_compile aquatrace/*.py aquatrace/sources/*.py`,
re-run a cached replay (`--date 2026-03-05 --source s2` is fast when caches exist), `npm run build`, then curl
`/api/runs`, `/api/metrics`, `/api/runs/<id>/route?port=Chennai` and `POST /api/forecast` and check the UI.
The uvicorn server has no `--reload`, so restart it after backend changes.

## Architecture

`pipeline.py` orchestrates OBSERVE → DETECT → FUSE → FORECAST → PRIORITIZE and writes
`outputs/runs/<run_id>/run.json` (+ overlay PNGs). `api.py` only serves those files, plus two computed endpoints
(`POST /api/forecast` what-if, `GET /api/runs/<id>/route`). The React app (`frontend/src`) renders run.json.

- `sources/`: `nasa.py` (PACE SFREFL/NRT via earthaccess, OSCAR v2.0, MERRA-2 via cloud OPeNDAP), `openmeteo.py`
  (fallback + live forecast forcing), `sentinel2.py` (Earth Search STAC), `coast.py` (land mask, coast
  distance, sensitive sites)
- `forcing.py`: `VelocityField`, the common (time, lat, lon) u/v grid in m/s with interpolation. Every source converts to this
- `detect.py`: resample to Sentinel-2-equivalent bands → masks → FDI anomaly z-score → ML check → hotspots
- `marida.py`: two-expert classifier (Extra Trees + HistGradientBoosting); `RFModel` wraps it for inference (`predict_proba_groups`)
- `drift.py`: RK4 particle ensemble with per-particle current error (antithetic pairs), forward or `backward=True`; `source.py` back-tracks; `risk.py` scores;
  `route.py` plans moving-target vessel routes; `validate.py` scores forecasts against NOAA drifters

run.json invariants: `hotspots[i]` and `forecasts[i]` are the same hotspot (same order and `id`). Live runs add
`live`, `issued`, `latest_pass`, `forcing_files`, and per-hotspot `detected` / `nowcast` / `ashore`.

## Decisions that must not be broken

- **Test split discipline**: choose models/features on MARIDA's validation split (`experiments.py`, `experiments_v2.py`);
  `marida.train()` scores the test split. Never tune on test. Reported numbers (94.1 % accuracy etc.) are the round-2
  score; the test split has been scored once per round (twice in total).
- **Drift hold-out discipline**: drift settings (`WINDAGE_RANGE`, `DIFFUSIVITY`, `CURRENT_SIGMA`) are tuned on January
  2025 buoys (`tune_drift.py`) and reported on February 2025 (`validate --holdout`). Don't tune on February.
- **Same features in training and inference**: `detect.feature_image` (background-relative bands + texture; `extra=True`
  adds feature set v2). The model bundle stores `spatial` / `extra` flags and inference reads them. If you change
  features, retrain the model and update README/DEMO/deck/report numbers.
- **Two experts**: `marida.hybrid_predict`: Extra Trees alone decides floating vs not (and gives the calibrated
  P(floating)); the ET + gradient-boosting soft vote only names non-floating classes.
- **Background-relative features exist on purpose**: raw-reflectance models mistook Bay water for clouds/wakes
  (MARIDA vs Sentinel-2 L2A processing differ). Keep them.
- **Honest framing**: outputs are *potential* floating-material hotspots with confidence; PACE pixels are ~1.2 km.
  Don't describe the system as a live video of debris. Live mode = latest pass + nowcast + forecast.
- Beaching counts only sea→land transitions (near-shore seeds may start inside the coarse land polygon).
- On PACE (non-native sensor) the ML probability gets a lower weight in hotspot confidence than on Sentinel-2.

## Data-source gotchas

- Earthdata login lives in `~/.netrc` (never in the repo). MERRA-2 also needs "NASA GESDISC DATA ARCHIVE" approved
  in the user's Earthdata profile. `nasa.logged_in()` gates NASA use; pipelines fall back to open sources.
- MERRA-2: the old `goldsmr4` OPeNDAP returns 410. Use the cloud OPeNDAP DAP4 subset (`MERRA2_OPENDAP` in nasa.py).
- OSCAR v2.0: `lon`/`lat` are plain coordinates on `longitude`/`latitude` dims, times are cftime, daily means are
  stamped 00:00 (we shift to 12:00). Product preference: final → interim → nrt.
- PACE: `geophysical_data/rhos` (lines × pixels × 122 bands), `sensor_band_parameters/wavelength_3d`, `l2_flags`.
  Granules are ~730 MB. NRT product (`PACE_OCI_L2_SFREFL_NRT`) appears ~3 h after the pass.
- Earth Search Sentinel-2: when `earthsearch:boa_offset_applied` is true, do NOT add the −0.1 offset.
- Open-Meteo free tier is ~10k location-calls/day; a 0.5° Bay grid is ~1,365 points per field. Results are cached
  in `data/processed/` (file name encodes source and date range), so delete a cache file to force a refetch.
- NOAA GDP: hourly QC data ends in 2022; use `drifter_6hour_qc` (to mid-2025). The ERDDAP server is slow, so use long timeouts.
- Natural Earth land/coast shapefiles download on first use into `data/raw/naturalearth/`.

## Conventions

- Python: small modules, type hints where useful, `logging.getLogger("aquatrace")`, settings in `config.py`,
  paths via `config.ROOT/DATA/RAW/PROCESSED/OUTPUTS/MODELS`. No notebooks in the pipeline.
- Frontend: React function components, plain CSS with variables in `index.css`, API calls only in `api.js`.
  Views are linkable via URL params (`run`, `select`, `hour`, `route`, `stops`, `view=lat,lon,zoom`, `hide`).
- Don't commit `data/raw/`, `.venv/`, `node_modules/` or `models/*.joblib` (see `.gitignore`).
