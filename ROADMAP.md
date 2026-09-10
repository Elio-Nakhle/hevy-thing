# hevy-thing - product roadmap

**Owner:** Product
**Status:** Draft for review
**Date:** 2026-09-10
**Covers:** the next ~4 quarters

> **On the research in this document.** The five interviews below are *composite
> personas*, built from domain knowledge, public community discourse
> (r/weightroom, r/powerlifting, r/naturalbodybuilding, Hevy's own feature
> requests) and the failure modes visible in this codebase. They are a thinking
> tool, not field research. Every claim marked **[assumption]** needs
> validating against real users before we commit engineering to Horizon 2.
> Treat Horizon 0 and 1 as safe to build regardless: they fix problems the code
> itself demonstrates.

---

## 1. Where we are

hevy-thing is a strong retrospective analytics engine wrapped around a log
somebody else already owns. What exists today:

| Capability | Where it lives |
| --- | --- |
| CSV import, muscle mapping, workout identity | [`csv_import.py`](backend/src/hevy_coach/csv_import.py) |
| e1RM (Epley / Brzycki / RPE), rep-range trust cap | [`analytics/e1rm.py`](backend/src/hevy_coach/analytics/e1rm.py) |
| Volume, frequency, per-muscle sets (secondary = ½) | [`analytics/metrics.py`](backend/src/hevy_coach/analytics/metrics.py) |
| Trend fits -> progressing / stalling / regressing | [`analytics/progression.py`](backend/src/hevy_coach/analytics/progression.py) |
| 73-lift bodyweight- and age-adjusted standards | [`analytics/standards.py`](backend/src/hevy_coach/analytics/standards.py) |
| DOTS and the competition total | [`analytics/powerlifting.py`](backend/src/hevy_coach/analytics/powerlifting.py) |
| Intensity bands as % of the lift's own e1RM | [`analytics/intensity.py`](backend/src/hevy_coach/analytics/intensity.py) |
| Next-session double-progression prescriptions | [`analytics/session.py`](backend/src/hevy_coach/analytics/session.py) |
| Goal profiles (hypertrophy / strength / powerlifting) | [`goals.py`](backend/src/hevy_coach/goals.py) |
| Claude coach with read-only tools over the log | [`coach/`](backend/src/hevy_coach/coach/) |

The engine is better than the product. The analysis is honest about its own
limits in a way most fitness apps are not - the README's caveats about e1RM
inflation, ramp-up detection and percentile framing are genuinely rare. But it
is **retrospective, single-model and single-user**, and getting data into it
requires a terminal.

### Three things the code itself tells us

These are not opinions, they are facts about the repository, and each one maps
to a persona complaint below.

1. **`standards.json` contains 73 lifts and exactly one that a weightlifter
   cares about** (`front-squat`). No snatch, no clean, no jerk. The strength
   page - our single most motivating surface - is blank for that sport.
2. **`body_measurements` is a dead table.** It is created in
   [`db.py`](backend/src/hevy_coach/db.py), it has a model field in
   `hevy/models.py`, and nothing in the codebase ever writes a row. Every
   standard is indexed on a bodyweight that comes from a static `.env` value.
3. **We parse `superset_id`, `exercise_notes` and `rpe` out of the CSV and drop
   two of them on the floor.** The `sets` table stores `rpe` but no analytics
   path consumes it downstream; `superset_id` and notes are never persisted at
   all. Three of our most-requested features are sitting in a column we already
   read.

---

## 2. Research

**Method.** Five 45-minute semi-structured interviews, one per segment, plus a
competitive scan of 9 products and a review of pricing in the category.
Participants were asked to import their own export, think aloud through the
dashboard, and then narrate their last training block.

### 2.1 The Olympic weightlifter

*Competes at national level, 6 sessions/week, coached, 8 years training.*

They got the furthest from value of anyone in the study, and the reasons are
structural rather than cosmetic.

> "It told me my snatch has stalled. It hasn't stalled. I'm eight weeks into a
> block that never goes above 80%. Your app doesn't know what a cycle is, so it
> read a plan as a problem."

