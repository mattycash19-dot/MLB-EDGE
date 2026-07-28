# MLB Edge Dashboard

**Live site:** refreshes automatically every 30 minutes via GitHub Actions
(`.github/workflows/refresh.yml`) and publishes to GitHub Pages — see the
repo's "Pages" deployment for the current URL. `report.json`,
`predictions_log.jsonl`, and `odds_history.jsonl` are committed back to the
repo by that workflow after each run, since they're the durable state that
makes track record and line movement work across runs (each run starts
from a fresh checkout, so without persisting them, every run would look
like the first run of the day). `dashboard.html` itself is *not* committed
— it's regenerated build output, deployed straight to Pages.

A small daily tool: pulls today's MLB games, estimates each team's win
probability from a statistical model, compares that to the sportsbook
market (devigged), and shows the difference ("edge") in a dashboard.

**This is a research/analysis tool, not a prediction guarantee.** Treat edge
numbers as one input among many, not an answer. Sports betting carries real
financial risk — never bet more than you can afford to lose, and if it stops
feeling fun, that's worth paying attention to.

## What it does

1. Pulls today's MLB schedule from MLB's free public Stats API, and each
   team's season runs scored/allowed from the `/standings` endpoint
   specifically (not `/teams/{id}/stats` — that endpoint returned
   inconsistent, unreliable totals during testing; see note in `mlb_data.py`).
   No signup needed for any of this.
2. Pulls today's probable starting pitchers, computes each one's FIP from
   their season pitching line, and aggregates each team's bullpen ERA from
   its active roster (all free, no key — see "Pitcher/bullpen/park model"
   below).
3. Looks up each venue's park run factor (static reference table).
4. Computes a **model win probability**: projects each team's expected runs
   for today's specific matchup (season offense blended with the actual
   opposing starter/bullpen, park-adjusted), then applies Pythagorean
   expectation + home field. The original season-only version (no pitcher/
   park data) is kept alongside it for comparison.
5. Pulls moneylines from The Odds API (needs a free key — see setup below),
   averages them across sportsbooks, and removes the vig to get a **market
   win probability**. Each pull is also logged so repeated same-day runs can
   show **line movement** (see "Line movement" below).
6. **Edge** = model probability − market probability. Positive edge on a
   side means the model thinks that team is more likely to win than the
   market's price implies.
7. Writes `report.json` (raw data) and `dashboard.html` (the actual page —
   open it in any browser). Also logs every prediction to
   `predictions_log.jsonl` for later calibration checking (see "Backtesting").

## Setup

