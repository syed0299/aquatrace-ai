"""FastAPI backend: serves pipeline runs, model metrics and on-demand drift forecasts.

    cd backend && ../.venv/bin/uvicorn aquatrace.api:app --port 8000
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import BBOX, MODELS, OUTPUTS, PROCESSED, ROOT
from .drift import Seed, simulate
from .forcing import VelocityField
from .pipeline import RUNS, load_forcing
from .risk import score
from .route import PORTS, plan
from .sources.coast import on_land

app = FastAPI(title="AquaTrace AI", version="0.1.0",
              description="Marine-debris hotspot detection and 24-48 h drift forecasting (Bay of Bengal pilot)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/runs")
def runs():
    out = []
    for rid in _read(RUNS / "index.json") or []:
        r = _read(RUNS / rid / "run.json")
        if r:
            out.append({"run_id": rid, "date": r["date"], "detection": r["sources"]["detection"],
                        "currents": r["sources"]["currents"]["source"], "wind": r["sources"]["wind"]["source"],
                        "hotspots": len(r["hotspots"]),
                        "high": sum(h["risk"]["tier"] == "High" for h in r["hotspots"])})
    return out


def _run(run_id: str) -> dict:
    path = RUNS / run_id / "run.json"
    if not path.exists():
        raise HTTPException(404, f"run {run_id} not found")
    return _load_run(path, path.stat().st_mtime)  # mtime in the key: re-runs are picked up


@lru_cache(maxsize=8)
def _load_run(path, mtime) -> dict:
    return _read(path)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return _run(run_id)


@app.get("/api/runs/{run_id}/files/{path:path}")
def run_file(run_id: str, path: str):
    base = (RUNS / run_id).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/metrics")
def metrics():
    return {"detection": _read(MODELS / "marida_metrics.json"),
            "calibration": _read(MODELS / "calibration.json"),
            "drift": _read(OUTPUTS / "drift_validation.json")}


@lru_cache(maxsize=4)
def _field(rel: str) -> VelocityField:
    return VelocityField.from_netcdf(PROCESSED / rel)


@app.get("/api/ports")
def ports():
    return PORTS


@app.get("/api/runs/{run_id}/route")
def route(run_id: str, port: str, speed_kn: float = 10.0, max_stops: int = 5, include_low: bool = False):
    """Cleanup vessel route that intercepts hotspots at their forecast positions."""
    try:
        return plan(_run(run_id), port, speed_kn=speed_kn, max_stops=max_stops, include_low=include_low)
    except ValueError as e:
        raise HTTPException(400, str(e))


class ForecastRequest(BaseModel):
    lat: float = Field(..., ge=BBOX["lat_min"], le=BBOX["lat_max"])
    lon: float = Field(..., ge=BBOX["lon_min"], le=BBOX["lon_max"])
    run_id: str
    confidence: float = Field(0.6, ge=0, le=1)


@app.post("/api/forecast")
def forecast(req: ForecastRequest):
    """'What if debris were here?': live 48 h drift + risk for any clicked point."""
    if on_land([req.lat], [req.lon])[0]:
        raise HTTPException(400, "That point is on land - click on the sea.")
    r = _run(req.run_id)
    day = date.fromisoformat(r["date"])
    if r.get("live"):  # live runs carry their own forecast forcing and start "now"
        currents, wind = (_field(r["forcing_files"][k]) for k in ("currents", "wind"))
        start = datetime.fromisoformat(r["issued"])
    else:
        currents = load_forcing("currents", day, day + timedelta(days=3))
        wind = load_forcing("wind", day, day + timedelta(days=3))
        start = min((datetime.fromisoformat(h["observed"]) for h in r["hotspots"]),
                    default=datetime.combine(day, datetime.min.time()) + timedelta(hours=6))
    fc = simulate([Seed("USER", req.lat, req.lon, 1.0)], start, currents, wind)[0]
    h = {"id": "USER", "lat": req.lat, "lon": req.lon, "confidence": req.confidence}
    return {"forecast": fc, "risk": score(h, fc)}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