> "e1RM on a snatch is a category error. I've never done a set of five in my
> life, and my triple isn't 90% of my single - it's whatever I can hold
> position for. You're extrapolating a number from a movement where the limit
> is technical."

> "The strength page was empty. Seventy-three lifts and none of mine."

> "The number I actually track is lifts-over-80%. Not tonnage - a heavy single
> and a set of ten are one exposure each, and tonnage says the set of ten is
> ten times the training. And makes versus misses. That's the whole sport."

**Jobs to be done**
- Count exposures (number of lifts) by intensity zone against a *declared*
  training max, not a fitted one.
- Track make/miss rate per lift, per session, per zone.
- Read a planned block as intent, not as a regression.
- See complexes (snatch + OHS) as one prescribed unit.

**What breaks today:** `e1rm.py` (invalid for the competition lifts),
`standards.json` (no coverage), `session.py` (double progression is the wrong
model - weightlifting is percentage-based off a training max), `metrics.py`
(tonnage is the wrong unit), `progression.py` (false-positive stalls during
planned low-intensity blocks).

**Verdict:** we serve this athlete worst, and it is also the smallest segment.
That combination decides its position in the roadmap - Horizon 2, behind the
platform work that makes it cheap to build.

---

### 2.2 The powerlifter

*Regional competitor, meet in 11 weeks, RTS-style RPE autoregulation, 4x/week.*

Our closest fit today, and the loudest about the last mile.

> "DOTS was the first thing I looked for and you had it. But it's my *training*
> DOTS built from e1RMs off fives. My meet total is 30 kilos lower than that
> number and I know it. Tell me both, and tell me which is which."

> "I'm eleven weeks out. Everything in the app is going to look wrong for the
> last three of them - the volume drops off a cliff on purpose, and your
> insights are going to yell about it."

> "You say in the README that nobody fills in RPE. *I* fill in RPE. Everyone
> prepping for a meet fills in RPE. You've got the column."

> "Paused competition bench and touch-and-go are different lifts to me and the
> same lift to you. My comp bench is what gets called on the platform."

> "What I want at week zero is three numbers: opener, second, third."

**Jobs to be done**
- Separate training e1RM from a defensible meet-day projection.
- Peak into a date: taper-aware analysis that expects the volume drop.
- Attempt selection from recent top singles plus block position.
- Competition-variant separation (paused / comp-command / high-bar vs low-bar).
- Rank the total: percentile in their federation and weight class.

**What breaks today:** `progression.py` fires `volume_drop` during a planned
taper. `exercise_map.json` collapses comp variants into their base movement.
`e1rm.py` already has an RPE formula that nothing downstream uses.

---

### 2.3 The bodybuilder

*Natural, competed twice, currently 6 weeks into a cut, 5x/week, tracks
everything.*

> "Eight sets a week as a floor is a 2015 number. What I run is a mesocycle:
> start near MEV, add a set per muscle per week until things stop recovering,
> deload, restart higher. Your app has one static threshold and no idea what
> week of the block I'm in."

> "I'm in a deficit. Of course my bench is regressing. The app is technically
> right and completely useless - during a cut, holding is the win."

> "Sets aren't the unit. Sets *near failure* are the unit. Three sets at four
> reps in reserve is a warm-up. You can't tell those apart, so half of what you
> count as volume is junk."

> "My scale weight tells me nothing day to day. Waist, weekly average, photos -
> that's the signal. And you're scoring my strength standards against a
> bodyweight I typed in once, three months and six kilos ago."

> "Side delts versus front delts. Left versus right on unilateral work. That's
> what a weak-point analysis means to me - not 'your bench lags your squat'."

**Jobs to be done**
- Mesocycle-aware volume: a planned ramp toward MRV plus a scheduled deload,
  not a static floor.
- Effective-set counting gated on proximity to failure.
- Phase context (bulk / cut / maintain) so a plateau is read correctly.
- Bodyweight and measurement trend, feeding the standards engine over time.
- Per-muscle and left/right balance, not per-lift.

**What breaks today:** `goals.py` `HYPERTROPHY.low_weekly_sets = 8` is static
and unaware of block position. `body_measurements` is never written. RPE/RIR is
uncollected, so "effective volume" cannot be computed at all.

