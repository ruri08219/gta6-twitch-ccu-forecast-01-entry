"""Forecast GTA VI launch-day Twitch viewers, hour by hour (hours 2-24).

Model: a diurnal curve anchored at the hour-1 print.

Launch-day Twitch audiences for big console games follow a strong
within-day shape when measured against the first hour: a dip in the small
hours (hour 1 is 00:00-01:00 UTC, i.e. UK/Europe just unlocked, US still
locked), then a climb as the US unlocks (05:00 / 08:00 UTC) and the US
evening arrives, peaking around hours 19-21 at roughly 2.5x hour 1.  This
program estimates that shape from the case's own `comparables`: for each
past launch it takes the release-day hourly viewers, forms the log ratio
of each hour to that launch's hour 1, and takes the median across launches
plus the spread of those log ratios.  The median curve is what the
forecast's centre follows; the spread sets the quantile widths.

Only like-for-like launches are used for the shape: console-only releases
with a rolling midnight-local unlock and no early access, no simultaneous
global unlock and no free-to-play/beta contamination.  Those are the
launches whose hour 1 means the same thing as GTA VI's hour 1 (a game
already live in New Zealand / Australia / Asia and just unlocked in the
UK and Europe, with the US still to come).  Launches with a PC release or
a single worldwide unlock time have a totally different hour-1 meaning --
their hour 1 can be near zero and their evening can be hundreds of times
bigger -- so they are left out of the shape estimate.  Each hour prefers
the like-for-like launches when at least three of them report that hour,
otherwise all usable comparables, otherwise a fixed prior curve measured
from the same kind of launches for that hour alone.

Spreads: the per-hour standard deviation of the log ratios across the
like-for-like launches, smoothed across neighbouring hours and inflated
by 1.5x.  The inflation is deliberate: with only a handful of launches
the raw sample spread understates how far a new launch can sit from the
median, and the pinball score punishes an over-narrow band at every hour
outside it.  A floor of 0.30 log units keeps the earliest hours honest.

The case's own pre-release history is deliberately NOT used to adjust the
shape: on the comparable launches, neither the hour-1 print's size nor
the pre-midnight level predicts the evening growth (correlation of the
pre-midnight / hour-1 ratio with the hour-19 / hour-1 ratio is about
-0.09), so adding it would be fitting noise.

Usage (Python 3.13, standard library only, no network, deterministic):
reads every <id>.in in $MAKEFUN_INPUT_DIR (else /input) and writes
<id>.out to $MAKEFUN_OUTPUT_DIR (else /output) as
{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}, ...]} for h 2..24.
"""

import json
import math
import os
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# Standard normal quantiles at the scored levels.
Z_SCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722)
HOURS = tuple(range(2, 25))

MIN_ANY = 3
SPREAD_INFLATION = 1.5
SPREAD_FLOOR = 0.30

# Prior curve, used only when the case carries too few usable
# comparables: median hour-1 ratio and log spread per hour, measured from
# console-only rolling-midnight launches (see module docstring).
PRIOR_RATIO = {
    2: 0.707, 3: 0.662, 4: 0.666, 5: 0.768, 6: 0.919, 7: 0.955,
    8: 0.921, 9: 0.869, 10: 0.855, 11: 0.892, 12: 0.986, 13: 1.137,
    14: 1.400, 15: 1.729, 16: 2.021, 17: 2.176, 18: 2.341, 19: 2.528,
    20: 2.673, 21: 2.657, 22: 2.563, 23: 2.416, 24: 2.332,
}
PRIOR_SPREAD = {
    2: 0.37, 3: 0.37, 4: 0.38, 5: 0.30, 6: 0.30, 7: 0.38,
    8: 0.45, 9: 0.48, 10: 0.51, 11: 0.52, 12: 0.57, 13: 0.61,
    14: 0.68, 15: 0.72, 16: 0.74, 17: 0.75, 18: 0.75, 19: 0.73,
    20: 0.69, 21: 0.66, 22: 0.64, 23: 0.62, 24: 0.58,
}

# Substrings that mark a comparable as a different kind of launch from a
# console-only rolling-midnight release like GTA VI.
EXCLUDED_PLATFORM = ("pc",)
EXCLUDED_UNLOCK = ("early access", "simultaneous", "free-to-play",
                   "f2p", "beta")


