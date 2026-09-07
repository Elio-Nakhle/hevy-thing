# Frontend

Nuxt 4 UI for [hevy-thing](../README.md): dashboard, strength standards, per-exercise
history, and the coach chat.

```bash
npm install
npm run dev        # http://localhost:3000
```

It expects the backend on `http://127.0.0.1:8000` (`cd ../backend && uv run
hevy-coach serve`). Point `NUXT_PUBLIC_API_BASE` elsewhere if you moved it -
note that the `/api` proxy target is read at build time, so a change needs a
rebuild, not just a restart.

```bash
npm run typecheck  # vue-tsc across pages, components and composables
npm run build
```

## Notes

- **No UI framework and no chart library.** The charts are hand-written SVG
  components (`LineChart`, `ColumnChart`, `MuscleVolumeChart`, `StandardsRow`);
  styling is plain CSS with custom properties in `app/assets/css/main.css`,
  themed light/dark from one token set.
- **`/api` is a proxy**, configured in `nuxt.config.ts`, so the browser makes
  same-origin requests. Because it is a proxy, Nuxt cannot infer response types -
  hence `app/types/api.ts`, which mirrors the backend dataclasses and is passed
  as the `useFetch` generic. Without it every response types as `{}` and
  typechecking silently does nothing.
- **Weights arrive in kilograms** and are converted for display by `useUnits()`,
  at the display boundary only. Never convert a value on its way into a
  calculation - ratios and level scores are unit-free.
