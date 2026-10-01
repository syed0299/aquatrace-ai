import { TIER } from '../lib/geo'

/** Brand mark: a drifting debris dot leaving a dashed trail over a wave. */
export function Logo({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#0B1F3A" />
      <path d="M5 20.5c3.2-3.6 6.4-3.6 9.6 0s6.4 3.6 9.6 0" stroke="#5EC8FF" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      <path d="M7.5 13.5c2.6-2.4 6-3 9.4-1.6" stroke="#fff" strokeWidth="1.6" fill="none" strokeDasharray="0.1 3.2" strokeLinecap="round" />
      <circle cx="21.5" cy="11.5" r="3.3" fill="#FF5A36" />
    </svg>
  )
}

/** Swallow-tail pennant in the tier colour (maritime signal-flag motif). */
export function Flag({ tier, size = 16 }) {
  const t = TIER[tier] || { color: '#2453FF' }
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="flag">
      <path d="M2.5 1.5v13" stroke="#0B1F3A" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M3.2 2.2h10.3l-3 3.6 3 3.6H3.2z" fill={t.color} />
    </svg>
  )
}

/** Semicircular 0-100 gauge. */
export function Gauge({ value, color }) {
  const len = Math.PI * 52
  return (
    <svg viewBox="0 0 120 70" className="gauge" role="img" aria-label={`Risk score ${Math.round(value)} of 100`}>
      <path d="M8 62 A52 52 0 0 1 112 62" stroke="var(--line)" strokeWidth="10" fill="none" strokeLinecap="round" />
      <path d="M8 62 A52 52 0 0 1 112 62" stroke={color} strokeWidth="10" fill="none" strokeLinecap="round"
        strokeDasharray={`${(len * Math.min(100, value)) / 100} ${len}`} className="gauge-arc" />
      <text x="60" y="55" textAnchor="middle" className="gauge-num">{Math.round(value)}</text>
      <text x="60" y="68" textAnchor="middle" className="gauge-cap">of 100</text>
    </svg>
  )
}

/** Compass rose with an arrow pointing where the patch is heading. */
export function Compass({ deg, color }) {
  return (
    <svg viewBox="0 0 64 64" className="compass" role="img" aria-label={`Heading ${Math.round(deg)} degrees`}>
      <circle cx="32" cy="32" r="29" fill="var(--mist)" stroke="var(--line)" />
      {[0, 90, 180, 270].map((a) => (
        <line key={a} x1="32" y1="5" x2="32" y2="10" stroke="var(--ink-3)" strokeWidth="1.5" transform={`rotate(${a} 32 32)`} />
      ))}
      <text x="32" y="17" textAnchor="middle" className="compass-n">N</text>
      <g transform={`rotate(${deg} 32 32)`} className="compass-needle">
        <path d="M32 12 L38.5 36 L32 31.5 L25.5 36 Z" fill={color} />
        <circle cx="32" cy="32" r="2.4" fill="#0B1F3A" />
      </g>
    </svg>
  )
}

/** Reliability diagram: stated confidence vs observed frequency. */
export function Reliability({ cal }) {
  if (!cal) return null
  const W = 220
  const H = 150
  const p = 26
  const x = (v) => p + v * (W - p - 10)
  const y = (v) => H - p - v * (H - p - 10)
  const pts = cal.curve.filter((c) => c.n >= 20)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="reliability" role="img" aria-label="Reliability diagram">
      {[0, 0.5, 1].map((t) => (
        <g key={t}>
          <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke="var(--line)" />
          <text x={p - 6} y={y(t) + 3} textAnchor="end" className="axis">{t * 100}</text>
          <text x={x(t)} y={H - 8} textAnchor="middle" className="axis">{t * 100}</text>
        </g>
      ))}
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--ink-3)" strokeDasharray="3 3" />
      <polyline fill="none" stroke="var(--signal)" strokeWidth="2.5" points={pts.map((c) => `${x(c.confidence)},${y(c.observed)}`).join(' ')} />
      {pts.map((c, i) => <circle key={i} cx={x(c.confidence)} cy={y(c.observed)} r="3.2" fill="var(--signal)" />)}
    </svg>
  )
}
