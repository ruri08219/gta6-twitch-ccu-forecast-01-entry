# GTA VI launch-day Twitch viewers — hour-by-hour forecast

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/ruri08219/gta6-twitch-ccu-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/ruri08219/gta6-twitch-ccu-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for the [make.fun bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), hours 2–24, as five quantiles
(5 / 25 / 50 / 75 / 95%) per hour, given everything recorded up to the end
of hour 1. `main.py` is Python 3.13, standard library only, no network,
deterministic, and runs in well under the 8-second limit.

## Model

A diurnal curve anchored at the hour-1 print. Launch-day Twitch audiences
for big console games follow a strong within-day shape measured against
the first hour: a dip in the small hours (hour 1 is 00:00–01:00 UTC — the
UK and Europe have just unlocked, the US is still locked), then a climb
as the US unlocks (05:00 / 08:00 UTC) and the US evening arrives, peaking
around hours 19–21 at roughly 2.5× hour 1.

The shape is estimated from the case's own `comparables`, not hard-coded:

1. For each past launch, take its release-day hourly viewers and form the
   log ratio of each hour to that launch's hour 1.
2. Keep only **like-for-like** launches: console-only releases with a
   rolling midnight-local unlock — no PC release, no early access, no
   simultaneous global unlock, no free-to-play/beta. Those are the launches
   whose hour 1 means the same thing as GTA VI's hour 1. Launches with a
   PC or single-time unlock have a totally different hour-1 meaning (hour 1
   can be near zero while the evening is hundreds of times bigger), so they
   are excluded from the shape.
3. Per hour, the forecast centre is the **median** log ratio across the
   kept launches, smoothed with a 3-point moving average.
4. The spread per hour is the **standard deviation** of those log ratios,
   smoothed the same way, inflated ×1.5, with a floor of 0.30 log units.
   The inflation is deliberate: with only a handful of launches the raw
   sample spread understates how far a new launch can sit from the median.
5. Quantiles: `q = hour1 × exp(median_h + z_tau × spread_h)`.

Fallbacks: each hour prefers the like-for-like launches when at least
three of them report that hour, otherwise all usable comparables, and
otherwise a fixed prior curve (measured from the same kind of launches)
for that hour alone — so one sparse hour never throws away the fitted
shape for the other twenty-two.

The case's own pre-release history is deliberately **not** used to adjust
the shape: on the comparable launches, neither the hour-1 print's size nor
the pre-midnight level predicts the evening growth (correlation of the
pre-midnight / hour-1 ratio with the hour-19 / hour-1 ratio ≈ −0.09), so
adding it would be fitting noise.

## Practice validation

The kit ships no practice answers, so the model was validated by
leave-one-out over the comparables inside the practice cases: each past
launch in turn was treated as the target (its hour 1 as the anchor, its
hours 2–24 as the truth), the curve was fitted on the remaining launches,
and the pinball loss on the log scale was scored exactly as the contest
scores it. Mean pinball loss:

| validation set | this model | house baseline (persistence) |
| --- | --- | --- |
| like-for-like launches (n=6) | **0.249** | 0.349 |
| all 37 launches | 0.820 | 0.930 |

On the launches that actually resemble GTA VI, the model beats the house
baseline by ~29%, with 90% coverage of 0.906 (honest ≈ 0.9). Per-launch
leave-one-out losses for this model: Ghost of Yōtei 0.24, Saros 0.35,
FINAL FANTASY VII REBIRTH 0.21, The Last of Us Part II 0.35,
Ghost of Tsushima 0.16, Stellar Blade 0.18 (baseline: 0.47, 0.60, 0.17,
0.25, 0.23, 0.37 respectively). The model wins on 4 of the 6; it loses on
the two flattest launches (Rebirth and The Last of Us Part II, whose
evenings only reached 1.3–1.5× hour 1) because the median curve expects
the usual ~2.5× evening climb. Two candidate refinements were tested and
rejected: damping the curve toward 1.0 (gains ≤0.003 on the 6-launch set
while slightly worsening the all-launch score) and adjusting the shape
from the case's own pre-release history (no predictive signal, r ≈ −0.09)
— both would be fitting noise on six launches.

## Verification (local, 2026-11-17)

- `main.py` run on all four practice cases (p00–p03) twice each:
  byte-identical outputs, exit 0, ~0.19–0.36 s per case (limit 8 s).
- Output format validated on all four: exactly 23 rows, hours 2–24 each
  once, five quantiles each, all finite, > 0, ≤ 1e9, non-decreasing.
- Forecast median curve on the practice cases (same comparables in all
  four): hour 2 ≈ 0.71× hour 1, hour 4 ≈ 0.67×, hour 12 ≈ 0.99×,
  hour 15 ≈ 1.73×, hour 19 ≈ 2.53×, hour 20 ≈ 2.67×, hour 24 ≈ 2.33×.
- Robustness: with the like-for-like comparables' release-day hours
  deleted, and with no comparables at all, the program still exits 0 and
  writes valid output (per-hour fallback to all comparables, then to the
  prior curve).

Note: the kit ships no practice answers, so the practice cases
themselves cannot be scored locally — the numbers above are the
leave-one-out scores over the comparables, which is the honest local
proxy. The server grades the practice cases.

## Running it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory and writes `<id>.out` as
`{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}, ...]}` for
hours 2–24.
