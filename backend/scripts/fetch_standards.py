"""Build the bundled strength-standards dataset from strengthlevel.com.

This is an *offline* build step, not a runtime dependency. Run it when you want to
refresh the bundled tables:

    uv run python scripts/fetch_standards.py

It writes ``src/hevy_coach/data/standards.json``. The site publishes, per lift and
per sex, two tables: a bodyweight table (kg lifted at each of the five standard
levels for a given bodyweight) and an age table (the same five levels at each age,
for the average lifter). We keep the bodyweight table as the primary lookup and
derive a multiplicative age factor from the age table, normalised to its peak.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://strengthlevel.com/strength-standards/{slug}/kg"
USER_AGENT = "hevy-coach/0.1 (personal training analytics; +https://github.com/)"
OUT = Path(__file__).resolve().parents[1] / "src" / "hevy_coach" / "data" / "standards.json"

LEVELS = ("beginner", "novice", "intermediate", "advanced", "elite")

# Lifts we pull. The key is our internal lift id, used by data/exercise_map.json
# to link Hevy exercise templates to a standard.
SLUGS = [
    "bench-press",
    "squat",
    "deadlift",
    "shoulder-press",
    "barbell-curl",
    "bent-over-row",
    "front-squat",
    "incline-bench-press",
    "close-grip-bench-press",
    "sumo-deadlift",
    "romanian-deadlift",
    "hex-bar-deadlift",
    "hip-thrust",
    "military-press",
    "t-bar-row",
    "seated-cable-row",
    "lat-pulldown",
    "leg-extension",
    "dumbbell-bench-press",
    "dumbbell-shoulder-press",
    "dumbbell-curl",
    "dumbbell-row",
    "dumbbell-lateral-raise",
    "ez-bar-curl",
    "tricep-pushdown",
    "face-pull",
    "goblet-squat",
    "bulgarian-split-squat",
    "pull-ups",
    "chin-ups",
    "dips",

    # Legs
    "leg-press",
    "horizontal-leg-press",
    "hack-squat",
    "smith-machine-squat",
    "zercher-squat",
    "dumbbell-lunge",
    "good-morning",
    "lying-leg-curl",
    "seated-leg-curl",
    "seated-calf-raise",
    "calf-raise",
    "dumbbell-calf-raise",
    "barbell-calf-raise",
    "hip-abduction",
    "hip-adduction",
    "machine-back-extension",

    # Chest
    "machine-chest-fly",
    "cable-fly",
    "dumbbell-fly",
    "chest-press",

    # Shoulders
    "machine-reverse-fly",
    "dumbbell-reverse-fly",
    "machine-lateral-raise",
    "cable-lateral-raise",
    "upright-row",
    "landmine-press",
    "machine-shoulder-press",
    "seated-shoulder-press",

    # Back
    "dumbbell-shrug",
    "barbell-shrug",
    "machine-row",

    # Arms
    "cable-curl",
    "preacher-curl",
    "hammer-curl",
    "incline-curl",
    "reverse-curl",
    "skullcrusher",
    "tricep-rope-pushdown",
    "wrist-curl",
    "reverse-wrist-curl",

    # Other
    "farmers-walk",
    "cable-crunch",

    # Reps- and time-only lifts (push-ups, sit-ups, crunches, planks, hanging
    # leg raises, bodyweight calf raises) are not listed: they publish no load
    # table at all. scrape() also rejects them on the page's own shape, so
    # adding one by mistake is caught rather than silently mis-parsed.
]

# The site publishes three page shapes, and picking the wrong table silently
# scores a lifter's kilos against a column of *reps*. Each shape is detected
# from the page itself rather than a hand-kept list of slugs:
#
# * **load** - a "Bodyweight Ratio" tab alongside the weight table. The weight
#   table is absolute load on the bar or machine. Most lifts.
# * **added load** - a reps table followed by a "1RM Weight" panel of signed
#   added load (`+22 kg`, `-5 kg` when assisted), which is exactly what Hevy
#   records in `weight_kg` for these. Pull-ups, chin-ups, dips.
# * **reps or time only** - no load table anywhere. Sit-ups, crunches, planks,
#   push-ups, bodyweight back extensions and calf raises. There is nothing here
#   to compare a logged load against, so these are skipped rather than
#   mis-parsed into a kg table.

#: Marks the start of the "1RM Weight" tab panel within a sex's section.
ADDED_WEIGHT_MARKER = "tabs-1rm-weight-kg"

#: Only appears on pages whose primary table is absolute load.
LOAD_MARKER = "bodyweight ratio"


class RepsOnlyStandard(Exception):
    """The lift has no load table - only reps or time."""


def fetch(url: str, attempts: int = 3) -> str:
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:
            last = exc
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_tables(page: str) -> list[list[list[str]]]:
    """Return every <table> on the page as a list of rows of cell strings."""
    tables: list[list[list[str]]] = []
    for match in re.finditer(r"<table[^>]*>(.*?)</table>", page, re.S):
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(1), re.S):
            cells = [strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def as_float(text: str) -> float | None:
    """Parse a table cell: ``100``, ``+22 kg``, ``-5 kg``, ``< 1``."""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def numeric_table(rows: list[list[str]], first_header: str) -> dict[float, list[float]] | None:
    """Parse a `BW|Age` + five-level table into {key: [beginner..elite]}."""
    header = [c.lower() for c in rows[0]]
    if not header or first_header not in header[0] or len(header) < 6:
        return None
    out: dict[float, list[float]] = {}
    for row in rows[1:]:
        if len(row) < 6:
            continue
        key = as_float(row[0])
        values = [as_float(c) for c in row[1:6]]
        if key is None or any(v is None for v in values):
            continue
        # Levels must be monotonically increasing; anything else is a parse error.
        if any(values[i] >= values[i + 1] for i in range(4)):  # type: ignore[operator]
            continue
        out[key] = [float(v) for v in values]  # type: ignore[arg-type]
    return out or None


def sex_sections(page: str) -> dict[str, str]:
    """Split the page into the male and female halves using the <h2> headings."""
    marks: list[tuple[int, str]] = []
    for match in re.finditer(r"<h2[^>]*>(.*?)</h2>", page, re.S):
        title = strip_tags(match.group(1)).lower()
        if title.startswith("male "):
            marks.append((match.start(), "male"))
        elif title.startswith("female "):
            marks.append((match.start(), "female"))
    sections: dict[str, str] = {}
    for i, (start, sex) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(page)
        sections.setdefault(sex, page[start:end])
    return sections


def age_factors(age_table: dict[float, list[float]]) -> dict[str, float]:
    """Collapse the age table into one multiplier per age, normalised to the peak.

    The five level columns move almost in lockstep with age, so a single factor
    per age captures it; we average the five columns' ratios to the peak age.
    """
    if not age_table:
        return {}
    peak_age = max(age_table, key=lambda a: sum(age_table[a]))
    peak = age_table[peak_age]
    factors: dict[str, float] = {}
    for age, values in sorted(age_table.items()):
        ratios = [v / p for v, p in zip(values, peak, strict=True) if p]
        if ratios:
            factors[str(int(age))] = round(sum(ratios) / len(ratios), 4)
    return factors


def scrape(slug: str) -> dict[str, Any] | None:
    page = fetch(BASE.format(slug=slug))
    title_match = re.search(r"<h2[^>]*>\s*Male\s+(.*?)\s+Standards", page, re.S)
    name = strip_tags(title_match.group(1)) if title_match else slug.replace("-", " ").title()

    sections = sex_sections(page)
    added_weight = any(ADDED_WEIGHT_MARKER in section for section in sections.values())
    if not added_weight and not any(
        LOAD_MARKER in section.lower() for section in sections.values()
    ):
        raise RepsOnlyStandard(f"{slug} is a reps/time standard, not a load standard")

    entry: dict[str, Any] = {
        "name": name,
        "source": BASE.format(slug=slug),
        # "kg" = load on the bar/machine. "added_kg" = load added to bodyweight,
        # negative for assisted reps - the same convention Hevy logs.
        "metric": "added_kg" if added_weight else "kg",
        "sexes": {},
    }

    for sex, section in sections.items():
        if added_weight:
            marker = section.find(ADDED_WEIGHT_MARKER)
            if marker == -1:
                continue  # no added-weight panel; skip rather than emit reps
            section = section[marker:]
        tables = parse_tables(section)
        bw = next((t for t in (numeric_table(r, "bw") for r in tables) if t), None)
        age = next((t for t in (numeric_table(r, "age") for r in tables) if t), None)
        if not bw:
            continue
        entry["sexes"][sex] = {
            "bodyweights_kg": [float(k) for k in sorted(bw)],
            "levels": {
                level: [bw[k][i] for k in sorted(bw)] for i, level in enumerate(LEVELS)
            },
            # Age factors are ratios to the peak-age row, which is only
            # meaningful for a strictly positive scale. Added-weight standards
            # cross zero (assisted reps), so we publish no age curve for them.
            "age_factors": {} if added_weight else age_factors(age or {}),
        }

    return entry if entry["sexes"] else None


def main() -> int:
    dataset: dict[str, Any] = {
        "schema_version": 1,
        "unit": "kg",
        "levels": list(LEVELS),
        "source": "https://strengthlevel.com/strength-standards",
        "retrieved_at": time.strftime("%Y-%m-%d"),
        "lifts": {},
    }

    failures: list[str] = []
    skipped: list[str] = []
    for slug in SLUGS:
        try:
            entry = scrape(slug)
        except RepsOnlyStandard as exc:
            print(f"  -- {exc}", file=sys.stderr)
            skipped.append(slug)
            continue
        except Exception as exc:
            print(f"  !! {slug}: {exc}", file=sys.stderr)
            failures.append(slug)
            continue
        if entry is None:
            print(f"  !! {slug}: no parseable standards tables", file=sys.stderr)
            failures.append(slug)
            continue
        dataset["lifts"][slug] = entry
        sexes = ",".join(sorted(entry["sexes"]))
        print(f"  ok {slug:28s} {entry['name']:34s} [{sexes}]")
        time.sleep(0.7)  # be polite

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dataset, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {len(dataset['lifts'])} lifts to {OUT}")
    if skipped:
        print(f"skipped (reps/time only): {', '.join(skipped)}", file=sys.stderr)
    if failures:
        print(f"failed: {', '.join(failures)}", file=sys.stderr)
    return 1 if not dataset["lifts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
