// Shared colours, geometry and interpolation helpers for the map and panels.

// Risk tiers use the international maritime signal-flag palette.
export const TIER = {
  High: { color: '#E5383B', soft: '#FDE8E8', ink: '#8C1C1E' },
  Medium: { color: '#F5A30B', soft: '#FEF3D7', ink: '#7A4A00' },
  Low: { color: '#16A36A', soft: '#DFF5EA', ink: '#0B5A39' },
}
export const WHATIF = '#2453FF'
export const BACKTRACK = '#7C3AED'
export const INK = '#0B1F3A'

const RAD = Math.PI / 180
const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']

export function bearing(lat1, lon1, lat2, lon2) {
  const y = Math.sin((lon2 - lon1) * RAD) * Math.cos(lat2 * RAD)
  const x = Math.cos(lat1 * RAD) * Math.sin(lat2 * RAD)
    - Math.sin(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos((lon2 - lon1) * RAD)
  return (Math.atan2(y, x) / RAD + 360) % 360
}

export const compass = (deg) => DIRS[Math.round(deg / 45) % 8]

/** Position on a [hour, lat, lon] track at a fractional hour. */
export function trackAt(track, h) {
  if (!track?.length) return null
  if (h <= track[0][0]) return [track[0][1], track[0][2]]
  for (let i = 1; i < track.length; i++) {
    if (h <= track[i][0]) {
      const [h0, a0, b0] = track[i - 1]
      const [h1, a1, b1] = track[i]
      const f = (h - h0) / (h1 - h0 || 1)
      return [a0 + f * (a1 - a0), b0 + f * (b1 - b0)]
    }
  }
  const last = track[track.length - 1]
  return [last[1], last[2]]
}

/** Track positions from the start up to a fractional hour (smooth end point). */
export function trackUpTo(track, h) {
  if (!track?.length) return []
  const pts = track.filter((p) => p[0] <= h).map((p) => [p[1], p[2]])
  const end = trackAt(track, h)
  if (end) pts.push(end)
  return pts
}

/** Particle positions at a fractional hour, interpolated between the 3-hourly frames. */
export function particlesAt(frames, h) {
  if (!frames?.length) return []
  let i = 0
  while (i < frames.length - 1 && frames[i + 1].h <= h) i++
  const a = frames[i]
  const b = frames[Math.min(i + 1, frames.length - 1)]
  if (a === b || b.h === a.h) return a.p
  const f = Math.min(1, Math.max(0, (h - a.h) / (b.h - a.h)))
  return a.p.map((p, k) => {
    const q = b.p[k] || p
    return [p[0] + f * (q[0] - p[0]), p[1] + f * (q[1] - p[1]), f < 0.5 ? p[2] : q[2]]
  })
}

/** Regular grid from the run's scattered {lat, lon, u, v} samples, for fast bilinear lookups. */
export function buildGrid(points) {
  if (!points?.length) return null
  const lats = [...new Set(points.map((p) => p.lat))].sort((a, b) => a - b)
  const lons = [...new Set(points.map((p) => p.lon))].sort((a, b) => a - b)
  const step = (arr) => {
    let m = Infinity
    for (let i = 1; i < arr.length; i++) m = Math.min(m, arr[i] - arr[i - 1])
    return Number.isFinite(m) ? m : 1
  }
  const dlat = step(lats)
  const dlon = step(lons)
  const lat0 = lats[0]
  const lon0 = lons[0]
  const nlat = Math.round((lats[lats.length - 1] - lat0) / dlat) + 1
  const nlon = Math.round((lons[lons.length - 1] - lon0) / dlon) + 1
  const u = new Float32Array(nlat * nlon).fill(NaN)
  const v = new Float32Array(nlat * nlon).fill(NaN)
  for (const p of points) {
    const k = Math.round((p.lat - lat0) / dlat) * nlon + Math.round((p.lon - lon0) / dlon)
    u[k] = p.u
    v[k] = p.v
  }
  const speeds = points.map((p) => Math.hypot(p.u, p.v)).sort((a, b) => a - b)
  return {
    lat0, lon0, dlat, dlon, nlat, nlon, u, v,
    lat1: lat0 + (nlat - 1) * dlat,
    lon1: lon0 + (nlon - 1) * dlon,
    median: Math.max(speeds[Math.floor(speeds.length / 2)] || 0.1, 0.02),
  }
}

/** Bilinear [u, v] at a point; null over land or outside the grid. */
export function sampleGrid(g, lat, lon) {
  const fi = (lat - g.lat0) / g.dlat
  const fj = (lon - g.lon0) / g.dlon
  const i0 = Math.floor(fi)
  const j0 = Math.floor(fj)
  if (i0 < 0 || j0 < 0 || i0 >= g.nlat - 1 || j0 >= g.nlon - 1) return null
  const di = fi - i0
  const dj = fj - j0
  let su = 0
  let sv = 0
  let sw = 0
  const add = (k, w) => {
    const uu = g.u[k]
    if (!Number.isNaN(uu)) { su += w * uu; sv += w * g.v[k]; sw += w }
  }
  const k = i0 * g.nlon + j0
  add(k, (1 - di) * (1 - dj))
  add(k + 1, (1 - di) * dj)
  add(k + g.nlon, di * (1 - dj))
  add(k + g.nlon + 1, di * dj)
  return sw > 0.35 ? [su / sw, sv / sw] : null
}

/** Simple summaries used by the briefing and the detail drawer. */
export function driftSummary(h, fc) {
  const m48 = fc.horizons['48'].mean
  const deg = bearing(h.lat, h.lon, m48[0], m48[1])
  return { deg, dir: compass(deg), km48: fc.horizons['48'].displacement_km, km24: fc.horizons['24'].displacement_km }
}
