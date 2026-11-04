# AI Job Interview Simulator: frontend

React + TypeScript + Vite single-page app for the FastAPI backend in `../backend`.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to http://localhost:8000
npm test           # unit, component, integration and journey tests
npm run typecheck && npm run lint && npm run format:check
npm run build
```

Configuration is documented in [`.env.example`](.env.example). Architecture, screens, session handling, accessibility and testing notes: [../docs/FRONTEND.md](../docs/FRONTEND.md).
