"""
Free, legitimate line-movement tracking: NOT a paid "sharp money" or "public
betting %" feed (those are proprietary - Action Network, Sports Insights,
etc. sell that data and there's no honest free equivalent). Instead, this
builds our own history by snapshotting the devigged consensus odds every
time the report runs, and comparing against the earliest snapshot recorded
for that game today.

This is a real, legitimate proxy for "is the market moving on this game,
and which way" - it just requires running this a few times a day (e.g. via
a scheduled task every few hours) to build up enough snapshots to be
useful. On the first run of a day there's nothing to compare against yet,
which is expected and reported as such rather than faked.
"""
import json
import os
from datetime import datetime, date

LOG_PATH = os.path.join(os.path.dirname(__file__), "odds_history.jsonl")


def append_snapshot(game_date, game_pk, home_team, away_team, home_prob, away_prob, path=LOG_PATH):
    record = {
        "logged_at": datetime.now().isoformat(),
        "game_date": game_date,
        "game_pk": game_pk,
        "home_team": home_team,
        "away_team": away_team,
        "home_prob": home_prob,
        "away_prob": away_prob,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _read_all(path=LOG_PATH):
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def get_movement(game_pk, current_home_prob, game_date=None, path=LOG_PATH):
    """
    Returns (movement_pts, opening_home_prob, opening_away_prob,
    num_snapshots_today) for a game, comparing current_home_prob against
    the earliest snapshot logged today for this game_pk. Returns
    (None, None, None, 0) if this is the first snapshot of the day
    (nothing to compare against yet). Opening probabilities are returned
    for both sides (not just home) so callers can show the actual
    opening price alongside the current one, not just the net point
    movement.
    """
    game_date = game_date or date.today().isoformat()
    records = [
        r for r in _read_all(path)
        if r["game_pk"] == game_pk and r["game_date"] == game_date
    ]
    if not records:
        return None, None, None, 0
    records.sort(key=lambda r: r["logged_at"])
    opening_home = records[0]["home_prob"]
    opening_away = records[0]["away_prob"]
    return round(current_home_prob - opening_home, 4), opening_home, opening_away, len(records)
