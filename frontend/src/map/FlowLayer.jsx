import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import { buildGrid, sampleGrid } from '../lib/geo'

/**
 * Animated streamlines of a velocity field (ocean currents or wind), drawn on a canvas in its own
 * pane between the basemap and the vector layers. Particles move in screen space at a speed
 * proportional to the local velocity, leaving fading trails.
 */
export default function FlowLayer({ field, pane = 'flow', zIndex = 350, color = 'rgba(255,255,255,0.9)',
  count = 2400, width = 1.15, pxPerFrame = 1.5, fade = 0.93, maxAge = 80 }) {
  const map = useMap()

  useEffect(() => {
    const grid = buildGrid(field)
    if (!grid) return undefined
    const host = map.getPane(pane) || map.createPane(pane)
    host.style.zIndex = zIndex
    host.style.pointerEvents = 'none'
    const canvas = L.DomUtil.create('canvas', 'flow-canvas', host)
    const ctx = canvas.getContext('2d')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let W = 0
    let H = 0
    let degPerPx = 0
    let raf = 0
    let hidden = false

    const spawn = (p) => {
      p.lat = grid.lat0 + Math.random() * (grid.lat1 - grid.lat0)
      p.lon = grid.lon0 + Math.random() * (grid.lon1 - grid.lon0)
      p.age = Math.floor(Math.random() * maxAge)
      p.x = null
      return p
    }
    const parts = Array.from({ length: count }, () => spawn({}))
    const place = () => L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
    const clear = () => ctx.clearRect(0, 0, W, H)
    const size = () => {
      const s = map.getSize()
      W = s.x
      H = s.y
      canvas.width = W * dpr
      canvas.height = H * dpr
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      degPerPx = 360 / (256 * 2 ** map.getZoom())
      place()
      parts.forEach((p) => { p.x = null })
    }

    function frame() {
      raf = requestAnimationFrame(frame)
      if (hidden) return
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = `rgba(0,0,0,${fade})`
      ctx.fillRect(0, 0, W, H)
      ctx.globalCompositeOperation = 'source-over'
      ctx.strokeStyle = color
      ctx.lineWidth = width
      ctx.lineCap = 'round'
      ctx.beginPath()
      const s = (pxPerFrame * degPerPx) / grid.median
      for (const p of parts) {
        const vel = sampleGrid(grid, p.lat, p.lon)
        p.age += 1
        if (!vel || p.age > maxAge) { spawn(p); continue }
        if (p.x === null) {
          const a = map.latLngToContainerPoint([p.lat, p.lon])
          p.x = a.x
          p.y = a.y
        }
        // Web Mercator is conformal: a screen pixel spans degPerPx of longitude and degPerPx*cos(lat) of latitude
        p.lon += vel[0] * s
        p.lat += vel[1] * s * Math.cos(p.lat * Math.PI / 180)
        const b = map.latLngToContainerPoint([p.lat, p.lon])
        if (b.x > -5 && b.y > -5 && b.x < W + 5 && b.y < H + 5) {
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(b.x, b.y)
        }
        p.x = b.x
        p.y = b.y
      }
      ctx.stroke()
    }

    const onMove = () => { place(); clear(); parts.forEach((p) => { p.x = null }) }
    const onZoomStart = () => { hidden = true; canvas.style.visibility = 'hidden' }
    const onZoomEnd = () => { size(); clear(); hidden = false; canvas.style.visibility = '' }
    size()
    map.on('move', onMove)
    map.on('zoomstart', onZoomStart)
    map.on('zoomend', onZoomEnd)
    map.on('resize', size)
    if (reduce) {
      // respect reduced-motion: draw a single static frame of short streaks
      for (let i = 0; i < 12; i++) frame()
      cancelAnimationFrame(raf)
    } else {
      frame()
    }
    return () => {
      cancelAnimationFrame(raf)
      map.off('move', onMove)
      map.off('zoomstart', onZoomStart)
      map.off('zoomend', onZoomEnd)
      map.off('resize', size)
      canvas.remove()
    }
  }, [map, field, pane, zIndex, color, count, width, pxPerFrame, fade, maxAge])

  return null
}