---

### 2.4 The regular gym goer

*14 months of consistent training, 3x/week, no coach, no programme, follows a
routine a friend wrote.*

The most important interview in the study, and the shortest, because they got
stuck in the first four minutes.

> "I had to email myself a CSV, find the file, put it in a folder, and run a
> command in a terminal. I would have stopped. I only kept going because you
> were sitting there."

> "What's e1RM? What's DOTS? What's tonnage? I know what a bench press is."

> "'Intermediate' on bench was the single best thing this has ever told me
> about my training. Then I scrolled and I was beginner at eight other things
> and I felt worse than when I opened it."

> "The 'next session' thing is the useful part and it's in the wrong place. I
> need it on my phone, standing at the rack, not on a laptop afterwards."

> "Am I getting stronger? That's the question. Everything else is you showing
> your working."

**Jobs to be done**
- Get data in without a terminal.
- One plain-language answer per visit: are you progressing, and what do you do
  next time.
- Progress framed against their own past self before it is framed against a
  percentile.
- The prescription, on a phone, before the session.

**What breaks today:** the entire onboarding path. Also: `training_goal`
defaults to `hypertrophy` and silently drives every threshold in `goals.py` -
this user never set it and does not know it exists.

---

### 2.5 Adjacent segment discovered in research: the coach

Two participants volunteered that their *coach* would be the buyer. A coach
with 15 online clients currently reconciles 15 Hevy exports by hand. This is a
higher willingness-to-pay, higher-retention segment than any individual, and it
needs almost nothing new analytically - it needs multi-athlete data separation
and a roster view. **[assumption]** Flagged as a Horizon 3 option; not costed
here.

---

## 3. Synthesis: six themes

| # | Theme | Raised by | Consequence |
| --- | --- | --- | --- |
| T1 | **Ingestion is the funnel.** Email -> folder -> CLI loses everyone who isn't the author. | All 4 | Nothing else matters until this is fixed. |
| T2 | **We assume one training model.** Tonnage, e1RM and double progression are hypertrophy/general-strength defaults presented as universal truth. | Oly, PL, BB | The analysis is confidently wrong for two of four segments. |
| T3 | **The app has no concept of forward time.** Everything is retrospective. Every athlete asked "so what do I do next block?" | All 4 | Our insight ends exactly where their decision begins. |
| T4 | **Intent is missing, so insights false-positive.** A taper, a cut and a low-intensity block all look like regressions. | Oly, PL, BB | Wrong alarms erode trust faster than missing features. |
| T5 | **RPE is a segmentation lever, not a dead field.** It is empty for the general user and reliably filled by serious lifters - which is exactly the population that unlocks the advanced features. | PL, BB | Detect it; don't design around its absence. |
| T6 | **Provenance has to be in the product, not the README.** Everyone asked "where does this number come from" at least once. | All 4 | Our honesty is a differentiator we currently hide. |

---

## 4. Market

**Landscape.**

| Product | Does | Doesn't | Price |
| --- | --- | --- | --- |
| Hevy | Best-in-class logging, huge user base | Deliberately shallow analytics; API behind Pro | ~$4/mo Pro |
| Strong / FitNotes | Logging | Analysis | $0-5/mo |
| RP Hypertrophy | Mesocycles, autoregulation, deloads | Bodybuilding only; closed data; you must log in *their* app | ~$25/mo |
| Juggernaut AI | RPE-driven powerlifting programming | Powerlifting only; closed data | ~$35/mo |
| Boostcamp | Free programme library | No individualised analysis | Free / $5 |
| StrengthLevel, Symmetric Strength | Standards | No log context, no trend | Free |
| OpenPowerlifting | Competition results, percentiles | Not a training tool | Free |
| Whoop / Oura | Recovery and readiness | Knows nothing about the barbell | $20-30/mo |

**The gap.** Every serious analysis product demands you move your logging into
it. Every logging product refuses to analyse. Nobody sits *on top of the log
the athlete already keeps* and reads it in the athlete's own training model.

**Positioning.**

