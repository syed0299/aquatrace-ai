import { CircleDashed, Crosshair, Flame, LocateFixed, MapPin, Satellite, Ship, Sparkles, Waves, Wind } from 'lucide-react'

const BASEMAPS = [['ocean', 'Ocean'], ['satellite', 'Satellite'], ['dark', 'Night']]
const LAYERS = [
  ['currents', Waves, 'Current flow'],
  ['wind', Wind, 'Wind flow'],
  ['anomaly', Flame, 'Debris signal'],
  ['satellite', Satellite, 'Satellite image'],
  ['cones', CircleDashed, 'Uncertainty cones'],
  ['particles', Sparkles, 'Drift particles'],
  ['sites', MapPin, 'Sensitive sites'],
]

function ToolButton({ on, onClick, label, children }) {
  return (
    <button type="button" className={`tb-btn ${on ? 'on' : ''}`} onClick={onClick} aria-pressed={on} aria-label={label}>
      {children}
      <span className="tb-tip" aria-hidden="true">{label}</span>
    </button>
  )
}

export default function Toolbar({ basemap, setBasemap, layers, setLayers, whatIfMode, setWhatIfMode, routeOpen, setRouteOpen, onHome }) {
  return (
    <div className="toolbar">
      <div className="tb-seg" role="group" aria-label="Basemap">
        {BASEMAPS.map(([k, label]) => (
          <button key={k} type="button" className={basemap === k ? 'on' : ''} onClick={() => setBasemap(k)} aria-pressed={basemap === k}>{label}</button>
        ))}
      </div>
      <div className="tb-col" role="group" aria-label="Map layers">
        {LAYERS.map(([k, Icon, label]) => (
          <ToolButton key={k} on={layers[k]} label={label} onClick={() => setLayers({ ...layers, [k]: !layers[k] })}>
            <Icon size={18} aria-hidden="true" />
          </ToolButton>
        ))}
      </div>
      <div className="tb-col" role="group" aria-label="Tools">
        <ToolButton on={whatIfMode} label="What-if: drop debris anywhere" onClick={() => setWhatIfMode(!whatIfMode)}>
          <Crosshair size={18} aria-hidden="true" />
        </ToolButton>
        <ToolButton on={routeOpen} label="Plan cleanup route" onClick={() => setRouteOpen(!routeOpen)}>
          <Ship size={18} aria-hidden="true" />
        </ToolButton>
        <ToolButton on={false} label="Back to the whole Bay" onClick={onHome}>
          <LocateFixed size={18} aria-hidden="true" />
        </ToolButton>
      </div>
    </div>
  )
}
