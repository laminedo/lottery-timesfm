# Web app

Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts. See the [project README](../README.md).

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api to the backend on :8000
npm run typecheck && npm run lint && npm test
```

Set `API_URL` to point the `/api` proxy at a backend that is not on `http://127.0.0.1:8000`.
