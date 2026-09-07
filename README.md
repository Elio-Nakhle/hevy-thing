# hevy-thing

Training analytics, strength-standard benchmarking and an AI coach, built on the
CSV export from [Hevy](https://www.hevyapp.com/).

A Python backend reads the export into SQLite, computes the analytics, and
serves them to a Nuxt frontend and a CLI. Everything runs locally against your
own data.

```
workouts/*.csv  ->  SQLite  ->  analytics  ->  FastAPI  ->  Nuxt
                                          \->  CLI
                                          \->  Claude (coach)
```

## What it does

- **Volume and frequency** - weekly tonnage, sets, sessions, and a per-muscle
  breakdown that counts secondary muscles as half a set.
- **Progression** - per-exercise e1RM trend fits that classify each lift as
  progressing, maintaining, stalling or regressing.
- **Strength standards** - every lift scored against
  [strengthlevel.com](https://strengthlevel.com)'s bodyweight-adjusted tables
  (73 lifts), interpolated to your exact bodyweight and adjusted for age, with a
  continuous 0-4 level score rather than a bucket.
- **Findings** - rule-based insights: stalls, regressions, dormant lifts, low
  weekly volume, and lifts that lag their own variations by a full level.
- **Coach** - Claude with read-only tools over the log, so answers come from
  your actual numbers.

## Getting your data in

The developer API needs a Hevy Pro subscription; the CSV export does not, so
that is what this reads.

1. In the Hevy app: **Profile -> Settings -> Export Data**. You get a CSV by
   email.
2. Drop it in [`workouts/`](workouts/). Any filename works.
3. Import it - the **newest CSV in the folder** is the one that gets read:

   ```bash
   cd backend && uv run hevy-coach import
   ```

Re-importing is safe: workout identity is derived from the start time, so an
updated export updates rows rather than duplicating them. An export is your
complete history, so workouts it no longer contains are removed to match
(`--no-prune` to keep them).

No export to hand? `uv run hevy-coach demo` seeds a synthetic log.

## Setup

```bash
cp .env.example .env      # then set your bodyweight, sex and birth date
cd backend && uv sync
cd ../frontend && npm install
```

`.env` is read from the repository root. The only setting you really need is
your bodyweight - it places every lift on the standards curves.

## Running it

```bash
cd backend  && uv run hevy-coach serve      # API on :8000
cd frontend && npm run dev                  # UI  on :3000
```

The frontend proxies `/api` to the backend, so the browser makes same-origin
requests and there is no CORS preflight.

## CLI

```bash
uv run hevy-coach import        # read the newest export in workouts/
uv run hevy-coach status        # what is in the local database
uv run hevy-coach benchmark     # every lift against the standards
uv run hevy-coach trends        # e1RM trend per exercise
uv run hevy-coach insights      # stalls, regressions, volume gaps
uv run hevy-coach ask "why has my bench stalled?"
```

The coach needs an Anthropic API key (`ANTHROPIC_API_KEY`); nothing else does.

## Layout

| Path | What lives there |
| --- | --- |
| [`backend/src/hevy_coach/csv_import.py`](backend/src/hevy_coach/csv_import.py) | Export parsing, identity, muscle groups |
| [`backend/src/hevy_coach/analytics/`](backend/src/hevy_coach/analytics/) | e1RM, metrics, progression, standards |
| [`backend/src/hevy_coach/coach/`](backend/src/hevy_coach/coach/) | Tools and prompt for the AI coach |
| [`backend/src/hevy_coach/data/`](backend/src/hevy_coach/data/) | Standards dataset and the two mapping files |
| [`backend/scripts/fetch_standards.py`](backend/scripts/fetch_standards.py) | Offline rebuild of the standards dataset |
| [`frontend/app/`](frontend/app/) | Nuxt pages, components and composables |

## When an exercise is not recognised

Two mappings turn an exercise title into something the analytics can use, and
both report what they could not place.

- [`data/muscle_map.json`](backend/src/hevy_coach/data/muscle_map.json) - title
  to muscle groups. Unmatched exercises count as "other" in the volume
  breakdown; `hevy-coach import` lists them.
- [`data/exercise_map.json`](backend/src/hevy_coach/data/exercise_map.json) -
  title to a strength standard. Unmatched exercises are listed on the strength
  page. Bodyweight and timed movements genuinely have no load standard, so
  those stay unmapped by design.

Rules are regexes tried in order against the lowercased title, first match wins,
so specific variants go above their base movement.

## Development

```bash
cd backend  && uv run pytest && uv run ruff check .
cd frontend && npm run typecheck && npm run build
```
