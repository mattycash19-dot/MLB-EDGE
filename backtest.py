"""
Prediction logging + calibration checking.

The whole point: a model that says "60% win probability" should be right
about 60% of the time across many such predictions, not just look
plausible. This module logs every prediction made, then later reconciles
each against the actual final score, then buckets predictions to check
calibration (does the ~60% bucket actually win ~60% of the time?).

NOTE ON VERIFICATION: reconcile() reads `isWinner` off MLB's schedule
response for finished games, which is a documented field of that endpoint
(see the community-maintained MLB-StatsAPI wiki). During development, the
sandbox this was built in never returned a "Final" game state for any date
tested (every date came back "Preview", even ones that should already have
been played) - which suggests that environment's MLB data may be a test/
synthetic mirror rather than a fully live feed, so this couldn't be
end-to-end verified against a real completed game in that session. The
parsing logic itself is straightforward and defensively coded (falls back
to comparing raw scores if isWinner is absent), but treat calibration
output with appropriate skepticism until it's been run for real over a
week or two of actual completed games on your own machine.
"""
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

BASE = "https://statsapi.mlb.com/api/v1"
LOG_PATH = os.path.join(os.path.dirname(__file__), "predictions_log.jsonl")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mlb-edge-calculator/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


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
    Appends one record per game in `report` (the same dict build_report.build()
    returns), skipping any game_pk+date already logged so re-running the
    same day doesn't create duplicates.

    Exception: if a game was already logged today but came in ungraded
    (picked_side=None - no market odds were available yet, e.g. the day's
    first run happened before an odds key was configured, or before books
    had posted lines) and it's still unresolved, this upgrades that record
    in place once real odds show up in a later run the same day, instead
    of leaving it permanently ungraded. A game that's already resolved is
    never touched - retroactively assigning it a "pick" after the result
    is known would be grading with hindsight, not a real prediction.
    """
    existing = _read_all(path)
    by_key = {(r["date"], r["game_pk"]): i for i, r in enumerate(existing)}

    def _pick(g):
        # "the pick": whichever side has positive edge over the market (see
        # dashboard's "Model likes" column - this is the same logic). Only
        # gradeable if market odds were available for this game.
        home_edge, away_edge = g.get("home_edge"), g.get("away_edge")
        if home_edge is None or away_edge is None:
            return None, None, None
        if home_edge >= away_edge:
            return "home", g["home_team"], round(home_edge * 100, 2)
        return "away", g["away_team"], round(away_edge * 100, 2)

    new_records = []
    upgraded = 0
    for g in report["games"]:
        key = (report["date"], g["game_pk"])
        picked_side, picked_team, edge_pts = _pick(g)

        if key in by_key:
            r = existing[by_key[key]]
            if r.get("picked_side") is None and not r.get("resolved") and picked_side is not None:
                r["home_model_prob"] = g["home_model_prob"]
                r["home_market_prob"] = g["home_market_prob"]
                r["picked_side"] = picked_side
                r["picked_team"] = picked_team
                r["edge_pts"] = edge_pts
                upgraded += 1
            continue

        new_records.append({
            "date": report["date"],
            "game_pk": g["game_pk"],
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "home_model_prob": g["home_model_prob"],
            "home_market_prob": g["home_market_prob"],
            "picked_side": picked_side,
            "picked_team": picked_team,
            "edge_pts": edge_pts,
            "resolved": False,
            "home_won": None,
        })

    if upgraded:
        _write_all(existing, path)
    if new_records:
        with open(path, "a") as f:
            for r in new_records:
                f.write(json.dumps(r) + "\n")
    return len(new_records), upgraded


def reconcile(path=LOG_PATH):
    """
    For every unresolved logged prediction, checks whether that game is
    Final yet and if so records who won. Returns count newly resolved.
    """
    records = _read_all(path)
    unresolved_dates = {r["date"] for r in records if not r["resolved"]}
    results_by_date = {}
    for d in unresolved_dates:
        data = _get(f"{BASE}/schedule?sportId=1&date={d}")
        by_pk = {}
        for day in data.get("dates", []):
            for g in day.get("games", []):
                if g["status"]["abstractGameState"] != "Final":
                    continue
                home = g["teams"]["home"]
                away = g["teams"]["away"]
                home_won = home.get("isWinner")
                if home_won is None and "score" in home and "score" in away:
                    home_won = home["score"] > away["score"]
                by_pk[g["gamePk"]] = home_won
        results_by_date[d] = by_pk

    newly_resolved = 0
    for r in records:
        if r["resolved"]:
            continue
        result = results_by_date.get(r["date"], {}).get(r["game_pk"])
        if result is not None:
            r["resolved"] = True
            r["home_won"] = result
            newly_resolved += 1

    _write_all(records, path)
    return newly_resolved


def reconcile_from_fetched(schedule_data, path=LOG_PATH):
    """
    Same job as reconcile(), but takes an already-fetched schedule response
    (the raw JSON from GET /schedule?sportId=1&date=<d>, one call per date
    that has unresolved predictions) instead of fetching it itself. Exists
    because reconcile()'s own urllib call is blocked by this sandbox's proxy
    for statsapi.mlb.com (confirmed 2026-07-27), while the web-fetch tool can
    reach it fine - so an agent can fetch the JSON and hand it to this
    function instead. schedule_data should be keyed by the date the games
    are for; pass one date's response at a time (mirrors reconcile()'s
    per-date loop, just inverted so the caller controls the fetching).
    """
    records = _read_all(path)
    by_pk = {}
    for day in schedule_data.get("dates", []):
        for g in day.get("games", []):
            if g["status"]["abstractGameState"] != "Final":
                continue
            home = g["teams"]["home"]
            away = g["teams"]["away"]
            home_won = home.get("isWinner")
            if home_won is None and "score" in home and "score" in away:
                home_won = home["score"] > away["score"]
            by_pk[g["gamePk"]] = home_won

    newly_resolved = 0
    for r in records:
        if r["resolved"]:
            continue
        result = by_pk.get(r["game_pk"])
        if result is not None:
            r["resolved"] = True
            r["home_won"] = result
            newly_resolved += 1

    _write_all(records, path)
    return newly_resolved


def compute_calibration(path=LOG_PATH, num_buckets=10):
    """
    Buckets resolved predictions by home_model_prob into deciles and
    compares average predicted probability vs actual home-win rate in each
    bucket. Also returns the Brier score (mean squared error between
    predicted prob and 0/1 outcome - lower is better, 0.25 is what
    always-guess-50% gets, well under that is good).
    """
    records = [r for r in _read_all(path) if r["resolved"] and r["home_won"] is not None]
    if len(records) < 20:
        return {
            "enough_data": False,
            "n": len(records),
            "message": f"Only {len(records)} resolved predictions logged so far - "
                       f"need a few weeks of daily runs (aim for 100+) before calibration "
                       f"numbers mean much.",
        }

    buckets = [[] for _ in range(num_buckets)]
    brier_terms = []
    for r in records:
        p = r["home_model_prob"]
        outcome = 1 if r["home_won"] else 0
        brier_terms.append((p - outcome) ** 2)
        idx = min(int(p * num_buckets), num_buckets - 1)
        buckets[idx].append((p, outcome))

    bucket_summary = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        avg_pred = sum(x[0] for x in b) / len(b)
        actual_rate = sum(x[1] for x in b) / len(b)
        bucket_summary.append({
            "range": f"{i*100//num_buckets}-{(i+1)*100//num_buckets}%",
            "n": len(b),
            "avg_predicted": round(avg_pred, 3),
            "actual_win_rate": round(actual_rate, 3),
        })

    return {
        "enough_data": True,
        "n": len(records),
        "brier_score": round(sum(brier_terms) / len(brier_terms), 4),
        "buckets": bucket_summary,
    }


# Confidence tiers, checked high-to-low against each pick's edge (percentage
# points of win probability over the market - see "edge_pts" above). Tune
# these thresholds once real history accumulates and shows where the model
# actually separates well vs. poorly.
CONFIDENCE_TIERS = [
    (10.0, "High confidence (10+ pt edge)"),
    (5.0, "Medium confidence (5-10 pt edge)"),
    (0.0, "Low confidence (0-5 pt edge)"),
]


def compute_track_record(path=LOG_PATH, tiers=CONFIDENCE_TIERS):
    """
    The simple, at-a-glance version of calibration: for every resolved,
    gradeable prediction (market odds were available, so there was an
    actual "pick" - see log_predictions), was the team the model favored
    over the market the one that actually won? Buckets that win/loss record
    by how big the edge was, so you can see e.g. "high-confidence picks are
    5-0" versus "low-confidence picks are 3-4" - i.e. whether the model's
    bigger disagreements with the market are actually the more reliable
    ones, which is the whole point of tracking edge in the first place.

    This complements compute_calibration() (which checks the underlying
    probabilities are well-calibrated) with a more intuitive record-style
    view of the picks themselves.
    """
    records = [
        r for r in _read_all(path)
        if r.get("resolved") and r.get("home_won") is not None and r.get("picked_side") is not None
    ]

    def _is_correct(r):
        if r["picked_side"] == "home":
            return bool(r["home_won"])
        return not bool(r["home_won"])

    tier_stats = {name: {"wins": 0, "losses": 0} for _, name in tiers}
    overall = {"wins": 0, "losses": 0}

    for r in records:
        correct = _is_correct(r)
        overall["wins" if correct else "losses"] += 1
        edge = r.get("edge_pts") or 0
        for threshold, name in tiers:
            if edge >= threshold:
                tier_stats[name]["wins" if correct else "losses"] += 1
                break

    def _pct(stats):
        n = stats["wins"] + stats["losses"]
        return round(stats["wins"] / n, 3) if n else None

    return {
        "n": len(records),
        "overall": {**overall, "win_pct": _pct(overall)},
        "by_tier": [
            {"tier": name, **tier_stats[name], "win_pct": _pct(tier_stats[name])}
            for _, name in tiers
        ],
    }


if __name__ == "__main__":
    n = reconcile()
    print(f"Newly resolved: {n}")
    cal = compute_calibration()
    print(json.dumps(cal, indent=2))
    print("\nTrack record by confidence tier:")
    print(json.dumps(compute_track_record(), indent=2))
