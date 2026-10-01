# AquaTrace AI web app

React + Vite + Leaflet map app. It talks to the FastAPI backend at `/api` (proxied to `localhost:8000` in dev).

```bash
npm install
npm run dev      # http://localhost:5173 (start the backend first)
npm run build    # writes dist/, which the backend serves at http://localhost:8000
```

Shareable views via URL parameters: `?run=<run_id>&select=HS-07&hour=24&route=Port%20Blair&stops=4&view=lat,lon,zoom&hide=truecolor,anomaly`.
