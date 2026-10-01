async function get(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  runs: () => get('/api/runs'),
  run: (id) => get(`/api/runs/${id}`),
  metrics: () => get('/api/metrics'),
  file: (id, path) => `/api/runs/${id}/files/${path}`,
  ports: () => get('/api/ports'),
  route: (id, p) => get(`/api/runs/${id}/route?${new URLSearchParams(p)}`),
  forecast: async (body) => {
    const r = await fetch('/api/forecast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (!r.ok) throw new Error(j.detail?.[0]?.msg || j.detail || 'Forecast failed')
    return j
  },
}
