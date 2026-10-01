// Formatting helpers. Data timestamps are UTC; people in the room think in IST.

const ist = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  hour12: false,
})
const istDay = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' })

export const utc = (iso) => new Date(Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`))
export const fmtIST = (d) => `${ist.format(d)} IST`
export const fmtDay = (d) => istDay.format(d)
export const hoursAgo = (iso) => Math.max(0, Math.round((Date.now() - utc(iso).getTime()) / 3600e3))
export const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`
export const coord = (lat, lon) => `${Math.abs(lat).toFixed(3)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(lon).toFixed(3)}°${lon >= 0 ? 'E' : 'W'}`

export function runLabel(r) {
  if (r.run_id.startsWith('live_')) {
    const s = r.run_id.slice(5) // YYYYMMDD_HHMM
    const d = new Date(Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(9, 11), +s.slice(11, 13)))
    return { live: true, title: 'Live', sub: fmtIST(d).replace(/^\w+, /, '') }
  }
  return { live: false, title: 'Replay', sub: fmtDay(new Date(`${r.date}T00:00:00Z`)) }
}

/** Which datasets a run used (shown as status chips in the top bar). */
export function sourceStatus(run) {
  if (!run) return []
  const det = run.sources.detection || ''
  const cur = run.sources.currents?.source || ''
  const wind = run.sources.wind?.source || ''
  return [
    { name: 'PACE', on: det.includes('PACE'), title: 'NASA PACE OCI hyperspectral imagery' },
    { name: 'Sentinel-2', on: det.includes('Sentinel-2'), title: 'ESA Sentinel-2 coastal imagery' },
    { name: 'OSCAR', on: cur.includes('OSCAR'), title: 'NASA OSCAR v2.0 surface currents' },
    { name: 'MERRA-2', on: wind.includes('MERRA-2'), title: 'NASA MERRA-2 10 m wind' },
    { name: 'Forecast', on: cur.includes('Open-Meteo') || wind.includes('Open-Meteo'), title: 'Open-Meteo ocean + wind forecasts (live runs)' },
  ]
}
