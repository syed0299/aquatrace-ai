import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import { particlesAt } from '../lib/geo'

/**
 * Drift-ensemble particles for every visible hotspot at a fractional forecast hour, drawn on one
 * canvas (thousands of DOM circles would make the time slider stutter).
 * items: [{ fc, color, strong }]
 */
export default function ParticleLayer({ items, hour }) {
  const map = useMap()
  const latest = useRef({ items, hour })
  const redraw = useRef(() => {})
  latest.current = { items, hour }

  useEffect(() => {
    const host = map.getPane('drift') || map.createPane('drift')
    host.style.zIndex = 450
    host.style.pointerEvents = 'none'
    const canvas = L.DomUtil.create('canvas', 'drift-canvas', host)
    const ctx = canvas.getContext('2d')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let W = 0
    let H = 0

    const draw = () => {
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      ctx.clearRect(0, 0, W, H)
      const { items: its, hour: h } = latest.current
      for (const it of its) {
        const pts = particlesAt(it.fc.frames, h)
        ctx.fillStyle = it.color
        ctx.globalAlpha = it.strong ? 0.95 : 0.7
        for (const p of pts) {
          const c = map.latLngToContainerPoint([p[0], p[1]])
          if (c.x < -4 || c.y < -4 || c.x > W + 4 || c.y > H + 4) continue
          ctx.beginPath()
          ctx.arc(c.x, c.y, p[2] ? 3.2 : it.strong ? 2.6 : 2.1, 0, Math.PI * 2)
          ctx.fill()
          if (p[2]) {
            ctx.strokeStyle = '#fff'
            ctx.lineWidth = 1.2
            ctx.stroke()
          }
        }
      }
      ctx.globalAlpha = 1
    }
    const size = () => {
      const s = map.getSize()
      W = s.x
      H = s.y
      canvas.width = W * dpr
      canvas.height = H * dpr
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      draw()
    }
    const hide = () => { canvas.style.visibility = 'hidden' }
    const show = () => { canvas.style.visibility = ''; draw() }
    redraw.current = draw
    size()
    map.on('move', draw)
    map.on('zoomstart', hide)
    map.on('zoomend', show)
    map.on('resize', size)
    return () => {
      map.off('move', draw)
      map.off('zoomstart', hide)
      map.off('zoomend', show)
      map.off('resize', size)
      canvas.remove()
    }
  }, [map])

  useEffect(() => { redraw.current() }, [items, hour])
  return null
}