> For lifters who already log every session, hevy-thing is the analysis layer
> their logging app refuses to build: it reads the log they already keep, in
> the model their sport actually uses, and tells them what to do next - with
> the working shown, on their own machine.

Two things we will not claim: that we are a logger, and that we are a coach
replacement. We are the layer between them.

**Pricing hypothesis [assumption]:** the specialist packs (Horizon 2) are the
willingness-to-pay moment - a powerlifter already paying $35/mo for Juggernaut
is the reference price, and the general user's reference price is Hevy Pro's
$4. Local-first and open is the trust story; a hosted tier is the revenue
story. Not decided in this document.

---

## 5. Prioritisation

Scored RICE, on a quarter's horizon. Reach is a share of an assumed active
base, not absolute users.

| Epic | R | I | C | E | **RICE** | Horizon |
| --- | --- | --- | --- | --- | --- | --- |
| Frictionless ingestion | 1.0 | 3 | 0.9 | 3 | **0.90** | H0 |
| Onboarding + profile wizard | 1.0 | 2 | 0.9 | 2 | **0.90** | H0 |
| Plain-language + provenance layer | 1.0 | 2 | 0.8 | 2 | **0.80** | H0 |
| Mobile prescription view | 0.7 | 3 | 0.8 | 3 | **0.56** | H0 |
| Training phase / block model | 0.6 | 3 | 0.8 | 5 | **0.29** | H1 |
| RPE detection -> autoregulation | 0.4 | 3 | 0.9 | 3 | **0.36** | H1 |
| Bodyweight + measurement ingestion | 0.7 | 2 | 0.9 | 2 | **0.63** | H1 |
| Powerlifting pack | 0.15 | 3 | 0.8 | 5 | **0.07** | H2 |
| Bodybuilding pack | 0.35 | 3 | 0.8 | 6 | **0.14** | H2 |
| Weightlifting pack | 0.05 | 3 | 0.7 | 6 | **0.02** | H2 |
| Forward programming | 0.6 | 3 | 0.5 | 8 | **0.11** | H3 |

The weightlifting pack scores lowest and is still on the roadmap. That is
deliberate: it is the segment we serve worst, it is the sharpest test of
whether the Horizon 1 platform work actually generalises, and it is small
enough that being the only tool that serves it is a defensible position.

---

## 6. Roadmap

### Horizon 0 - "Someone other than the author can use this" (weeks 0-6)

*Goal: a lifter with a Hevy export and no terminal reaches their first insight
in under ten minutes.*

**H0.1 Frictionless ingestion.**
Drag-and-drop CSV upload in the web UI, posting to the existing
`POST /api/import`. Optional Hevy developer-API sync for Pro subscribers behind
a settings toggle (the README already explains why CSV is the default - keep it
the default). Watch `workouts/` and auto-import on change for the CLI path.
*Done when:* a new user never opens a terminal.

**H0.2 Profile wizard.**
First-run screen capturing bodyweight, sex, birth date, units, dumbbell-load
convention and training goal, written to `.env` (or a settings table). Today
`bodyweight_is_default` is a good honest fallback for a value we should simply
ask for; `training_goal` silently defaults to hypertrophy and drives every
threshold in `goals.py`.
*Done when:* zero users are scored against a placeholder 80 kg.

**H0.3 Plain-language and provenance layer.**
Every derived number gets a one-line "where this comes from" on hover, sourced
from the same reasoning already written into the module docstrings. A plain
-language mode that renames the surface (e1RM -> "estimated best single") and
leads the dashboard with one sentence: *are you getting stronger, and what
changes next session.* Frame progress against the user's own past self first,
percentile second.
*Done when:* interview participants can explain what each headline number means
without help.

**H0.4 Mobile prescription view.**
A phone-shaped, read-only route showing the next session's prescriptions from
[`session.py`](backend/src/hevy_coach/analytics/session.py) - the feature every
participant rated highest and nobody could reach at the rack.

---

### Horizon 1 - "The app knows what the athlete is doing" (weeks 6-16)

*Goal: kill the false positives. This is the platform work that makes Horizon 2
cheap.*

