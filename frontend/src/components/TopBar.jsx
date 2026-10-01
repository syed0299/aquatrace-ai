import { ShieldCheck } from 'lucide-react'
import { runLabel, sourceStatus } from '../lib/format'
import { Logo } from './Marks'

export default function TopBar({ runs, runId, setRunId, run, trustOpen, setTrustOpen }) {
  const sources = sourceStatus(run)
  return (
    <header className="topbar">
      <div className="brand">
        <Logo />
        <div>
          <b>AquaTrace</b>
          <span>Bay of Bengal debris watch</span>
        </div>
      </div>

      <nav className="runs" aria-label="Forecast runs">
        {runs.map((r) => {
          const l = runLabel(r)
          return (
            <button key={r.run_id} type="button" className={`run ${r.run_id === runId ? 'on' : ''} ${l.live ? 'is-live' : ''}`}
              onClick={() => setRunId(r.run_id)} aria-pressed={r.run_id === runId}>
              {l.live && <i className="live-dot" aria-hidden="true" />}
              <b>{l.title}</b>
              <span>{l.sub}</span>
            </button>
          )
        })}
      </nav>

      <div className="sources" aria-label="Datasets used in this run">
        {sources.map((s) => (
          <span key={s.name} className={`src ${s.on ? 'on' : ''}`} title={`${s.title}${s.on ? '' : ' (not used in this run)'}`}>
            <i aria-hidden="true" />{s.name}
          </span>
        ))}
      </div>

      <button type="button" className={`trust-btn ${trustOpen ? 'on' : ''}`} onClick={() => setTrustOpen(!trustOpen)}
        aria-expanded={trustOpen}>
        <ShieldCheck size={16} aria-hidden="true" /><span>Model trust</span>
      </button>
    </header>
  )
}
