import { useMemo } from 'react'
import { Pause, Play } from 'lucide-react'
import { fmtIST } from '../lib/format'

const TICKS = [0, 6, 12, 18, 24, 30, 36, 42, 48]

/** Night-time bands (18:00-06:00 IST): cleanup crews work in daylight. */
function nightBands(start) {
  if (!start) return []
  const bands = []
  let open = null
  for (let h = 0; h <= 48; h += 0.25) {
    const d = new Date(start.getTime() + h * 3600e3)
    const ist = (d.getUTCHours() + d.getUTCMinutes() / 60 + 5.5) % 24
    const night = ist < 6 || ist >= 18
    if (night && open === null) open = h
    if ((!night || h === 48) && open !== null) { bands.push([open, h]); open = null }
  }
  return bands
}

export default function Timeline({ hour, setHour, playing, setPlaying, speed, setSpeed, start, live }) {
  const bands = useMemo(() => nightBands(start), [start])
  const when = start ? new Date(start.getTime() + hour * 3600e3) : null
  const label = hour === 0 ? (live ? 'Now' : 'Satellite pass') : `+${Number.isInteger(hour) ? hour : hour.toFixed(1)} h`
  return (
    <div className="timeline" role="group" aria-label="Forecast time">
      <button type="button" className="tl-play" onClick={() => setPlaying(!playing)} aria-label={playing ? 'Pause' : 'Play'}>
        {playing ? <Pause size={18} /> : <Play size={18} />}
      </button>
      <div className="tl-read">
        <b>{label}</b>
        <span>{when ? fmtIST(when) : playing ? 'after each satellite pass' : 'press Space to play 48 h'}</span>
      </div>
      <div className="tl-track">
        <div className="tl-rail">
          {bands.map(([a, b]) => (
            <i key={a} className="tl-night" style={{ left: `${(a / 48) * 100}%`, width: `${((b - a) / 48) * 100}%` }} title="Night (IST)" />
          ))}
          <div className="tl-fill" style={{ width: `${(hour / 48) * 100}%` }} />
        </div>
        <input type="range" min={0} max={48} step={0.25} value={hour} aria-label="Forecast hour"
          onChange={(e) => { setPlaying(false); setHour(Number(e.target.value)) }} />
        <div className="tl-ticks" aria-hidden="true">
          {TICKS.map((t) => (
            <span key={t} style={{ left: `${(t / 48) * 100}%` }}>{t === 0 ? (live ? 'now' : 'pass') : `+${t}h`}</span>
          ))}
        </div>
      </div>
      <button type="button" className="tl-speed" onClick={() => setSpeed(speed === 4 ? 1 : speed * 2)}
        aria-label={`Playback speed ${speed}x`}>{speed}×</button>
    </div>
  )
}
