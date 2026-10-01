import { useState } from 'react'
import { Check, Copy, Satellite, Ship, Siren, Waves, X } from 'lucide-react'
import { TIER, WHATIF, driftSummary } from '../lib/geo'
import { coord, fmtIST, pct, utc } from '../lib/format'
import { Compass, Flag, Gauge } from './Marks'

const COMPONENTS = [
  ['confidence', 'Detection confidence', 35],
  ['proximity', 'Near sensitive coast', 25],
  ['beaching', 'Likely to wash ashore', 15],
  ['persistence', 'Seen on several passes', 15],
  ['certainty', 'Forecast certainty', 10],
]

function Stat({ value, label }) {
  return <div className="stat"><b>{value}</b><span>{label}</span></div>
}

function CopyCoord({ lat, lon }) {
  const [done, setDone] = useState(false)
  const text = coord(lat, lon)
  return (
    <button type="button" className="coord" title="Copy coordinates"
      onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200) }}>
      {text} {done ? <Check size={12} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
    </button>
  )
}

export default function Drawer({ hotspot, fc, isWhatIf, onClose }) {
  const open = !!(hotspot && fc)
  if (!open) return <aside className="drawer" aria-hidden="true" />
  const h = hotspot
  const tier = h.risk.tier
  const t = isWhatIf ? { color: WHATIF, soft: 'var(--signal-soft)', ink: '#1A3AB8' } : TIER[tier]
  const d = driftSummary(h, fc)
  const hours = fc.horizons['48'].displacement_km
  const ActionIcon = /shoreline|ashore/i.test(h.risk.action) ? Waves : /vessel/i.test(h.risk.action) ? Ship : Siren

  return (
    <aside className="drawer open" aria-label={`${h.id} details`}>
      <div className="dr-head">
        <div className="dr-title">
          <Flag tier={isWhatIf ? 'whatif' : tier} size={22} />
          <h2>{isWhatIf ? 'What-if release' : h.id}</h2>
          <span className="tier-pill" style={{ background: t.soft, color: t.ink }}>{isWhatIf ? 'Simulation' : `${tier} priority`}</span>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details"><X size={18} /></button>
      </div>
      <div className="dr-sub">
        {!isWhatIf && <span>{h.region || h.sensor}</span>}
        <CopyCoord lat={h.lat} lon={h.lon} />
      </div>

      <div className="callout" style={{ background: t.soft, color: t.ink }}>
        <ActionIcon size={18} aria-hidden="true" />
        <p>{h.risk.action}</p>
      </div>

      <section className="dr-sec">
        <h3>Cleanup risk</h3>
        <div className="risk-row">
          <Gauge value={h.risk.risk_score} color={t.color} />
          <ul className="bars">
            {COMPONENTS.map(([k, label, w]) => (
              <li key={k}>
                <span>{label}<em>{w}%</em></span>
                <div className="bar"><div style={{ width: pct(h.risk.components[k]), background: t.color }} /></div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="dr-sec">
        <h3>Drift forecast</h3>
        <div className="drift-row">
          <Compass deg={d.deg} color={t.color} />
          <div className="stats">
            <Stat value={`${Math.round(fc.horizons['24'].displacement_km)} km`} label="by +24 h" />
            <Stat value={`${Math.round(hours)} km`} label="by +48 h" />
            <Stat value={`±${Math.round(fc.horizons['48'].spread_km)} km`} label="uncertainty" />
            <Stat value={pct(fc.beached_fraction)} label={fc.first_beaching_h != null ? `ashore from +${fc.first_beaching_h} h` : 'washes ashore'} />
          </div>
        </div>
        <p className="note">Heading <b>{d.dir}</b> at about {(hours / 2).toFixed(0)} km a day. Nearest sensitive site: {h.risk.nearest_site}
          {h.risk.min_distance_to_site_km != null && ` (${h.risk.min_distance_to_site_km} km)`}.</p>
      </section>

      {h.nowcast?.age_h > 0 && (
        <section className="dr-sec">
          <h3>Since the satellite saw it</h3>
          <p className="note">Seen {fmtIST(utc(h.detected.time))}, then drifted {h.nowcast.age_h} h to its estimated position now
            {h.ashore ? ': most likely already ashore.' : '.'}</p>
        </section>
      )}

      {h.source && (
        <section className="dr-sec">
          <h3>Where it came from</h3>
          <p className="note">{h.source.summary}</p>
          {h.source.sources.filter((s) => s.share >= 0.05).map((s) => (
            <div key={s.name} className="share">
              <span>{s.name}</span>
              <div className="bar"><div style={{ width: pct(Math.min(1, s.share)), background: 'var(--violet)' }} /></div>
              <b>{pct(s.share)}</b>
            </div>
          ))}
        </section>
      )}

      {!isWhatIf && (
        <section className="dr-sec">
          <h3>Evidence</h3>
          <dl className="facts">
            <dt><Satellite size={13} aria-hidden="true" /> Satellite</dt><dd>{h.sensor}</dd>
            <dt>Observed</dt><dd>{fmtIST(utc(h.observed))}</dd>
            <dt>Debris signal</dt><dd>FDI anomaly z = {h.max_z} · {h.pixels} px</dd>
            {h.p_floating_ml != null && <><dt>AI model</dt><dd>{pct(h.p_floating_ml)} floating material · looks like {h.ml_class?.toLowerCase()}</dd></>}
            <dt>Patch size</dt><dd>{h.area_km2} km²</dd>
          </dl>
        </section>
      )}
    </aside>
  )
}
