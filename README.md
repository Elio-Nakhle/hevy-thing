# hevy-thing

Training analytics, strength-standard benchmarking and an AI coach, built on the
CSV export from [Hevy](https://www.hevyapp.com/).

A Python backend reads the export into SQLite, computes the analytics, and
serves them to a Nuxt frontend and a CLI. Everything runs locally against your
own data.

```
upload or workouts/*.csv  ->  SQLite  ->  analytics  ->  FastAPI  ->  Nuxt
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
  continuous 0-4 level score rather than a bucket. The band names are percentiles
  of lifts logged on that site - beginner is the 5th, novice the 20th,
  intermediate the 50th, advanced the 80th, elite the 95th - so they rank you
  against people who track their training, not the general population. Standards
  built on other populations put the same lift a band or two higher.
- **Findings** - rule-based insights: stalls, regressions, dormant lifts, low
  weekly volume, and lifts that lag their own variations by a full level.
- **Your total** - on a strength or powerlifting goal, a **Total** page adds up
  the lifts that goal is judged on, scores them with DOTS, and breaks down what
  the next DOTS marker costs: the gap split across squat, bench and deadlift in
  proportion to what each already contributes, snapped to 2.5 kg jumps. It is a
  *training* total, built from estimated 1RMs, so it reads higher than what you
  would hit on the platform - the page says so. DOTS is scored on squat, bench
  and deadlift only, whatever else the goal totals, because that is the total
  the coefficients were fitted to. The page is offered only for a goal that has
  a total; hypertrophy is judged on weekly volume instead.
- **Session plans** - open any workout for what it did to each lift and what to
  load the next time that routine comes round. Prescriptions use double
  progression, with the load increment read from the jumps you actually make and
  deload/hold branches for lifts that have stopped responding. See
  [Next-session prescriptions](#next-session-prescriptions).
- **Next session, on your phone** - `/next` is a one-column view of the
  prescriptions for whichever routine is due, sized for reading at the rack. It
  works out what is due from what you actually train: a routine has to repeat
  and to have been trained in the last four weeks, so a dropped programme or a
  week of hotel-gym improvising cannot sit at the top of the list. Trying five
  routines is not committing to five - the rest stay one tap away, and you can
  put a routine away for good when the dates alone cannot know you are done
  with it.
- **Coach** - Claude with read-only tools over the log, so answers come from
  your actual numbers.

Two things about how it reads. The dashboard **leads with one sentence** - are
you getting stronger, and what changes next session - measured against your own
past self, with the percentile kept on the strength page where you go looking
for it. And every derived number carries **where it came from**: hover any term
for a one-line account of how it was computed and what not to trust about it,
or hit **Plain** in the header to rename the whole surface (`e1RM` becomes
"estimated best single"). Both come from one table,
[`provenance.py`](backend/src/hevy_coach/provenance.py), so a tooltip cannot
describe something other than what its label says.

## Getting your data in

The developer API needs a Hevy Pro subscription; the CSV export does not, so
that is what this reads.

In the Hevy app: **Profile -> Settings -> Export Data**. You get a CSV by email.
Then either:

**In the browser.** Drop the CSV on the dashboard, or click **Import CSV** in the
header. No terminal.

**On the command line.** Drop the file in [`workouts/`](workouts/) - any filename
works - and run the import. The **newest CSV in the folder** is the one that gets
read.

```bash
cd backend && uv run hevy-coach import
```

The two are the same path: an upload is saved into `workouts/` and imported from
there, so the browser and the CLI always agree about which export is current.

Re-importing is safe: workout identity is derived from the start time, so an
updated export updates rows rather than duplicating them. An export is your
complete history, so workouts it no longer contains are removed to match
(`--no-prune` to keep them).

No export to hand? `uv run hevy-coach demo` seeds a synthetic log.

## Setup

```bash
uv tool install invoke    # task runner; `inv --list` for everything below
inv setup                 # copies .env.example, uv sync, npm install
```

Without invoke:

```bash
cp .env.example .env
cd backend && uv sync
cd ../frontend && npm install
```

Nothing needs editing by hand. The app asks for the lifter profile on first run
and writes your answers to `.env` (read from the repository root), which is also
what the CLI reads - so there is one place a value can come from. **Settings**
edits it later.

### Why it asks

Six values decide what most of the analysis *says*:

| Value | What it changes |
| --- | --- |
| **Bodyweight** | Every standard is indexed on it. On the log in this repo, the placeholder 80 kg reads as *novice* and the real 55 kg as *advanced* - the same lifts, two whole bands apart. |
| **Sex** | Which published table each lift is scored against. |
| **Training goal** | Every volume and frequency threshold in `goals.py`. Switching hypertrophy to powerlifting on that same log turns 25 findings into 15 and swaps a low-volume warning for heavy-exposure and main-lift-frequency ones. |
| **Birth date** | Enables the age adjustment on the standards. Optional. |
| **Dumbbell loads** | `combined` if you type the pair's total. The tables are published per dumbbell - what Hevy asks for - so a combined log otherwise scores at double. |
| **Units** | Display only. Everything is stored and calculated in kilograms. |

A key commented out in `.env` is *unset*, which the app tells apart from a value
you chose: unset is what makes it offer the form, and what makes the strength
page admit a number is a stand-in rather than presenting it as yours. Only
bodyweight is required - it is the one answer that cannot be guessed.

## Running it

```bash
inv hevy-thing              # API on :8000 and UI on :3000; Ctrl-C stops both
inv hevy-thing.backend      # just the API
inv hevy-thing.frontend     # just the UI
inv hevy-thing --lan        # also reachable from your phone, for /next
```

`--lan` binds the UI to every interface so a phone on the same network can open
it - the point of the `/next` view. Only the UI is exposed; the browser's `/api`
requests are proxied by the Nuxt server, which reaches the backend over
loopback, so the API stays bound to localhost either way.

Ports are flags: `--api-port` / `--web-port` on the combined task, `--port` on
either single one. The combined task also points the frontend's proxy at
whichever API port you pick (`inv hevy-thing.frontend --api <url>` on its own).
The equivalent by hand:

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
| [`backend/src/hevy_coach/analytics/session.py`](backend/src/hevy_coach/analytics/session.py) | Per-session analysis and next-session prescriptions |
| [`backend/src/hevy_coach/coach/`](backend/src/hevy_coach/coach/) | Tools and prompt for the AI coach |
| [`backend/src/hevy_coach/data/`](backend/src/hevy_coach/data/) | Standards dataset and the two mapping files |
| [`backend/scripts/fetch_standards.py`](backend/scripts/fetch_standards.py) | Offline rebuild of the standards dataset |
| [`frontend/app/`](frontend/app/) | Nuxt pages, components and composables |
| [`tasks.py`](tasks.py) | Invoke tasks - running the stack, checks, setup |

## Next-session prescriptions

Every workout page ends each exercise with what to do next time. The model is
**double progression**: hold the load until every working set reaches the top of
its rep range, then add the smallest increment and drop back to the bottom of
the range. Three details are worth knowing before you trust it.

**Rep ranges are read off the session, not configured.** The median reps across
all of an exercise's sets picks one of `1-3`, `4-6`, `6-10`, `10-15`, `15-20`.
Using the median of every set rather than the heaviest one matters: a ramp
finishing on a heavy triple is still a session of fives, and reading the range
off the top set alone would prescribe singles.

**Load increments come from your own history.** The median jump between the
distinct loads you have used on that exercise in its last eight sessions,
snapped to something loadable. A machine whose stack moves in fours gets
progressed in fours without anyone configuring it. Equipment category is the
fallback until an exercise has two distinct loads on record.

**Ramp-up sets are excluded.** Hevy's CSV types every set `normal`, so a ramp is
indistinguishable from straight sets by label. The heaviest load in the exercise
is found and only the sets at that load count as working sets; the rest are
shown but do not affect the decision.

Progression is overridden in two cases. A lift at an unchanged load with no new
e1RM best for three sessions is **stalled** and gets a 10% deload rather than
more weight. A session that lands under both your best and the session before it
**holds** instead of progressing, because one down session is usually sleep or
stress.

Note that RPE is not used anywhere in this: Hevy exports the field but almost
nobody fills it in, so anything RPE-gated would silently never fire.

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
inv check                   # lint, tests, typecheck, build
inv test -k standards       # backend tests, filtered
inv lint --fix              # ruff, applying what it can fix
inv fmt                     # ruff format
```

Tasks live in [`tasks.py`](tasks.py). What `inv check` runs, by hand:

```bash
cd backend  && uv run pytest && uv run ruff check .
cd frontend && npm run typecheck && npm run build
```
