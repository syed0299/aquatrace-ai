import { Fragment, useEffect, useMemo } from 'react'
import {
  CircleMarker, ImageOverlay, MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../api'
import { BACKTRACK, INK, TIER, WHATIF, trackUpTo } from '../lib/geo'
import FlowLayer from './FlowLayer'
import ParticleLayer from './ParticleLayer'
import { hotspotIcon, portIcon, stopIcon, whatIfIcon } from './markers'

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
const ATTR = 'Tiles &copy; Esri, GEBCO, NOAA, Garmin, HERE'
const BASEMAPS = {
  ocean: [`${ESRI}/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}`, `${ESRI}/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}`, 13],
  satellite: [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, 17],
  dark: [`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, 16],
}
export const HOME = { center: [15.4, 87.2], zoom: 6 }
// optional initial view from the URL: ?view=lat,lon,zoom
const VIEW = new URLSearchParams(window.location.search).get('view')?.split(',').map(Number)

function Basemap({ kind }) {
  const [base, ref, maxNative] = BASEMAPS[kind] || BASEMAPS.ocean
  return (
    <>
      <TileLayer key={`b-${kind}`} url={base} attribution={ATTR} maxNativeZoom={maxNative} />
      <TileLayer key={`r-${kind}`} url={ref} maxNativeZoom={maxNative} zIndex={2} />
    </>
  )
}

function Events({ onClick }) {
  useMapEvents({ click: (e) => onClick(e.latlng.lat, e.latlng.lng) })
  return null
}

/** Frame the selected hotspot and its 48 h forecast, leaving room for the detail drawer. */
function Focus({ hotspot, fc }) {
  const map = useMap()
  useEffect(() => {
    if (!hotspot) return
    const pts = [[hotspot.lat, hotspot.lon]]
    if (fc) pts.push(fc.horizons['48'].mean, ...fc.horizons['48'].hull)
    if (hotspot.detected) pts.push([hotspot.detected.lat, hotspot.detected.lon])
    const b = L.latLngBounds(pts).pad(0.25)
    map.flyToBounds(b, { paddingTopLeft: [60, 60], paddingBottomRight: [480, 190], maxZoom: 8, duration: 0.9 })
  }, [hotspot, fc, map])
  return null
}

function Forecast({ fc, color, hour, cones, strong, onSelect }) {
  const full = useMemo(() => fc.central_track.map((p) => [p[1], p[2]]), [fc])
  const upto = trackUpTo(fc.central_track, hour)
  return (
    <>
      {cones && ['48', '24'].map((h) => fc.horizons[h] && (
        <Polygon key={h} positions={fc.horizons[h].hull} eventHandlers={{ click: onSelect }}
          pathOptions={{
            color, weight: strong ? 1.6 : 1, opacity: strong ? 0.9 : 0.55, dashArray: h === '48' ? '5 5' : null,
            fillColor: color, fillOpacity: strong ? (h === '24' ? 0.2 : 0.12) : 0.07,
          }}>
          <Tooltip sticky className="tt">{fc.id} · +{h} h cone · spread ±{fc.horizons[h].spread_km} km</Tooltip>
        </Polygon>
      ))}
      <Polyline positions={full} interactive={false}
        pathOptions={{ color, weight: 1.5, opacity: strong ? 0.6 : 0.35, dashArray: '2 6' }} />
      <Polyline positions={upto} interactive={false}
        pathOptions={{ color: '#fff', weight: strong ? 7 : 5, opacity: 0.85 }} />
      <Polyline positions={upto} interactive={false} pathOptions={{ color, weight: strong ? 4 : 2.5, opacity: 1 }} />
      {fc.beach_points.length > 0 && hour >= (fc.first_beaching_h ?? 99) && fc.beach_points.slice(0, 40).map((p, i) => (
        <CircleMarker key={i} center={p} radius={3} interactive={false}
          pathOptions={{ color: '#fff', weight: 1, fillColor: color, fillOpacity: 1 }} />
      ))}
    </>
  )
}

function RouteLayer({ route, onSelect }) {
  if (!route?.stops?.length) return null
  const port = [route.port.lat, route.port.lon]
  const path = [port]
  route.stops.forEach((s) => { s.via.forEach((w) => path.push(w)); path.push([s.lat, s.lon]) })
  route.return_via?.forEach((w) => path.push(w))
  path.push(port)
  return (
    <>
      <Polyline positions={path} interactive={false} pathOptions={{ color: '#fff', weight: 9, opacity: 0.9 }} />
      <Polyline positions={path} interactive={false} pathOptions={{ color: INK, weight: 4, opacity: 1, dashArray: '10 6' }} />
      <Marker position={port} icon={portIcon()}>
        <Tooltip direction="top" offset={[0, -14]} className="tt">Depart {route.port.name}</Tooltip>
      </Marker>
      {route.stops.map((s, i) => (
        <Fragment key={s.id}>
          <Polyline positions={[s.seen_at, [s.lat, s.lon]]} interactive={false}
            pathOptions={{ color: INK, weight: 1.2, dashArray: '2 4', opacity: 0.8 }} />
          <Marker position={[s.lat, s.lon]} icon={stopIcon(i + 1)} eventHandlers={{ click: () => onSelect(s.id) }}>
            <Tooltip direction="right" offset={[12, 0]} className="tt">
              Stop {i + 1} · {s.id} · arrive +{s.arrive_h} h · drifted {s.drift_since_seen_km} km
            </Tooltip>
          </Marker>
        </Fragment>
      ))}
    </>
  )
}

export default function MapView({
  run, runId, hour, layers, basemap, selected, hovered, setHovered, onSelect, visible, forecastById,
  whatIf, whatIfMode, onMapClick, route, mapRef,
}) {
  const hs = run?.hotspots || []
  const sel = hs.find((h) => h.id === selected)
  const shown = hs.filter((h) => visible.has(h.id))
  const particleItems = useMemo(() => {
    const items = shown.map((h) => ({
      fc: forecastById[h.id], color: TIER[h.risk.tier].color, strong: h.id === selected || h.id === hovered,
    })).filter((x) => x.fc)
    if (whatIf) items.push({ fc: whatIf.forecast, color: WHATIF, strong: true })
    return items
  }, [shown, forecastById, selected, hovered, whatIf])

  return (
    <div className={`map ${whatIfMode ? 'crosshair' : ''}`}>
      <MapContainer ref={mapRef} center={VIEW ? [VIEW[0], VIEW[1]] : HOME.center} zoom={VIEW ? VIEW[2] : HOME.zoom}
        minZoom={4} maxZoom={14} preferCanvas zoomControl={false} worldCopyJump
        style={{ height: '100%', width: '100%' }}>
        <Basemap kind={basemap} />
        <Events onClick={onMapClick} />
        <Focus hotspot={sel} fc={sel && forecastById[sel.id]} />

        {run && layers.satellite && run.overlays.map((o) => (
          <ImageOverlay key={`t${o.truecolor}`} url={api.file(runId, o.truecolor)} bounds={o.bounds} opacity={0.85} />
        ))}
        {run && layers.anomaly && run.overlays.map((o) => (
          <ImageOverlay key={`a${o.anomaly}`} url={api.file(runId, o.anomaly)} bounds={o.bounds} opacity={0.75} />
        ))}
        {run && layers.currents && (
          <FlowLayer key={`cur-${runId}-${basemap}`} field={run.fields.currents}
            color={basemap === 'ocean' ? 'rgba(255,255,255,0.95)' : 'rgba(150,225,255,0.85)'} count={3000} width={1.3} />
        )}
        {run && layers.wind && (
          <FlowLayer key={`wind-${runId}`} pane="windflow" zIndex={355} field={run.fields.wind}
            color="rgba(255,196,64,0.85)" count={1400} pxPerFrame={2.4} width={1} />
        )}

        {run && layers.sites && run.sites.map((s) => (
          <CircleMarker key={s.name} center={[s.lat, s.lon]} radius={5}
            pathOptions={{ color: INK, weight: 1.6, fillColor: '#fff', fillOpacity: 1 }}>
            <Tooltip className="tt"><b>{s.name}</b><br />{s.type}</Tooltip>
          </CircleMarker>
        ))}

        {shown.map((h) => {
          const fc = forecastById[h.id]
          const strong = h.id === selected || h.id === hovered
          return fc && (
            <Fragment key={`f-${h.id}`}>
              {h.detected && h.nowcast?.track?.length > 1 && (
                <>
                  <Polyline positions={h.nowcast.track} interactive={false}
                    pathOptions={{ color: INK, weight: 1.6, opacity: 0.7, dashArray: '1 6', lineCap: 'round' }} />
                  <CircleMarker center={[h.detected.lat, h.detected.lon]} radius={6}
                    pathOptions={{ color: INK, weight: 1.6, fillOpacity: 0, dashArray: '2 3' }}>
                    <Tooltip className="tt">Satellite saw {h.id} here · drifted {h.nowcast.age_h} h since</Tooltip>
                  </CircleMarker>
                </>
              )}
              <Forecast fc={fc} color={TIER[h.risk.tier].color} hour={hour} cones={layers.cones}
                strong={strong} onSelect={() => onSelect(h.id)} />
            </Fragment>
          )
        })}

        {sel?.source?.track?.length > 1 && (
          <>
            <Polyline positions={sel.source.track} interactive={false}
              pathOptions={{ color: BACKTRACK, weight: 2.5, dashArray: '6 6', opacity: 0.95 }} />
            <CircleMarker center={sel.source.origin} radius={6}
              pathOptions={{ color: '#fff', weight: 2, fillColor: BACKTRACK, fillOpacity: 1 }}>
              <Tooltip className="tt" permanent direction="left" offset={[-8, 0]}>{sel.source.hours} h earlier</Tooltip>
            </CircleMarker>
          </>
        )}

        {layers.particles && <ParticleLayer items={particleItems} hour={hour} />}

        {whatIf && (
          <>
            <Forecast fc={whatIf.forecast} color={WHATIF} hour={hour} cones={layers.cones} strong onSelect={() => onSelect('USER')} />
            <Marker position={[whatIf.lat, whatIf.lon]} icon={whatIfIcon()} eventHandlers={{ click: () => onSelect('USER') }}>
              <Tooltip direction="top" offset={[0, -16]} className="tt">What-if release</Tooltip>
            </Marker>
          </>
        )}

        <RouteLayer route={route} onSelect={onSelect} />

        {shown.map((h) => (
          <Marker key={`m-${h.id}`} position={[h.lat, h.lon]}
            icon={hotspotIcon(h.rank, h.risk.tier, h.id === selected, h.id === hovered)}
            zIndexOffset={h.id === selected ? 1000 : h.id === hovered ? 900 : 100 - h.rank}
            eventHandlers={{ click: () => onSelect(h.id), mouseover: () => setHovered(h.id), mouseout: () => setHovered(null) }}>
            <Tooltip direction="top" offset={[0, -16]} className="tt">
              <b>{h.id}</b> · {h.risk.tier} · risk {Math.round(h.risk.risk_score)}
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
