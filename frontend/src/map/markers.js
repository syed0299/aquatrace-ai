import L from 'leaflet'

const cache = new Map()
const memo = (key, make) => {
  if (!cache.has(key)) cache.set(key, make())
  return cache.get(key)
}

/** Numbered hotspot pin; high and medium tiers pulse. */
export const hotspotIcon = (rank, tier, active, hover) => memo(`hs|${rank}|${tier}|${active}|${hover}`, () => L.divIcon({
  className: 'pin-icon',
  iconSize: [36, 36],
  iconAnchor: [18, 18],
  html: `<div class="hs-pin t-${tier.toLowerCase()}${active ? ' is-active' : ''}${hover ? ' is-hover' : ''}">`
    + `${tier !== 'Low' || active ? '<span class="hs-pulse"></span>' : ''}<span class="hs-dot">${rank}</span></div>`,
}))

export const stopIcon = (n) => memo(`stop|${n}`, () => L.divIcon({
  className: 'pin-icon', iconSize: [26, 26], iconAnchor: [13, 13],
  html: `<div class="stop-pin">${n}</div>`,
}))

const ANCHOR = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2"/><path d="M12 7v14M5 13H3a9 9 0 0 0 18 0h-2"/></svg>'
export const portIcon = () => memo('port', () => L.divIcon({
  className: 'pin-icon', iconSize: [30, 30], iconAnchor: [15, 15],
  html: `<div class="port-pin">${ANCHOR}</div>`,
}))

export const whatIfIcon = () => memo('whatif', () => L.divIcon({
  className: 'pin-icon', iconSize: [36, 36], iconAnchor: [18, 18],
  html: '<div class="hs-pin t-whatif is-active"><span class="hs-pulse"></span><span class="hs-dot">?</span></div>',
}))
