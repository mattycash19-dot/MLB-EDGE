#!/usr/bin/env python3
"""
Run this once a day (morning, before first pitch) to refresh the dashboard.
Running it a few times through the day also builds up line-movement history
(see line_movement.py) - that's optional, once a day is enough for the core
dashboard.

Usage:
    python3 run_daily.py

Output:
    report.json         - raw data for today
    dashboard.html      - open this in a browser to see today's games
    predictions_log.jsonl - accumulating log of every prediction made, for
                            later calibration checking (see backtest.py)
    nrfi_log.jsonl         - same idea, for the separate NRFI model (see
                            nrfi.py / nrfi_backtest.py) - resolves faster
                            since a NRFI pick only needs the 1st inning
    odds_history.jsonl    - accumulating log of odds snapshots, for line
                            movement tracking (see line_movement.py)

First-time setup for odds/edge (optional but recommended):
    1. Sign up for a free key at https://the-odds-api.com/
    2. Either:
       - set an environment variable:  export ODDS_API_KEY=your_key_here
       - or copy config.example.json to config.json and paste your key in

Without a key, this still works and shows model win probabilities for every
game today - you just won't get market comparison / edge until you add one.

Note: with the starting pitcher + bullpen additions, this now makes on the
order of a couple hundred API calls (roster + season stats for every
pitcher on both teams, for every game) instead of a couple dozen. Still
free, still no rate-limit concerns against MLB's public API, but expect
this to take a bit longer to run than the first version did - that's normal.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import build_report
import dashboard
import backtest
import nrfi_backtest


def main():
    print("Reconciling yesterday's (and earlier) logged predictions against final scores...")
    try:
        n_resolved = backtest.reconcile()
        print(f"  Newly resolved: {n_resolved}")
    except Exception as e:
        print(f"  Skipped (couldn't reconcile: {e})")

    print("Reconciling NRFI predictions (resolves as soon as a game's 1st inning ends, "
          "not the whole game)...")
    try:
        n_nrfi_resolved = nrfi_backtest.reconcile()
        print(f"  Newly resolved: {n_nrfi_resolved}")
    except Exception as e:
        print(f"  Skipped (couldn't reconcile: {e})")

    print("\nFetching today's MLB schedule, team stats, starters, and bullpens...")
    report = build_report.build()
    json_path = build_report.write_report(report)
    html_path = dashboard.render(report)

    try:
        n_logged, n_upgraded = backtest.log_predictions(report)
        print(f"Logged {n_logged} new predictions for calibration tracking.")
        if n_upgraded:
            print(f"Upgraded {n_upgraded} earlier ungraded picks now that market odds are available.")
    except Exception as e:
        print(f"Could not log predictions: {e}")

    try:
        n_nrfi_logged = nrfi_backtest.log_predictions(report)
        print(f"Logged {n_nrfi_logged} new NRFI predictions.")
    except Exception as e:
        print(f"Could not log NRFI predictions: {e}")

    print(f"\n{len(report['games'])} games for {report['date']}")
    if report["odds_available"]:
        n_with_odds = sum(1 for g in report["games"] if g["home_market_prob"] is not None)
        print(f"Odds found for {n_with_odds}/{len(report['games'])} games.")
    else:
        print(f"No odds: {report['odds_error']}")

    print(f"\nWrote:\n  {json_path}\n  {html_path}")
    print(f"\nOpen dashboard.html in your browser to view it.")
    print(f"Run `python3 backtest.py` any time to check calibration once enough predictions have resolved.")


if __name__ == "__main__":
    main()
