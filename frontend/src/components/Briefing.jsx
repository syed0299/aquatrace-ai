import { useMemo } from 'react'
import { ArrowUp, Clock, MapPin, Navigation, Waves } from 'lucide-react'
import { TIER, driftSummary } from '../lib/geo'
import { fmtDay, hoursAgo, utc } from '../lib/format'
import { Flag } from './Marks'

const TIERS = ['High', 'Medium', 'Low']
const SORTS = { risk: 'Risk', drift: 'Drift distance', confidence: 'Confidence' }

function Insight({ icon: Icon, label, value, sub }) {
  return (
    <div className="insight">
      <span className="insight-label"><Icon size={13} aria-hidden="true" /> {label}</span>
      <b>{value}</b>
      <span className="insight-sub">{sub}</span>
    </div>
  )
}

export default function Briefing({
  run, forecastById, tierFilter, setTierFilter, sort, setSort, selected, hovered, setHovered, onSelect,
}) {
  const hs = run?.hotspots || []
  const counts = useMemo(() => Object.fromEntries(TIERS.map((t) => [t, hs.filter((h) => h.risk.tier === t).length])), [hs])

  const insights = useMemo(() => {
    if (!hs.length) return null
    const withFc = hs.map((h) => ({ h, fc: forecastById[h.id] })).filter((x) => x.fc)
    const landing = withFc
      .filter(({ fc }) => fc.first_beaching_h != null && fc.beached_fraction >= 0.3)
      .sort((a, b) => a.fc.first_beaching_h - b.fc.first_beaching_h)[0]
    const fastest = [...withFc].sort((a, b) => b.fc.horizons['48'].displacement_km - a.fc.horizons['48'].displacement_km)[0]
    const passes = [...new Set(hs.map((h) => h.observed.slice(0, 10)))].sort()
    return { landing, fastest, passes }
  }, [hs, forecastById])

  const list = useMemo(() => {
    const key = {
      risk: (h) => -h.risk.risk_score,
      drift: (h) => -(forecastById[h.id]?.horizons['48'].displacement_km || 0),
      confidence: (h) => -h.confidence,
    }[sort]
    return hs.filter((h) => tierFilter.has(h.risk.tier)).sort((a, b) => key(a) - key(b))
  }, [hs, tierFilter, sort, forecastById])

  if (!run) {
    return (
      <aside className="briefing">
        <div className="skeleton" style={{ height: 120 }} />
        {[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 64 }} />)}
      </aside>
    )
  }

  const attention = counts.High + counts.Medium
  const toggle = (t) => {
    const next = new Set(tierFilter)
    if (next.has(t)) next.delete(t); else next.add(t)
    setTierFilter(next.size ? next : new Set(TIERS))
  }

  return (
    <aside className="briefing" aria-label="Cleanup briefing">
      <div className="brief-head">
        <p className="kicker">{run.live ? 'Live briefing' : 'Replay briefing'} · {fmtDay(utc(run.live ? run.issued : `${run.date}T00:00:00`))}</p>
        <h1><span className="big">{hs.length}</span> debris hotspots tracked</h1>
        <p className="lede">
          {attention > 0
            ? <><b>{attention}</b> need attention in the next 48 hours.</>
            : <>None need urgent action. All {hs.length} are low risk and being monitored.</>}
        </p>
      </div>

      {insights && (
        <div className="insights">
          <Insight icon={Waves} label="First landfall"
            value={insights.landing ? `+${insights.landing.fc.first_beaching_h} h` : 'None'}
            sub={insights.landing ? `${insights.landing.h.id} near ${insights.landing.h.risk.nearest_site}` : 'within 48 h'} />
          <Insight icon={Navigation} label="Fastest drift"
            value={`${Math.round(insights.fastest.fc.horizons['48'].displacement_km)} km`}
            sub={`${insights.fastest.h.id} in 48 h`} />
          <Insight icon={Clock} label={run.live ? 'Latest pass' : 'Satellite passes'}
            value={run.live && run.latest_pass ? `${hoursAgo(run.latest_pass)} h ago` : `${insights.passes.length}`}
            sub={run.live ? 'drifted to now' : `${fmtDay(utc(`${insights.passes[0]}T00:00:00`))} – ${fmtDay(utc(`${insights.passes[insights.passes.length - 1]}T00:00:00`))}`} />
        </div>
      )}

      <div className="filters">
        <div className="chips" role="group" aria-label="Filter by priority">
          {TIERS.map((t) => (
            <button key={t} type="button" className={`chip ${tierFilter.has(t) ? 'on' : ''}`} style={{ '--tier': TIER[t].color }}
              aria-pressed={tierFilter.has(t)} onClick={() => toggle(t)}>
              <i aria-hidden="true" />{t}<b>{counts[t]}</b>
            </button>
          ))}
        </div>
        <div className="list-head">
          <span><b>{list.length}</b> of {hs.length} shown</span>
          <label className="sort">
            Sort by
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
      </div>

      <ol className="tickets">
        {list.map((h) => {
          const fc = forecastById[h.id]
          const d = fc && driftSummary(h, fc)
          return (
            <li key={h.id}>
              <button type="button"
                className={`ticket ${selected === h.id ? 'is-active' : ''} ${hovered === h.id ? 'is-hover' : ''}`}
                onMouseEnter={() => setHovered(h.id)} onMouseLeave={() => setHovered(null)} onClick={() => onSelect(h.id)}>
                <span className="tk-rank"><Flag tier={h.risk.tier} /><span>{h.rank}</span></span>
                <span className="tk-main">
                  <span className="tk-top"><b>{h.id}</b><span className="tk-region">{h.region || h.sensor}</span></span>
                  <span className="tk-meta">
                    {d && (
                      <span className="tk-drift" title={`Heading ${d.dir}`}>
                        <ArrowUp size={12} style={{ transform: `rotate(${d.deg}deg)` }} aria-hidden="true" />
                        {Math.round(d.km48)} km {d.dir}
                      </span>
                    )}
                    <span>{Math.round(h.confidence * 100)}% conf</span>
                    {h.nowcast && <span>seen {h.nowcast.age_h} h ago</span>}
                  </span>
                  <span className="tk-site"><MapPin size={11} aria-hidden="true" /> {h.risk.nearest_site}</span>
                </span>
                <span className="tk-score" style={{ '--tier': TIER[h.risk.tier].color, '--tier-ink': TIER[h.risk.tier].ink }}>
                  <b>{Math.round(h.risk.risk_score)}</b><small>risk</small>
                </span>
              </button>
            </li>
          )
        })}
        {!list.length && <li className="empty">No hotspots match these filters.</li>}
      </ol>
    </aside>
  )
}