def _parse_time(text):
    """Parse an ISO-8601 UTC timestamp into an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _pstdev(values, mean):
    if len(values) < 2:
        return 0.5
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _smooth_neighbour(values_by_hour):
    """Three-point moving average over hours; ends average what exists."""
    hours = sorted(values_by_hour)
    out = {}
    for i, h in enumerate(hours):
        near = hours[max(0, i - 1):i + 2]
        out[h] = sum(values_by_hour[k] for k in near) / len(near)
    return out


def _is_like_for_like(comparable):
    platforms = str(comparable.get("platforms", "")).lower()
    unlock = str(comparable.get("unlock", "")).lower()
    if any(word in platforms for word in EXCLUDED_PLATFORM):
        return False
    return not any(word in unlock for word in EXCLUDED_UNLOCK)


def _release_day_profile(comparable):
    """Hour -> viewers for the comparable's own release UTC day.

    Returns None when the launch's hour-1 print is missing or not
    positive; individual later hours may be missing and are simply
    left out of that hour's statistics.
    """
    try:
        day_start = _parse_time(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_time = {}
    for row in comparable.get("hourly") or []:
        try:
            by_time[_parse_time(row["from"])] = float(row["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
    first = by_time.get(day_start)
    if not first or first <= 0:
        return None
    profile = {}
    for hour in range(1, 25):
        value = by_time.get(day_start + timedelta(hours=hour - 1))
        if value is not None and value > 0:
            profile[hour] = value
    return profile


def _hour_stats(profiles):
    """Per hour: (median log ratio, spread, count) from release-day profiles.

    An hour is only as good as the launches that actually report it, so
    each hour carries its own count; sparse hours are not allowed to
    silently borrow a neighbour's statistics.
    """
    stats = {}
    for hour in HOURS:
        ratios = [math.log(p[hour] / p[1]) for p in profiles if hour in p]
        if not ratios:
            continue
        middle = _median(ratios)
        stats[hour] = (middle,
                       _pstdev(ratios, sum(ratios) / len(ratios)),
                       len(ratios))
    return stats


def _shape_from(profiles):
    """Median log ratio and spread per hour from release-day profiles.

    Returned unsmoothed; the caller smooths once, after combining the
    like-for-like and all-comparable estimates per hour.
    """
    stats = _hour_stats(profiles)
    centre = {h: v[0] for h, v in stats.items()}
    spread = {h: v[1] for h, v in stats.items()}
    return centre, spread, stats


def _shape_for(case):
    """Centre (log ratio) and spread per hour for this case's comparables.

    Each hour prefers the like-for-like launches when at least three of
    them report it, otherwise all usable comparables, otherwise the
    prior curve for that hour alone -- so one sparse hour never throws
    away the fitted shape for the other twenty-two.
    """
    profiles = []
    like_profiles = []
    for comparable in case.get("comparables") or []:
        profile = _release_day_profile(comparable)
        if profile is None:
            continue
        profiles.append(profile)
        if _is_like_for_like(comparable):
            like_profiles.append(profile)
    like_centre, like_spread, like_stats = _shape_from(like_profiles)
    all_centre, all_spread, all_stats = _shape_from(profiles)
    centre = {}
    spread = {}
    for hour in HOURS:
        if like_stats.get(hour, (0, 0, 0))[2] >= MIN_ANY:
            centre[hour] = like_centre[hour]
            spread[hour] = like_spread[hour]
        elif all_stats.get(hour, (0, 0, 0))[2] >= MIN_ANY:
            centre[hour] = all_centre[hour]
            spread[hour] = all_spread[hour]
        else:
            centre[hour] = math.log(PRIOR_RATIO[hour])
            spread[hour] = PRIOR_SPREAD[hour]
    centre = _smooth_neighbour(centre)
    spread = _smooth_neighbour(spread)
    return centre, {h: max(SPREAD_FLOOR, SPREAD_INFLATION * s)
                    for h, s in spread.items()}


def _round_money(value):
    """Round to 2 decimals, half up, returning an int for whole numbers."""
    rounded = Decimal(str(value)).quantize(Decimal("0.01"),
                                           rounding=ROUND_HALF_UP)
    as_float = float(rounded)
    return int(as_float) if as_float.is_integer() else as_float


def forecast_case(case):
    known = [row for row in case.get("known") or [] if row.get("hour") == 1]
    if not known:
        raise ValueError("case has no hour-1 print")
    anchor = max(1.0, float(known[0]["viewers"]))
    centre, spread = _shape_for(case)
    rows = []
    for row in case.get("forecast") or []:
        hour = int(row["hour"])
        if hour not in centre:
            continue
        quantiles = []
        for z in Z_SCORES:
            value = anchor * math.exp(centre[hour] + z * spread[hour])
            value = min(max(value, 0.01), 1e9)
            quantiles.append(_round_money(value))
        # Guard the ordering after rounding (rounding can only tie).
        for i in range(1, len(quantiles)):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append({"hour": hour, "q": quantiles})
    rows.sort(key=lambda r: r["hour"])
    if [r["hour"] for r in rows] != list(HOURS):
        raise ValueError("forecast does not cover hours 2..24")
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        text = json.dumps(result, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
