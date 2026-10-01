"""Project-wide settings for the AquaTrace AI prototype."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
OUTPUTS = ROOT / "outputs"
MODELS = ROOT / "models"

for _d in (RAW, PROCESSED, OUTPUTS, MODELS):
    _d.mkdir(parents=True, exist_ok=True)

# Phase 1 pilot region: Bay of Bengal (+ Andaman Sea edge)
BBOX = {"lon_min": 79.0, "lon_max": 96.0, "lat_min": 4.0, "lat_max": 23.0}

# Drift forecast
FORECAST_HOURS = 48
DT_HOURS = 1.0
PARTICLES_PER_HOTSPOT = 300
# Drift settings tuned on January 2025 NOAA drifters and checked on February 2025 (tune_drift.py,
# outputs/drift_tuning.json).
# Share of 10 m wind speed transferred to floating debris ("windage"), sampled per particle
# (unknown debris type). Literature range for floating plastics is 1-3 %; buoys favour 2-3 %.
WINDAGE_RANGE = (0.02, 0.03)
# Horizontal eddy diffusivity (m^2/s) for the random-walk term.
DIFFUSIVITY = 20.0
# Per-particle current error (m/s): daily ~25 km current maps miss tides and small eddies. With it the
# 90 % cone contains real buoys 79-86 % of the time on the held-out month (5-6 % without it).
CURRENT_SIGMA = 0.16
RANDOM_SEED = 42

EARTH_RADIUS_M = 6_371_000.0
M_PER_DEG_LAT = 111_320.0
