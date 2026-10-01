import { useEffect, useState } from 'react'
import { Ship, X } from 'lucide-react'
import { api } from '../api'
import { TIER } from '../lib/geo'
import { Reliability } from './Marks'

export function RoutePanel({ runId, route, setRoute, onClose, setError, onSelect }) {
  const [ports, setPorts] = useState([])
  const [port, setPort] = useState('Chennai')
  const [speed, setSpeed] = useState(10)
  const [stops, setStops] = useState(4)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.ports().then(setPorts).catch(() => {}) }, [])
  useEffect(() => { if (route) setPort(route.port.name) }, [route])

  async function plan() {
    setBusy(true)
    try {
      const r = await api.route(runId, { port, speed_kn: speed, max_stops: stops, include_low: true })
      setRoute(r)
      if (!r.stops.length) setError(`No reachable hotspots at sea within 450 km of ${port}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="float-panel route-panel" aria-label="Cleanup route planner">
      <header>
        <h3><Ship size={16} aria-hidden="true" /> Cleanup route</h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close route planner"><X size={16} /></button>
      </header>
      <p className="muted">The boat is sent to where each patch <i>will be</i> when it arrives, not where it was seen.</p>
      <label className="field">Depart from
        <select value={port} onChange={(e) => setPort(e.target.value)}>
          {ports.map((p) => <option key={p.name}>{p.name}</option>)}
        </select>
      </label>
      <div className="field-row">
        <label className="field">Speed (knots)
          <input type="number" min={5} max={30} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} />
        </label>
        <label className="field">Max stops
          <input type="number" min={1} max={10} value={stops} onChange={(e) => setStops(Number(e.target.value))} />
        </label>
      </div>
      <button type="button" className="primary" onClick={plan} disabled={busy || !runId}>{busy ? 'Planning…' : 'Plan route'}</button>
      {route?.stops?.length > 0 && (
        <div className="route-result">
          <div className="route-total">
            <div><b>{route.total_km}</b><span>km</span></div>
            <div><b>{route.total_h}</b><span>hours</span></div>
            <div><b>{route.stops.length}</b><span>stops</span></div>
          </div>
          <ol>
            {route.stops.map((s, i) => (
              <li key={s.id}>
                <button type="button" onClick={() => onSelect(s.id)}>
                  <span className="stop-num">{i + 1}</span>
                  <span><b>{s.id}</b> <em style={{ color: TIER[s.tier].ink }}>{s.tier}</em><br />
                    <small>arrive +{s.arrive_h} h · drifts {s.drift_since_seen_km} km first</small></span>
                </button>
              </li>
            ))}
          </ol>
          <button type="button" className="link" onClick={() => setRoute(null)}>Clear route</button>
        </div>
      )}
    </section>
  )
}

export function TrustPanel({ metrics, onClose }) {
  const det = metrics?.detection
  const drift = metrics?.drift
  const cal = metrics?.calibration?.floating_material
  return (
    <section className="float-panel trust-panel" aria-label="Model trust">
      <header>
        <h3>How far to trust this</h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
      </header>
      {det ? (
        <>
          <div className="trust-grid">
            <div><b>{(det.accuracy * 100).toFixed(1)}%</b><span>detection accuracy</span></div>
            <div><b>{det.floating_material.f1.toFixed(2)}</b><span>F1 floating material</span></div>
            <div><b>{det.debris.f1.toFixed(2)}</b><span>F1 marine debris</span></div>
            {drift && <div><b>{Math.round(drift.summary['48'].median_km)} km</b><span>error at +48 h</span></div>}
            {drift && <div><b>{Math.round(drift.skill_vs_persistence['48'] * 100)}%</b><span>better than a snapshot</span></div>}
            {drift && (drift.summary['48'].cone90_coverage != null
              ? <div><b>{Math.round(drift.summary['48'].cone90_coverage * 100)}%</b><span>buoys inside the 48 h cone</span></div>
              : <div><b>{Math.round(drift.summary['24'].median_km)} km</b><span>error at +24 h</span></div>)}
          </div>
          <div className="trust-cal">
            <Reliability cal={cal} />
            <p><b>Calibration error {(cal.ece * 100).toFixed(1)}%.</b> When the model says it is 80% sure, it is right at least
              that often. Dashed line = perfect.</p>
          </div>
          <p className="muted small">Detection: MARIDA test split, {det.test_pixels.toLocaleString()} unseen pixels.
            {drift && ` Forecast: ${drift.cases} forecasts against ${drift.drifters} NOAA drifting buoys in the Bay`}
            {drift?.held_out ? ', in a month not used for tuning.' : drift ? '.' : ''}</p>
        </>
      ) : <p className="muted">Metrics not available.</p>}
    </section>
  )
}
