# Soony — Launch Control Room

Frontend prototype for the Grand Heist 6 launch control room (T6).

## Run

```bash
cd web
npm install
npm run dev
```

Open the local URL printed by Vite.

For a production build:

```bash
npm run build
npm run preview
```

The UI currently loads mock data from `src/mock/dashboard.json`. `src/api.ts` defines the `DashboardApi` contract and a mock implementation that can later be replaced by HTTP/WebSocket-backed calls.
