import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import Briefing from './components/Briefing'
import Drawer from './components/Drawer'
import { RoutePanel, TrustPanel } from './components/Panels'
import Timeline from './components/Timeline'
import Toolbar from './components/Toolbar'
import TopBar from './components/TopBar'
import { TIER } from './lib/geo'
import { utc } from './lib/format'
import MapView, { HOME } from './map/MapView'

const ALL_TIERS = ['High', 'Medium', 'Low']
const DEFAULT_LAYERS = { currents: true, wind: false, anomaly: false, satellite: false, cones: true, particles: true, sites: true }

export default function App() {
  const [runs, setRuns] = useState([])
  const [runId, setRunId] = useState(null)
  const [run, setRun] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [selected, setSelected] = useState(null)
  const [hovered, setHovered] = useState(null)
  const [layers, setLayers] = useState(DEFAULT_LAYERS)
  const [basemap, setBasemap] = useState('ocean')
  const [tierFilter, setTierFilter] = useState(new Set(ALL_TIERS))
  const [sort, setSort] = useState('risk')
  const [whatIfMode, setWhatIfMode] = useState(false)
  const [whatIf, setWhatIf] = useState(null)
  const [route, setRoute] = useState(null)
  const [routeOpen, setRouteOpen] = useState(false)
  const [trustOpen, setTrustOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const mapRef = useRef(null)

  useEffect(() => {
    api.runs()
      .then((r) => {
        setRuns(r)
        const want = new URLSearchParams(window.location.search).get('run')
        if (r.length) setRunId(r.find((x) => x.run_id === want)?.run_id || r[0].run_id)
      })
      .catch((e) => setError(`Cannot reach the AquaTrace API (${e.message}). Is the backend running?`))
    api.metrics().then(setMetrics).catch(() => {})
  }, [])

  useEffect(() => {
    if (!runId) return
    setRun(null); setSelected(null); setWhatIf(null); setHour(0); setRoute(null)
    api.run(runId).then(setRun).catch((e) => setError(e.message))
  }, [runId])

  // Shareable views, e.g. ?run=20260314_pace&select=HS-07&hour=24&route=Port%20Blair&stops=4&hide=cones
  const applied = useRef(false)
  useEffect(() => {
    if (!run || applied.current) return
    applied.current = true
    const q = new URLSearchParams(window.location.search)
    if (q.get('select')) setSelected(q.get('select'))
    if (q.get('hour')) setHour(Number(q.get('hour')))
    if (q.get('basemap')) setBasemap(q.get('basemap'))
    if (q.get('trust')) setTrustOpen(true)
    if (q.get('shot')) document.body.classList.add('shot')
    if (q.get('hide')) setLayers((l) => ({ ...l, ...Object.fromEntries(q.get('hide').split(',').map((k) => [k, false])) }))
    if (q.get('show')) setLayers((l) => ({ ...l, ...Object.fromEntries(q.get('show').split(',').map((k) => [k, true])) }))
    if (q.get('route')) {
      setRouteOpen(true)
      api.route(run.run_id, { port: q.get('route'), max_stops: q.get('stops') || 4, include_low: true }).then(setRoute).catch(() => {})
    }
  }, [run])

  // Pick up a newer live run automatically (the pipeline can be scheduled after each satellite pass)
  useEffect(() => {
    const t = setInterval(() => {
      api.runs().then((r) => {
        setRuns(r)
        if (run?.live && r[0]?.run_id.startsWith('live_') && r[0].run_id !== runId) setRunId(r[0].run_id)
      }).catch(() => {})
    }, 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [run, runId])

  // Smooth playback: 48 forecast hours in ~16 s at 1x
  useEffect(() => {
    if (!playing) return undefined
    const t = setInterval(() => setHour((h) => (h >= 48 ? 0 : Math.min(48, Math.round((h + 0.15 * speed) * 100) / 100))), 50)
    return () => clearInterval(t)
  }, [playing, speed])

  const forecastById = useMemo(() => {
    const m = {}
    run?.forecasts.forEach((f) => { m[f.id] = f })
    if (whatIf) m.USER = whatIf.forecast
    return m
  }, [run, whatIf])

  const visible = useMemo(() => new Set((run?.hotspots || []).filter((h) => tierFilter.has(h.risk.tier)).map((h) => h.id)), [run, tierFilter])

  const select = useCallback((id) => {
    setSelected(id)
    if (id && id !== 'USER') setWhatIfMode(false)
  }, [])

  const goHome = useCallback(() => {
    setSelected(null)
    mapRef.current?.flyTo(HOME.center, HOME.zoom, { duration: 0.8 })
  }, [])

  // Keyboard: space = play/pause, arrows = scrub, Home/End, Esc = close
  useEffect(() => {
    const onKey = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
      else if (e.key === 'ArrowRight') setHour((h) => Math.min(48, Math.floor(h) + 1))
      else if (e.key === 'ArrowLeft') setHour((h) => Math.max(0, Math.ceil(h) - 1))
      else if (e.key === 'Home') setHour(0)
      else if (e.key === 'End') setHour(48)
      else if (e.key === 'Escape') { setSelected(null); setWhatIfMode(false); setRouteOpen(false); setTrustOpen(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  async function onMapClick(lat, lon) {
    if (!whatIfMode || !runId) return
    setBusy(true); setError(null)
    try {
      const r = await api.forecast({ lat, lon, run_id: runId })
      setWhatIf({ ...r, lat, lon })
      setSelected('USER')
      setHour(0)
      setPlaying(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const selHotspot = selected === 'USER' && whatIf
    ? { id: 'USER', lat: whatIf.lat, lon: whatIf.lon, risk: whatIf.risk, confidence: 0.6 }
    : run?.hotspots.find((h) => h.id === selected)
  const start = useMemo(() => {
    const fc = selected && forecastById[selected]
    if (fc) return utc(fc.start)
    if (run?.live) return utc(run.issued)
    return null
  }, [run, selected, forecastById])
  const drawerOpen = !!(selHotspot && forecastById[selected])

  return (
    <div className="app">
      <TopBar runs={runs} runId={runId} setRunId={setRunId} run={run} trustOpen={trustOpen} setTrustOpen={setTrustOpen} />
      <Briefing run={run} forecastById={forecastById} tierFilter={tierFilter} setTierFilter={setTierFilter}
        sort={sort} setSort={setSort} selected={selected} hovered={hovered} setHovered={setHovered} onSelect={select} />

      <main className={`stage ${drawerOpen ? 'has-drawer' : ''}`}>
        <MapView run={run} runId={runId} hour={hour} layers={layers} basemap={basemap} selected={selected}
          hovered={hovered} setHovered={setHovered} onSelect={select} visible={visible} forecastById={forecastById}
          whatIf={whatIf} whatIfMode={whatIfMode} onMapClick={onMapClick} route={route} mapRef={mapRef} />

        <Toolbar basemap={basemap} setBasemap={setBasemap} layers={layers} setLayers={setLayers}
          whatIfMode={whatIfMode} setWhatIfMode={setWhatIfMode} routeOpen={routeOpen} setRouteOpen={setRouteOpen} onHome={goHome} />

        {routeOpen && <RoutePanel runId={runId} route={route} setRoute={setRoute} onClose={() => setRouteOpen(false)}
          setError={setError} onSelect={select} />}
        {trustOpen && <TrustPanel metrics={metrics} onClose={() => setTrustOpen(false)} />}

        {whatIfMode && (
          <div className="banner" role="status">
            {busy ? 'Simulating 300 particles…' : 'What-if mode: click anywhere on the sea to drop a virtual debris patch'}
            <kbd>Esc</kbd>
          </div>
        )}
        {error && <button type="button" className="toast" onClick={() => setError(null)}>{error}</button>}

        <div className="legend" aria-label="Legend">
          {ALL_TIERS.map((t) => <span key={t}><i style={{ background: TIER[t].color }} />{t}</span>)}
          <span><i className="lg-line" />track</span>
          <span><i className="lg-cone" />48 h cone</span>
          <span><i className="lg-back" />came from</span>
          {layers.currents && <span><i className="lg-flow" />currents</span>}
        </div>

        <Timeline hour={hour} setHour={setHour} playing={playing} setPlaying={setPlaying} speed={speed} setSpeed={setSpeed}
          start={start} live={!!run?.live} />

        <Drawer hotspot={selHotspot} fc={selected && forecastById[selected]} isWhatIf={selected === 'USER'}
          onClose={() => setSelected(null)} />
      </main>
    </div>
  )
}