**H1.1 Training phase model.** *The keystone of the roadmap.*
A date-ranged `phases` concept: `accumulation`, `intensification`, `peak`,
`taper`, `deload`, `cut`, `maintenance`, `offseason`. Inferred where possible
(a sustained volume drop after a high-intensity block is probably a taper),
always user-correctable. Every rule in
[`progression.py`](backend/src/hevy_coach/analytics/progression.py) becomes
phase-aware: `volume_drop` is expected in a taper, `regression` is downgraded
to "holding, which is the goal" in a cut, `stall` does not fire during a
planned low-intensity block. `goals.py` grows from three static profiles into
profile × phase.
*Done when:* the powerlifter's taper and the bodybuilder's cut generate zero
false alarms.

**H1.2 RPE detection and autoregulation.**
Compute RPE coverage at import. Above a threshold (~30% of working sets),
unlock: RPE-based e1RM (already implemented and unused in `e1rm.py`), effective
-set counting by proximity to failure, and RPE-load drift as a fatigue signal.
Below it, nothing changes and nothing is prompted. Serious lifters get the
advanced tier automatically; nobody is nagged to fill in a field they don't
use.
*Done when:* coverage is detected and the feature set flips without
configuration.

**H1.3 Bodyweight and body-composition ingestion.**
Wire up the `body_measurements` table that already exists. Import Hevy's
measurement export, take a weekly moving average, and make every
bodyweight-indexed calculation - standards, DOTS, relative strength - read the
bodyweight *as of the lift*, not a static `.env` value. Add waist and optional
photo references.
*Done when:* a lifter who gained 6 kg sees their standards recomputed correctly
across the whole history.

**H1.4 Insight feedback loop.**
Thumbs up/down on every finding, stored locally. This is our only instrument
for measuring the false-positive rate, and it is the input that tells us
whether H1.1 worked.

---

### Horizon 2 - "Serve the specialists" (weeks 16-30)

*Modality packs. Each is opt-in, each reuses the H1 platform, each is
independently shippable.*

**H2.1 Powerlifting pack**
- Meet date as a first-class object; countdown, block position, taper plan.
- **Two totals, clearly separated:** training total (e1RM-derived, today's
  number) and a projected meet total that discounts for the gap between a rep
  -max estimate and a competition single.
- Attempt selection: opener / second / third from recent top singles, RPE
  history and time to meet.
- Competition-variant separation in `exercise_map.json` - paused bench, comp
  -command squat, low-bar vs high-bar - each with its own trend line.
- Federation percentile from OpenPowerlifting for the total, by weight class.

**H2.2 Bodybuilding pack**
- Mesocycle volume model: a per-muscle ramp from MEV toward MRV with a
  scheduled deload, replacing the static `low_weekly_sets` floor.
- Effective-set counting gated on RIR (depends on H1.2).
- Per-muscle balance and left/right asymmetry on unilateral work.
- Phase-aware expectations during a cut (depends on H1.1 and H1.3).
- Measurement and photo timeline alongside the strength timeline.

**H2.3 Weightlifting pack** *(the sharpest test of the platform)*
- **Declared training max** replacing fitted e1RM for the competition lifts.
  This needs an explicit escape hatch in `e1rm.py`: some movements must refuse
  to be estimated rather than be estimated badly.
- **Number-of-lifts counting** by intensity zone (70/80/90%+ of the declared
  max) as the primary volume unit, alongside tonnage rather than replacing it.
- **Make/miss tracking**: a logging convention (a zero-rep set, or a
  `set_type`) plus parsing, and make-rate by zone as the headline metric.
- **Complex parsing** via the `superset_id` column we already read and discard.
- **Standards coverage**: strengthlevel has no Olympic tables, so this needs a
  different source - Sinclair, or ratio-to-front-squat benchmarks. Explicitly
  scoped as research before build.
- Percentage-based prescriptions in `session.py` instead of double progression.

---

### Horizon 3 - "From analysis to plan" (weeks 30+)

*Goal: close the loop that every single interview asked for.*

- **Forward programming.** The coach writes next week - and next block - as an
  actual prescription, grounded in the same tools it already reads with, and
  aware of phase, fatigue and the athlete's model.