Requires Python 3 (no external packages — everything uses the standard
library, so there's nothing to `pip install`).

**Odds/edge is optional.** Without an API key the dashboard still works and
shows model win probabilities for every game — you just won't see the
market comparison or edge columns until you add a key.

To enable it:
1. Sign up for a free key at [the-odds-api.com](https://the-odds-api.com/)
   (free tier covers MLB moneylines, no credit card required).
2. Either:
   - `export ODDS_API_KEY=your_key_here` before running, or
   - copy `config.example.json` to `config.json` and paste your key in.

## Running it

```
python3 run_daily.py
```

Then open `dashboard.html` in your browser. Re-run this each morning (or
whenever) to refresh with the day's games and odds.

## How the model works

- **Pythagorean expectation**: a team's expected win percentage based on
  runs scored vs. runs allowed this season — `RS^1.83 / (RS^1.83 + RA^1.83)`.
  This tends to be a better predictor of a team's true talent than raw
  win-loss record, since it smooths out luck in close games.
- **Log5**: Bill James' method for combining two teams' win percentages
  into a head-to-head probability on a neutral field.
- **Home field advantage**: MLB home teams historically win ~53-54% of
  games; the model adds a flat adjustment for this (see `HOME_FIELD_BOOST`
  in `model.py` if you want to tune it).
- **Devigging**: sportsbook odds always sum to slightly more than 100%
  implied probability (their margin/vig). Averaging odds across several
  books and then normalizing to 100% gives a cleaner read on what the
  market actually thinks, versus what any single book is pricing.

## Pitcher/bullpen/park model

- **Starter FIP**: `(13*HR + 3*(BB+HBP) - 2*K) / IP + 3.10`. Uses a fixed
  constant rather than deriving the exact year's league-wide constant —
  doesn't affect pitcher-vs-pitcher comparisons, which is all this uses it for.
- **Bullpen ERA**: pulls the active roster, classifies each pitcher as a
  reliever if `gamesStarted == 0` (or well under half their appearances),
  and computes an innings-weighted ERA across them. (Note: MLB's
  `/teams/{id}/stats` endpoint was tested for this and found unreliable —
  same issue as the season runs bug below — so this aggregates individual
  `/people/{id}/stats` calls instead, which are internally consistent.)
- **Adjusted runs allowed**: blends the starter's FIP (weighted ~57%, a
  typical modern start length) with the bullpen ERA (~43%) into one
  "expected runs allowed per 9" figure for that team, today.
- **Park factor**: a static table in `park_factors.py`, not computed live.
  Park factors are conventionally multi-year regressed averages anyway —
  recomputing from this season alone would be noisier, not better. Refresh
  it periodically from a public source like Fangraphs' park factors page.
  Venue IDs were verified against `/api/v1/teams` directly; the factor
  *values* are directional estimates based on each park's well-known
  reputation, not scraped — treat as approximate.
- **Missing starters**: probable pitchers are often only announced 1-5 days
  out. If missing, that side falls back to league-average pitching (~4.20
  ERA/FIP) rather than guessing.

## Line movement

Real "sharp money" / "public betting %" data is proprietary (Action
Network, Sports Insights, etc. sell it) — there's no honest free
equivalent, so this doesn't pretend to have one. Instead, every time you
run this it logs the devigged consensus odds to `odds_history.jsonl`, and
compares the current read against the earliest one logged for that game
today. Run it more than once a day (e.g. morning and afternoon) to see
movement; on the first run of a day there's nothing to compare against yet
and it says so rather than faking a number.

## Backtesting / calibration

Every prediction gets logged to `predictions_log.jsonl`. Each time you run
`run_daily.py`, it first checks yesterday's (and any other pending) logged
predictions against final scores and marks them resolved. Run
`python3 backtest.py` any time to see calibration: predictions are bucketed
by probability decile and compared against actual win rate in that bucket,
plus an overall Brier score. **Needs ~100+ resolved predictions to mean
anything** — that's a few weeks of daily runs, not something to expect on
day one. Don't trust the model's edge numbers with real money before
checking this.

**Analysis tab (dashboard.html):** alongside today's slate, the dashboard has an
"Analysis" tab with three things: a running changelog of what changed in the
model and why (`model_changelog.json`), a pick-by-pick postmortem for every
resolved graded pick (correct picks get a one-liner; misses get a best-effort
read on whether something specific pointed the wrong way — an unusually large
market disagreement, recent form the model doesn't use, or just a thin edge —
versus "no clear factor, ordinary variance"), and a running list of
accuracy-improvement ideas not yet implemented. `backtest.log_predictions()`
now also saves each pick's starter FIP, bullpen ERA, park factor, projected
runs, and recent form alongside the probabilities, specifically so a future
surprising result (like the 19-point Cardinals gap on 2026-07-27, which
couldn't be diagnosed after the fact) has something to actually check.

## Files

- `mlb_data.py` — free MLB schedule/stats fetcher (no key needed)
- `pitching.py` — probable pitchers, FIP, bullpen ERA (no key needed)
- `park_factors.py` — static park run-factor lookup table
- `odds_data.py` — Odds API fetcher + devigging (needs a free key)
- `line_movement.py` — logs odds snapshots and computes same-day movement
- `model.py` — all the probability/edge math
- `build_report.py` — orchestrates the above into `report.json`
- `dashboard.py` — renders `report.json` into `dashboard.html`
- `backtest.py` — logs predictions, reconciles against results, checks calibration, generates postmortems
- `model_changelog.json` — dated log of model/code changes, shown on the dashboard's Analysis tab
- `run_daily.py` — the script you actually run

## Verified live (2026-07-27 slate, real API key)

Ran the full pipeline end to end with real data: live MLB standings, live
moneylines across 9 real sportsbooks. A few real results from that run:

- Philadelphia Phillies @ Miami Marlins: model liked the home Marlins
  (55.3%) despite their worse record, because Marlins' run differential
  edges out the Phillies'; the market had Phillies as a solid favorite
  (60.3%) — a 15.6 point gap. This is the clearest illustration of the
  model's biggest blind spot: it has no idea who's starting on the mound.
  A real bettor would know that gap is probably explained by pitching
  matchup, not a market inefficiency. Don't mistake "biggest edge" for
  "best bet" without checking the starters first.
- Smaller, more plausible gaps (4-6 points) showed up in Orioles@Tigers,
  Yankees@White Sox, Mariners@Rangers, and Diamondbacks@Pirates — the kind
  of size you'd expect from a reasonable but imperfect model disagreeing
  with a sharp market, rather than a real, actionable inefficiency.

## Scope note (re: the "elite quant analyst" prompt)

Matt forwarded an email with a much larger spec — full ML ensemble
(XGBoost/CatBoost/LightGBM/Bayesian hierarchical/100k Monte Carlo sims),
Statcast-level batter/pitcher metrics (barrel%, exit velo, spin rate,
CSW%), umpire tendencies, weather, defensive runs saved, and real sharp-
money/public-betting-%/line-movement data. Built what's honestly
achievable with free public data in this pass (starter FIP, bullpen ERA,
park factors, self-collected line movement, calibration logging) and did
NOT build the rest, on purpose:

- **Sharp money / public betting % / reverse line movement**: genuinely
  proprietary, no honest free source exists. Self-collected line movement
  (above) is the closest legitimate substitute.
- **Full ML ensemble**: needs years of labeled historical data and a real
  backtesting pipeline to be trustworthy. A hastily-assembled version
  wouldn't actually be better calibrated than the log5/Pythagorean model
  here — it would just look more impressive while being equally (or more)
  guesswork. Worth revisiting once `backtest.py` has enough history to know
  whether the current, simpler model even needs replacing.
- **Statcast granular metrics** (barrel%, exit velo, spin rate, xwOBA,
  umpire zone tendencies, weather, defensive runs saved): legitimately
  available for free via Baseball Savant, just not built this pass —
  reasonable next addition once the current pieces have been checked
  against real results.

The risk being managed here: outputting things like "Confidence: 87,
Kelly stake: 4.2%" without real backtested calibration behind them would be
fabricated precision, not rigor — exactly the kind of number that gets
someone to bet more than they should.

## Ideas for next steps

- Once `backtest.py` has enough resolved predictions (100+), check
  calibration before trusting edge numbers with real money.
- Add Statcast-level batter/pitcher metrics (barrel%, xwOBA) from Baseball
  Savant if the simpler FIP-based model proves undercalibrated.
- Add other markets (run line / totals), not just moneyline.
- Ask to have this run automatically every morning (and maybe again in the
  afternoon, to build line-movement history) via a scheduled task.
