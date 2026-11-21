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

The UI reads `/api/dashboard`. During development Vite proxies `/api` to the orchestrator at `http://127.0.0.1:8787`. Add `?mock=1` for the prototype fixture or `?static=1` to exercise the sample replay controls. The [team Vercel replay](../deploy/vercel/README.md) uses the same UI with case-backed forecasts and a password gate.
