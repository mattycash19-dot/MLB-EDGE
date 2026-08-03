"""
NRFI prediction logging + reconciliation + track record - the same
discipline as backtest.py (log every pick with its real inputs, reconcile
against what actually happened, never grade with hindsight), applied to
the separate NRFI model in nrfi.py.

Kept as its own log file (nrfi_log.jsonl) and module rather than merged
into backtest.py / predictions_log.jsonl because NRFI is a genuinely
different bet (a first-inning-only outcome, not a game winner) with its
own grading rule and, notably, its own reconciliation timing: a NRFI pick
is knowable as soon as the 1st inning ends (see
nrfi.get_linescore_first_inning), often 15-20 minutes into a game - far
sooner than a game-winner pick, which needs the whole game to finish. That
timing difference is exactly why this isn't just another field bolted
onto the main log.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
import nrfi

LOG_PATH = os.path.join(os.path.dirname(__file__), "nrfi_log.jsonl")


def _read_all(path=LOG_PATH):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _write_all(records, path=LOG_PATH):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def log_predictions(report, path=LOG_PATH):
    """
    Appends one record per game in `report` that has NRFI data (see
    build_report.build()), skipping any game_pk+date already logged so
    re-running the same day doesn't duplicate. Records the full factor
    breakdown at prediction time, not just the final probability - the
    same principle as backtest.log_predictions(): a future postmortem
    should never hit a dead end because the inputs weren't saved (that's
    exactly what happened to the main model before v8, see
    model_changelog.json).
    """
    existing = _read_all(path)
    logged_keys = {(r["date"], r["game_pk"]) for r in existing}

    new_records = []
    for g in report.get("games", []):
        n = g.get("nrfi")
        if not n:
            continue
        key = (report["date"], g["game_pk"])
        if key in logged_keys:
            continue
        new_records.append({
            "date": report["date"],
            "game_pk": g["game_pk"],
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "nrfi_prob": n["nrfi_prob"],
            "predicted_side": "NRFI" if n["nrfi_prob"] >= 0.5 else "YRFI",
            "home_starter_1st_rate": n.get("home_starter_1st_rate"),
            "away_starter_1st_rate": n.get("away_starter_1st_rate"),
            "home_starter_1st_starts": n.get("home_starter_1st_starts"),
            "away_starter_1st_starts": n.get("away_starter_1st_starts"),
            "home_lineup_obp": n.get("home_lineup_obp"),
            "away_lineup_obp": n.get("away_lineup_obp"),
            "home_starter_rest_days": n.get("home_starter_rest_days"),
            "away_starter_rest_days": n.get("away_starter_rest_days"),
            "lineup_posted": n.get("lineup_posted"),
            "resolved": False,
            "actual_result": None,  # "NRFI" or "YRFI" once known
            "home_1st_runs": None,
            "away_1st_runs": None,
        })

    if new_records:
        with open(path, "a") as f:
            for r in new_records:
                f.write(json.dumps(r) + "\n")
    return len(new_records)


def reconcile(path=LOG_PATH):
    """
    For every unresolved logged prediction, checks whether that game's 1st
    inning is complete yet (nrfi.get_linescore_first_inning - resolves
    well before the whole game finishes) and records the real result if
    so. Returns count newly resolved.
    """
    records = _read_all(path)
    newly_resolved = 0
    for r in records:
        if r["resolved"]:
            continue
        result = nrfi.get_linescore_first_inning(r["game_pk"])
        if result is None:
            continue
        home_runs, away_runs = result
        r["resolved"] = True
        r["home_1st_runs"] = home_runs
        r["away_1st_runs"] = away_runs
        r["actual_result"] = "NRFI" if (home_runs == 0 and away_runs == 0) else "YRFI"
        newly_resolved += 1
    _write_all(records, path)
    return newly_resolved


# Confidence tiers, checked high-to-low against each pick's distance from a
# 50/50 coin flip. There's no market line to compare against yet (see
# nrfi.py / README - unverified whether this site's Odds API plan even
# offers a first-inning market), so "confidence" here is the model's own
# probability lean, not edge vs. a real price the way the main model's
# tiers work. Thresholds picked from the actual observed distribution of
# nrfi_prob across logged picks (median lean ~13.5pts, 75th percentile
# ~22.6pts) rather than copied blindly from the main model's edge-vs-market
# tiers, which measure a different thing.
CONFIDENCE_TIERS = [
    (20.0, "High confidence (20+ pt lean)"),
    (10.0, "Medium confidence (10-20 pt lean)"),
    (0.0, "Low confidence (0-10 pt lean)"),
]


def compute_track_record(path=LOG_PATH, tiers=CONFIDENCE_TIERS):
    """
    Was the side actually favored (NRFI if nrfi_prob>=0.5, else YRFI) the
    side that actually happened? Also reports the observed NRFI rate
    across all resolved games as a sanity check against MLB's historical
    ~50-52% league-wide rate - if this drifts far from that with enough
    sample, it's a signal something in the model or the data is off,
    independent of whether the picks themselves are winning.

    Also buckets the record by confidence tier (see CONFIDENCE_TIERS above),
    computed fresh from every resolved pick already in the log each time
    this runs - so a newly added tier immediately reflects the full history
    already collected, not just picks logged going forward.
    """
    records = [r for r in _read_all(path) if r.get("resolved") and r.get("actual_result")]
    n = len(records)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "win_pct": None, "observed_nrfi_rate": None, "by_tier": []}
    wins = sum(1 for r in records if r["predicted_side"] == r["actual_result"])
    nrfi_count = sum(1 for r in records if r["actual_result"] == "NRFI")

    tier_stats = {name: {"wins": 0, "losses": 0} for _, name in tiers}
    for r in records:
        correct = r["predicted_side"] == r["actual_result"]
        lean = abs(r["nrfi_prob"] - 0.5) * 100
        for threshold, name in tiers:
            if lean >= threshold:
                tier_stats[name]["wins" if correct else "losses"] += 1
                break

    def _tier_pct(stats):
        total = stats["wins"] + stats["losses"]
        return round(stats["wins"] / total, 3) if total else None

    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "win_pct": round(wins / n, 3),
        "observed_nrfi_rate": round(nrfi_count / n, 3),
        "by_tier": [
            {"tier": name, **tier_stats[name], "win_pct": _tier_pct(tier_stats[name])}
            for _, name in tiers
        ],
    }


def generate_postmortems(path=LOG_PATH):
    """
    Same idea as backtest.generate_postmortems(): a plain-English read on
    every resolved pick, correct or not, grounded only in numbers that
    were actually logged - never an invented reason.
    """
    records = [r for r in _read_all(path) if r.get("resolved") and r.get("actual_result")]
    records.sort(key=lambda r: r["date"], reverse=True)

    out = []
    for r in records:
        correct = r["predicted_side"] == r["actual_result"]
        score = f"{r['away_1st_runs']}-{r['home_1st_runs']} in the 1st"

        if correct:
            explanation = f"Correct - {score}."
        else:
            reasons = []
            if not r.get("lineup_posted"):
                reasons.append(
                    "neither lineup was posted yet when this was predicted, so Order Check "
                    "had no real data to work with"
                )
            if (r.get("home_starter_1st_starts") or 0) < 5 or (r.get("away_starter_1st_starts") or 0) < 5:
                reasons.append(
                    "at least one starter's first-inning rate was based on a small sample "
                    "(under 5 starts) - noisy this early"
                )
            if not reasons:
                reasons.append(
                    "no single factor stands out - the 1st inning is a small, high-variance "
                    "sample (usually 3-6 batters total), so a miss here doesn't necessarily "
                    "mean anything was wrong with the inputs"
                )
            explanation = f"{score}. " + "; ".join(reasons) + "."

        out.append({
            "date": r["date"],
            "matchup": f"{r['away_team']} @ {r['home_team']}",
            "predicted_side": r["predicted_side"],
            "nrfi_prob": r["nrfi_prob"],
            "actual_result": r["actual_result"],
            "correct": correct,
            "explanation": explanation,
        })
    return out


if __name__ == "__main__":
    n = reconcile()
    print(f"Newly resolved: {n}")
    print(json.dumps(compute_track_record(), indent=2))