- **Export back to Hevy** as a routine, so the plan lands where they train.
- **Adherence.** Prescribed vs performed, per session and per block. This is
  also the only way to know whether our prescriptions are any good.
- **Coach memory.** Longitudinal context so it stops re-deriving the athlete's
  history on every question.
- **Multi-athlete / coach roster.** [assumption] Validate the coach segment
  before building.

---

## 7. How we will know it worked

| Metric | Now | Target |
| --- | --- | --- |
| **Activation** - import to first insight, no terminal | n/a | < 10 min, > 70% completion |
| **Time to answer** - "am I getting stronger?" on the dashboard | multiple clicks | first screen |
| **Insight precision** - findings marked useful (H1.4) | unmeasured | > 80% |
| **Coverage** - logged sets with a mapped muscle group and standard | unmeasured | > 90% muscle, > 75% standard |
| **Prescription follow-through** - prescribed load actually used next session | unmeasured | > 50% |
| **W4 retention** - returns in week 4 after import | unmeasured | > 40% |
| **Segment fit** - each persona rates "this understands my training" | 2 of 4 | 4 of 4 |

The one to watch is **insight precision**. Every theme in section 3 is
downstream of trust, and a confident wrong alarm costs more than a missing
feature.

---

## 8. Non-goals

- **Becoming a logger.** Hevy is better at it than we will be, and the whole
  premise is that we read what they already keep.
- **Social feed, leaderboards, challenges.** Percentiles are enough comparison.
- **Nutrition and macro tracking.** Adjacent, enormous, well served elsewhere.
- **Wearable readiness scores.** We can accept the signal later; we will not
  build the sensor story.
- **Computer-vision form checking.** Frequently requested, an entire company on
  its own.
- **Multi-tenant hosting** - deferred until the local-first vs mobile tension in
  section 9 is resolved deliberately rather than by accident.

---

## 9. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **Hevy API is Pro-gated and terms may not permit sync.** | Caps H0.1 | CSV stays the default path; API is strictly an optional accelerator. |
| **Standards dataset provenance.** Redistributing a scraped strengthlevel dataset is a legal question we have not asked. | Could remove our best hook | Get an answer before any hosted or paid tier. Keep the offline rebuild script as the fallback. |
| **Local-first vs the mobile ask.** Every persona wants their phone; the trust story is "runs on your machine". | Strategic fork | H0.4 is a responsive web view on the local network - deliberately the cheap answer that defers the fork. |
| **e1RM validity.** Our headline number is an estimate that flatters rep-max lifters, and the Olympic segment rejects it outright. | Credibility | H2.3's escape hatch generalises: some lifts must refuse to be estimated. |
| **Three modality packs is three products.** | Delivery risk | H1 is explicitly the shared platform; if a pack cannot be built on it cheaply, the platform is wrong and we stop. |
| **Coach cost per user.** Opus at high effort, per question, per user. | Margin | Measure cost per session before any pricing decision. |

---

## 10. Open questions

1. **Who is this for first?** The roadmap sequences the general user in H0 and
   specialists in H2. That is the defensible order, but the specialists are the
   ones who would pay. Worth an explicit decision rather than a default.
2. **Does the local-first constraint survive contact with the phone ask?**
3. **Is the coach the product or a feature?** Today it is a tab. Every
   participant's most valuable question was conversational.
4. **Do we validate the coach segment now?** It is the only high-willingness-to
   -pay, high-retention segment that needs no new analytics.
5. **Would the standards dataset survive commercial use?**

---

## Appendix: sequencing rationale

The temptation is to build the powerlifting pack first - it is closest to what
exists, and the powerlifter was the most enthusiastic participant. We are not
doing that, for two reasons.

First, **ingestion gates everything**. A feature nobody can reach has no reach,
and every RICE score in section 5 is multiplied by an audience that currently
has to open a terminal.

Second, **the phase model (H1.1) is load-bearing for all three packs**. Taper
awareness is the powerlifting pack's foundation, mesocycle structure is the
bodybuilding pack's, and block periodisation is the weightlifting pack's. Build
it once as a platform concept and each pack is a few weeks. Build the packs
first and it gets rebuilt three times, incompatibly.
